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

def list_xlsx() -> list[str]:
    """
    単一ファイルモード用。storage.list_xlsx(prefix="uploads/") は
    “uploads/.../*.xlsx” の **フルキー** を返す前提。
    """
    keys = storage.list_xlsx(prefix="uploads/") or []
    # 念のためxlsxだけに
    keys = [k for k in keys if k.lower().endswith(".xlsx")]
    print(f"[FILES] count={len(keys)} sample={keys[:5]}", flush=True)
    return keys

def norm_sep(path: str) -> str:
    return path.replace("\\", "/")

def sanitize_path_component(name: str) -> str:
    name = name.replace("\x00", "")
    name = name.strip().strip("/").strip("\\")
    name = unicodedata.normalize("NFKC", name)
    if name in (".", ".."):
        name = "_"
    name = name.replace("/", "_").replace("\\", "_")
    name = re.sub(r"[\u0000-\u001F\u007F]", "", name)
    return name or "_"

def decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    # UTF-8 フラグが無ければ cp437→cp932 再解釈
    name = info.filename
    if (info.flag_bits & 0x800) != 0:
        return name
    try:
        raw = name.encode("cp437", errors="strict")
        return raw.decode("cp932", errors="strict")
    except Exception:
        return name

# --- レッスン配下の .xlsx を相対パスで列挙 ---
def list_lessons_all() -> list[str]:
    """
    返り値は **LESSON_DIR からの相対パス**（例: '中1/Excelデータ/lesson1.xlsx'）。
    R2: storage.list_xlsx は 'uploads/lessons/...' のフルキー → LESSON_DIR を剥がす。
    Local: uploads/lessons の物理ディレクトリから再帰列挙。
    """
    if cfg.USE_R2:
        full_keys = storage.list_xlsx(prefix=f"{LESSON_DIR}/") or []
        rels: list[str] = []
        prefix = f"{LESSON_DIR}/"
        for k in full_keys:
            if not k.lower().endswith(".xlsx"):
                continue
            if k.startswith(prefix):
                rels.append(k[len(prefix):])
            else:
                # 念のため防御（想定外キー）
                rels.append(k)
        rels.sort(key=str.lower)
        print(f"[LESSONS:R2] rels count={len(rels)} sample={rels[:5]}", flush=True)
        return rels
    else:
        items: list[str] = []
        if os.path.isdir(LOCAL_LESSON_ROOT):
            for base, _, files in os.walk(LOCAL_LESSON_ROOT):
                for fn in files:
                    if not fn.lower().endswith(".xlsx"):
                        continue
                    full = os.path.join(base, fn)
                    rel = os.path.relpath(full, LOCAL_LESSON_ROOT)
                    items.append(norm_sep(rel))
        items.sort(key=str.lower)
        print(f"[LESSONS:LOCAL] rels count={len(items)} sample={items[:5]}", flush=True)
        return items

def build_lesson_tree() -> dict[str, list[str]]:
    """
    { フォルダ相対パス("")含む : [ 相対パス(ファイル) ... ] }
    """
    items = list_lessons_all()
    tree: dict[str, list[str]] = {}
    for rel in items:
        parts = rel.split("/")
        folder = "" if len(parts) == 1 else "/".join(parts[:-1])
        tree.setdefault(folder, []).append(rel)
    for k in tree:
        tree[k].sort(key=str.lower)
    print(f"[LESSON-TREE] folders={len(tree)} keys={list(tree.keys())[:6]}", flush=True)
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
        # --- 単一 .xlsx ---
        if "file" in request.files and request.files["file"] and request.files["file"].filename:
            file = request.files["file"]
            filename = safe_filename(file.filename)
            _, ext = os.path.splitext(filename)
            if ext.lower() not in cfg.ALLOWED_UPLOAD_EXTENSIONS:
                flash(".xlsx のみアップロード可です。")
                return redirect(url_for("upload"))
            try:
                # 既存どおり uploads/ 直下（フォルダを増やしたい場合はここで調整）
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
                            key = f"{LESSON_DIR}/{rel_path}"
                            storage.upload(file_bytes, key, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                            saved_keys.append(key)
                        else:
                            dst = os.path.join(LOCAL_LESSON_ROOT, *rel_path.split("/"))
                            os.makedirs(os.path.dirname(dst), exist_ok=True)
                            with open(dst, "wb") as f:
                                f.write(file_bytes)
                            saved_keys.append(dst)

                print("[ZIP] saved (first 8):", *saved_keys[:8], sep="\n  ")
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
    files = list_xlsx()                  # ここは **フルキー**（uploads/...）
    lesson_tree = build_lesson_tree()    # ここは **相対パス**（LESSON_DIR から）

    if request.method == "POST":
        select_mode   = request.form.get("select_mode", "single")
        filename      = request.form.get("filename", "")           # ← 単一モード: フルキー
        lesson_folder = request.form.get("lesson_folder", "")      # ← 相対フォルダ
        lesson_files  = request.form.getlist("lesson_files")       # ← 相対ファイル群
        num_questions = request.form.get("num_questions", "")
        mode          = request.form.get("mode", "en-ja")

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
                # 相対ファイルの正当性チェック
                valid_relpaths = set(lesson_tree.get(lesson_folder, []))
                picked = [p for p in lesson_files if p in valid_relpaths]
                if not picked:
                    flash("選択されたファイルがありません（フォルダとファイルを選んでください）。")
                    return redirect(url_for("make"))

                frames = []
                for rel in picked:
                    if cfg.USE_R2:
                        key = f"{LESSON_DIR}/{rel}"       # R2: フルキー化
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
                # 複数レッスンは番号レンジ表記なし
                base_name_for_title = f"{lesson_folder or '（直下）'}: " + ", ".join(os.path.basename(p) for p in picked)
                title_range_part = None

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

                # filename は **フルキー**（uploads/...）
                data = storage.open_xlsx_as_bytes(filename)
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

                # タイトルはベース名のみ
                base_name_for_title = os.path.splitext(os.path.basename(filename))[0]
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
