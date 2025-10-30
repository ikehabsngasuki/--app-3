# app.py
import io
import os
import re
import uuid
import zipfile
import unicodedata
import datetime as dt
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_file

from config import Config
from services.storage import get_storage
from services.pdf_service import register_fonts, build_styles, build_pdf
from utils.files import safe_filename

cfg = Config()
cfg.log_env()

# ディレクトリ作成（ローカル開発で使用）
os.makedirs(cfg.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(cfg.FONTS_DIR, exist_ok=True)

app = Flask(__name__, template_folder=cfg.TEMPLATE_DIR, static_folder="static")
app.secret_key = cfg.SECRET_KEY
app.config["UPLOAD_FOLDER"] = cfg.UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_CONTENT_LENGTH

# ストレージ実体（R2 or Local）
storage = get_storage(cfg)

# PDF 用フォント＆スタイル
FONT_NAME = register_fonts(cfg.FONTS_DIR)
styles = build_styles(FONT_NAME)

# ========= 定数 / ユーティリティ =========
LESSON_DIR = "uploads/lessons"  # ストレージ上の論理ルート
LOCAL_LESSON_ROOT = os.path.join(cfg.UPLOAD_FOLDER, "lessons")  # ローカル実体

def allowed_download(name: str) -> bool:
    _, ext = os.path.splitext(name)
    return ext.lower() in cfg.ALLOWED_DOWNLOAD_EXTENSIONS

def list_xlsx():
    """従来: 単一ファイルモード用（uploads/直下）。storage 実装に依存。"""
    return storage.list_xlsx(prefix="uploads/")

# --- パス正規化 ---
def norm_sep(path: str) -> str:
    return path.replace("\\", "/")

# --- 日本語温存のサニタイズ（危険文字だけ除去） ---
def sanitize_path_component(name: str) -> str:
    name = name.replace("\x00", "")
    name = name.strip().strip("/").strip("\\")
    name = unicodedata.normalize("NFKC", name)
    if name in (".", ".."):
        name = "_"
    # ディレクトリセパレータは無効化（zip-slip対策）
    name = name.replace("/", "_").replace("\\", "_")
    # 制御文字を除去
    name = re.sub(r"[\u0000-\u001F\u007F]", "", name)
    return name or "_"

# --- ZIP エントリ名の文字化け救済（UTF-8 フラグ無し=cp932 前提で再解釈） ---
def decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    """
    UTF-8 フラグ(0x800)が無い場合、zipfile が cp437 とみなした文字列を
    cp437 → cp932 でデコードし直して日本語名を復元する。
    """
    name = info.filename  # str
    if (info.flag_bits & 0x800) != 0:
        return name
    try:
        raw = name.encode("cp437", errors="strict")
        fixed = raw.decode("cp932", errors="strict")
        return fixed
    except Exception:
        return name

# --- レッスン配下の .xlsx を相対パスで列挙 ---
def list_lessons_all() -> list[str]:
    """
    R2：services/storage.py の list_xlsx(prefix) は basename を返すため階層は失われる。
        → 現状は「直下扱い（フォルダなし）」としてファイル名のみ返る。
    Local：uploads/lessons 以下を os.walk で再帰して相対パスを返す（階層維持）。
    """
    if cfg.USE_R2:
        raw = storage.list_xlsx(prefix=f"{LESSON_DIR}/") or []
        # R2 実装は basename を返すのでそのまま扱う（= 直下扱い）
        items = [f for f in raw if f.lower().endswith(".xlsx")]
        print(f"[LESSONS:R2] files (count={len(items)}): sample={items[:5]}")
        return items
    else:
        root = LOCAL_LESSON_ROOT
        items = []
        if os.path.isdir(root):
            for base, _, files in os.walk(root):
                for fn in files:
                    if fn.lower().endswith(".xlsx"):
                        full = os.path.join(base, fn)
                        rel = os.path.relpath(full, root)
                        items.append(norm_sep(rel))
        items.sort(key=lambda p: p.lower())
        print(f"[LESSONS:LOCAL] files (count={len(items)}): sample={items[:5]}")
        return items

def build_lesson_tree():
    """
    lessons配下のフォルダ -> ファイル一覧（相対パス）の辞書に変換。
    直下ファイルは folder_key=""（空文字）。
    """
    items = list_lessons_all()
    tree: dict[str, list[str]] = {}
    for rel in items:
        parts = rel.split("/")
        folder = "" if len(parts) == 1 else "/".join(parts[:-1])
        tree.setdefault(folder, []).append(rel)
    for k in tree:
        tree[k].sort(key=lambda p: p.lower())
    # デバッグ
    print(f"[LESSON-TREE] folders={len(tree)} keys={list(tree.keys())[:6]}")
    return dict(sorted(tree.items(), key=lambda kv: kv[0].lower()))

# ========= ルーティング =========
@app.route("/")
def index():
    files = list_xlsx()
    lesson_tree = build_lesson_tree()
    return render_template("index.html", files=files, lesson_tree=lesson_tree)

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        # --- 従来: 単一 .xlsx ---
        if "file" in request.files and request.files["file"] and request.files["file"].filename:
            file = request.files["file"]
            filename = safe_filename(file.filename)
            _, ext = os.path.splitext(filename)
            if ext.lower() not in cfg.ALLOWED_UPLOAD_EXTENSIONS:
                flash(".xlsx のみアップロード可です。")
                return redirect(url_for("upload"))
            try:
                key = f"uploads/{filename}"
                storage.upload(file, key, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                flash(f"アップロードが完了しました: {filename}")
            except Exception as e:
                flash(f"アップロードに失敗しました: {e}")
            return redirect(url_for("upload"))

        # --- レッスン ZIP 一括 ---
        if "lesson_zip" in request.files and request.files["lesson_zip"] and request.files["lesson_zip"].filename:
            zf = request.files["lesson_zip"]
            if not zf.filename.lower().endswith(".zip"):
                flash("ZIPファイルを選択してください。")
                return redirect(url_for("upload"))
            try:
                data = zf.read()
                saved_keys = []
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for info in z.infolist():
                        if info.is_dir():
                            continue
                        inner = norm_sep(decode_zip_member_name(info))
                        raw_parts = [seg for seg in inner.split("/") if seg and seg not in (".", "..")]
                        if not raw_parts:
                            continue
                        safe_parts = [sanitize_path_component(seg) for seg in raw_parts]
                        rel_path = "/".join(safe_parts)
                        if not rel_path.lower().endswith(".xlsx"):
                            continue

                        file_bytes = z.read(info)

                        if cfg.USE_R2:
                            # R2: オブジェクトキーは階層付きで保存
                            key = f"{LESSON_DIR}/{rel_path}"
                            storage.upload(file_bytes, key, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                            saved_keys.append(key)
                        else:
                            # Local: 物理ディレクトリを作って書き込む（階層保持）
                            dst = os.path.join(LOCAL_LESSON_ROOT, *rel_path.split("/"))
                            os.makedirs(os.path.dirname(dst), exist_ok=True)
                            with open(dst, "wb") as f:
                                f.write(file_bytes)
                            saved_keys.append(dst)

                print("[ZIP] saved (first 8):")
                for i, k in enumerate(saved_keys[:8]):
                    print(f"  [{i}] {k}")
                flash(f"レッスンZIPを展開しました（{len(saved_keys)} 件の .xlsx）" if saved_keys else "ZIP内に .xlsx が見つかりませんでした。")
            except Exception as e:
                flash(f"ZIPの展開に失敗しました: {e}")
            return redirect(url_for("upload"))

        flash("ファイルが選択されていません。")
        return redirect(url_for("upload"))

    files = list_xlsx()
    lesson_tree = build_lesson_tree()
    return render_template("upload.html", files=files, lesson_tree=lesson_tree)

@app.route("/make", methods=["GET", "POST"])
def make():
    files = list_xlsx()
    lesson_tree = build_lesson_tree()

    if request.method == "POST":
        select_mode   = request.form.get("select_mode", "single")
        filename      = request.form.get("filename", "")
        lesson_folder = request.form.get("lesson_folder", "")      # "" は直下
        lesson_files  = request.form.getlist("lesson_files")       # 相対パス
        num_questions = request.form.get("num_questions", "")
        mode          = request.form.get("mode", "en-ja")

        # 出題数チェック
        try:
            num_questions = int(num_questions)
        except ValueError:
            flash("出題数は整数で指定してください。")
            return redirect(url_for("make"))
        if num_questions <= 0:
            flash("出題数は1以上にしてください。")
            return redirect(url_for("make"))

        try:
            if select_mode == "lessons":
                # フォルダ配下のファイルのみ許容
                valid_relpaths = set(lesson_tree.get(lesson_folder, []))
                picked = [p for p in lesson_files if p in valid_relpaths]
                if not picked:
                    flash("選択されたファイルがありません（フォルダとファイルを選んでください）。")
                    return redirect(url_for("make"))

                frames = []
                for rel in picked:
                    if cfg.USE_R2:
                        key = f"{LESSON_DIR}/{rel}"
                        data = storage.open_xlsx_as_bytes(key)
                    else:
                        path = os.path.join(LOCAL_LESSON_ROOT, *rel.split("/"))
                        with open(path, "rb") as f:
                            data = f.read()

                    dfi = pd.read_excel(io.BytesIO(data), engine="openpyxl")
                    required = {"number", "word", "meaning"}
                    missing = required - set(dfi.columns)
                    if missing:
                        flash(f"{rel} に必要な列がありません: {', '.join(sorted(missing))}")
                        return redirect(url_for("make"))

                    num_series_i = pd.to_numeric(dfi["number"], errors="coerce")
                    dfi = dfi.loc[num_series_i.notna()].copy()
                    if dfi.empty:
                        continue
                    dfi["number"] = num_series_i.loc[dfi.index].astype(int)
                    dfi["__source__"] = rel
                    frames.append(dfi)

                if not frames:
                    flash("選択したレッスンに問題データが見つかりませんでした。")
                    return redirect(url_for("make"))

                df = pd.concat(frames, axis=0, ignore_index=True)
                base_name_for_title = f"{lesson_folder or '（直下）'}: " + ", ".join(os.path.basename(p) for p in picked)
                title_range_part = None  # レンジ表示なし（番号は各レッスンでリセットされる想定）

            else:
                # 単一ファイル（番号範囲あり）
                start_num = request.form.get("start_num", "")
                end_num   = request.form.get("end_num", "")
                try:
                    start_num = int(start_num); end_num = int(end_num)
                except ValueError:
                    flash("開始番号・終了番号は整数で指定してください。")
                    return redirect(url_for("make"))
                if start_num > end_num:
                    flash("開始番号は終了番号以下にしてください。"); return redirect(url_for("make"))

                if filename not in files:
                    flash("不正なファイル名です。")
                    return redirect(url_for("make"))

                xlsx_key = f"uploads/{filename}"
                data = storage.open_xlsx_as_bytes(xlsx_key)
                df = pd.read_excel(io.BytesIO(data), engine="openpyxl")

                required = {"number", "word", "meaning"}
                missing = required - set(df.columns)
                if missing:
                    flash(f"必要な列がありません: {', '.join(sorted(missing))}")
                    return redirect(url_for("make"))

                num_series = pd.to_numeric(df["number"], errors="coerce")
                df = df.loc[num_series.notna()].copy()
                if df.empty:
                    flash("number 列に有効な数値がありません。")
                    return redirect(url_for("make"))
                df["number"] = num_series.loc[df.index].astype(int)

                df = df[(df["number"] >= start_num) & (df["number"] <= end_num)]
                if df.empty:
                    flash("指定範囲に該当する問題がありません。")
                    return redirect(url_for("make"))

                base_name_for_title, _ = os.path.splitext(filename)
                title_range_part = f"No.{start_num}–{end_num}"

        except Exception as e:
            flash(f"Excelの読み込みに失敗しました: {e}")
            return redirect(url_for("make"))

        # ランダム抽出
        n = min(num_questions, len(df))
        sample = df.sample(n=n).reset_index(drop=True)

        # 出題モード
        if mode == "en-ja":
            question_col, answer_col = "word", "meaning"; title_base = "英和"
        elif mode == "ja-en":
            question_col, answer_col = "meaning", "word"; title_base = "和英"
        else:
            flash("不正な出題モードです。"); return redirect(url_for("make"))

        # タイトル
        if title_range_part:
            title_common = f"{base_name_for_title} / {title_range_part} / {n}問"
        else:
            title_common = f"{base_name_for_title} / {n}問"
        title_q = f"{title_base}：問題（{title_common}）"
        title_a = f"{title_base}：解答（{title_common}）"

        # 出力
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        q_name = f"questions_{title_base}_{stamp}_{uid}.pdf"
        a_name = f"answers_{title_base}_{stamp}_{uid}.pdf"

        try:
            q_pdf = build_pdf(sample, styles, with_answers=False,
                              question_col=question_col, answer_col=answer_col, title=title_q).read()
            a_pdf = build_pdf(sample, styles, with_answers=True,
                              question_col=question_col, answer_col=answer_col, title=title_a).read()

            if cfg.USE_R2:
                q_key = f"generated/{q_name}"; a_key = f"generated/{a_name}"
                storage.upload(q_pdf, q_key, "application/pdf")
                storage.upload(a_pdf, a_key, "application/pdf")
                return redirect(url_for("download", q=q_key, a=a_key))
            else:
                with open(os.path.join(cfg.UPLOAD_FOLDER, q_name), "wb") as f: f.write(q_pdf)
                with open(os.path.join(cfg.UPLOAD_FOLDER, a_name), "wb") as f: f.write(a_pdf)
                flash("問題と解答PDFを作成しました！")
                return redirect(url_for("download", q=q_name, a=a_name))
        except Exception as e:
            flash(f"PDFの作成に失敗しました: {e}")
            return redirect(url_for("make"))

    return render_template("make.html", files=files, lesson_tree=lesson_tree)

@app.route("/download")
def download():
    q = request.args.get("q"); a = request.args.get("a")
    print("[/download] query:", q, a, "USE_R2:", cfg.USE_R2, flush=True)
    if cfg.USE_R2:
        q_url = a_url = None
        try:
            if q and (q.startswith("generated/") or q.startswith("uploads/")):
                q_url = storage.presign_get(q, cfg.PRESIGN_EXPIRES)
            if a and (a.startswith("generated/") or a.startswith("uploads/")):
                a_url = storage.presign_get(a, cfg.PRESIGN_EXPIRES)
            return render_template("download.html", q_url=q_url, a_url=a_url)
        except Exception:
            return render_template("download.html", q=q, a=a)
    return render_template("download.html", q=q, a=a)

@app.route("/download_file/<filename>")
def download_file(filename):
    filename = safe_filename(filename)
    _, ext = os.path.splitext(filename)
    if ext.lower() not in cfg.ALLOWED_DOWNLOAD_EXTENSIONS:
        flash("許可されていないファイル形式です。")
        return redirect(url_for("download"))
    full_path = os.path.join(cfg.UPLOAD_FOLDER, filename)
    if not os.path.isfile(full_path):
        flash("指定されたファイルが存在しません。")
        return redirect(url_for("download"))
    try:
        return send_file(full_path, as_attachment=True, download_name=filename, conditional=True, max_age=0)
    except Exception as e:
        app.logger.exception(f"send_file failed for {filename}: {e}")
        abort(500)

if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
    )
