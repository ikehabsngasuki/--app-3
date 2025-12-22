# app.py
import io
import os
import uuid
import datetime as dt
import hmac
from urllib.parse import urlencode
import urllib.request
import zipfile

import pandas as pd
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    send_file,
    Response,
    g,
)

from config import Config
from services.storage import get_storage
from services.pdf_service import register_fonts, build_styles, build_pdf
from utils.files import safe_filename

# ===== PDF結合用（pypdf 推奨、なければ PyPDF2）=====
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    from PyPDF2 import PdfReader, PdfWriter  # type: ignore


cfg = Config()
cfg.log_env()

# ディレクトリ作成（ローカル開発で使用）
os.makedirs(cfg.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(cfg.FONTS_DIR, exist_ok=True)

# ローカル開発時に生成された PDF をまとめて置いておくディレクトリ
# 実体は: <BASE_DIR>/uploads/pdfs/
PDF_LOCAL_DIR = os.path.join(cfg.UPLOAD_FOLDER, "pdfs")
os.makedirs(PDF_LOCAL_DIR, exist_ok=True)

app = Flask(__name__, template_folder=cfg.TEMPLATE_DIR, static_folder="static")


@app.route("/healthz", methods=["GET", "HEAD"])
def healthz():
    return "ok", 200


app.secret_key = cfg.SECRET_KEY
app.config["UPLOAD_FOLDER"] = cfg.UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_CONTENT_LENGTH

# ===== Optional Basic認証（Public/認証ありの段階運用） =====
# 認証を『強制』はしない。Authorization ヘッダーが付いている場合のみ認証済み扱いにする。
# 認証ダイアログを出したい場合は /login を開く。

def _basic_auth_enabled() -> bool:
    return bool(cfg.BASIC_AUTH_USER and cfg.BASIC_AUTH_PASS)

def _basic_auth_ok() -> bool:
    auth = request.authorization
    if not auth:
        return False
    return hmac.compare_digest(auth.username or "", cfg.BASIC_AUTH_USER) and hmac.compare_digest(
        auth.password or "", cfg.BASIC_AUTH_PASS
    )

@app.before_request
def _set_auth_flag():
    # 認証情報が未設定なら常に Public 扱い
    if not _basic_auth_enabled():
        g.is_auth = False
        return None
    # Authorization が付いていれば判定（付いていなければ Public）
    g.is_auth = bool(_basic_auth_ok())
    return None

@app.route("/login")
def login():
    """Basic認証の入力ダイアログを出すための入口。

    - USER/PASS が設定されていない場合は Public のまま
    - すでに認証済みならトップへ
    """
    if not _basic_auth_enabled():
        flash("認証（BASIC_AUTH_USER/PASS）が未設定のため、Public モードで動作しています。")
        return redirect(url_for("index"))

    if getattr(g, "is_auth", False):
        flash("認証済みです。")
        return redirect(url_for("index"))

    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": f'Basic realm="{cfg.BASIC_AUTH_REALM}"'},
    )

# ===== 段階制限（Public/認証あり） =====
# NOTE: Render の複数インスタンスや再起動をまたぐ永続的な制限にはなりません。
# まずは最低限の濫用対策として、プロセス内メモリで日次クォータを管理します。

_usage_by_day: dict[tuple[str, str, str], int] = {}

def _client_id() -> str:
    # なるべく代理IPでも安定するよう X-Forwarded-For を優先
    ip = request.headers.get("X-Forwarded-For", "")
    if ip:
        ip = ip.split(",")[0].strip()
    if not ip:
        ip = request.remote_addr or "unknown"
    ua = request.headers.get("User-Agent", "")[:80]
    return f"{ip}|{ua}"

def _today_utc() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d")

def _prune_usage(keep_days: int = 2) -> None:
    # keep_days 日分だけ残す（簡易）
    # key: (date, tier, client_id)
    if not _usage_by_day:
        return
    dates = sorted({k[0] for k in _usage_by_day.keys()})
    if len(dates) <= keep_days:
        return
    for d in dates[:-keep_days]:
        for k in [k for k in list(_usage_by_day.keys()) if k[0] == d]:
            _usage_by_day.pop(k, None)

def _tier(is_auth: bool) -> str:
    return "auth" if is_auth else "public"

def enforce_sets_limits(num_sets: int, *, is_auth: bool) -> None:
    # 絶対上限（全員共通）
    if num_sets > cfg.ABSOLUTE_MAX_SETS_PER_REQUEST:
        abort(403, f"作成部数が多すぎます（最大{cfg.ABSOLUTE_MAX_SETS_PER_REQUEST}部まで）。")

    if is_auth:
        if cfg.AUTH_MAX_SETS_PER_REQUEST > 0 and num_sets > cfg.AUTH_MAX_SETS_PER_REQUEST:
            abort(403, f"認証ユーザーの作成部数は最大{cfg.AUTH_MAX_SETS_PER_REQUEST}部までです。")
    else:
        if num_sets > cfg.PUBLIC_MAX_SETS_PER_REQUEST:
            abort(403, f"非認証（Public）の作成部数は最大{cfg.PUBLIC_MAX_SETS_PER_REQUEST}部までです。")

def consume_daily_quota(num_sets: int, *, is_auth: bool) -> None:
    # 日次の絶対上限（全員共通）
    abs_limit = cfg.ABSOLUTE_MAX_SETS_PER_DAY
    tier_limit = cfg.AUTH_MAX_SETS_PER_DAY if is_auth else cfg.PUBLIC_MAX_SETS_PER_DAY

    # 0以下なら「そのティアは日次上限なし」（ただし absolute は適用）
    if tier_limit <= 0:
        tier_limit = abs_limit

    today = _today_utc()
    t = _tier(is_auth)
    cid = _client_id()
    key = (today, t, cid)
    used = _usage_by_day.get(key, 0)

    if used + num_sets > tier_limit:
        abort(429, "本日の作成上限に達しました。")
    if used + num_sets > abs_limit:
        abort(429, "本日の作成上限に達しました。")

    _usage_by_day[key] = used + num_sets
    _prune_usage()

# ストレージ実体（R2 or Local）
storage = get_storage(cfg)

# PDF 用フォント＆スタイル
FONT_NAME = register_fonts(cfg.FONTS_DIR)
styles = build_styles(FONT_NAME)


# ========= ユーティリティ =========
def list_xlsx() -> list[str]:
    """
    アップロード済み .xlsx を “uploads/.../*.xlsx” のフルキーで返す。
    """
    keys = storage.list_xlsx(prefix="uploads/") or []
    keys = [k for k in keys if k.lower().endswith(".xlsx")]
    print(f"[FILES] count={len(keys)} sample={keys[:5]}", flush=True)
    return keys


def parse_optional_positive_int(
    raw: str | None, *, default: int, min_v: int, max_v: int, label: str
) -> int:
    """
    空欄OKの数値入力をパースする。
    - None/空文字/空白のみ → default
    - 数字 → min_v..max_v の範囲チェック
    """
    s = (raw or "").strip()
    if s == "":
        return default
    try:
        v = int(s)
    except ValueError:
        raise ValueError(f"{label}は整数で指定してください。")
    if v < min_v:
        raise ValueError(f"{label}は{min_v}以上にしてください。")
    if v > max_v:
        raise ValueError(f"{label}が大きすぎます（最大{max_v}まで）。")
    return v


def _read_pdf_bytes_from_identifier(identifier: str) -> bytes:
    """
    /download で items に入れている q/a の値を元に PDF bytes を取得する。
    - USE_R2=True : identifier は "generated/..." などのキー → presign_get → URL から取得
    - USE_R2=False: identifier は ローカルPDFファイル名 → PDF_LOCAL_DIR から読み込み
    """
    if cfg.USE_R2:
        key = identifier
        if not key or not (key.startswith("generated/") or key.startswith("uploads/")):
            raise ValueError("不正なファイルキーです。")

        url = storage.presign_get(key, cfg.PRESIGN_EXPIRES)
        if not url:
            raise ValueError("ダウンロードURLの生成に失敗しました。")

        with urllib.request.urlopen(url) as resp:
            return resp.read()

    filename = safe_filename(identifier)
    full_path = os.path.join(PDF_LOCAL_DIR, filename)
    if not os.path.isfile(full_path):
        raise FileNotFoundError(f"ファイルが存在しません: {filename}")
    with open(full_path, "rb") as f:
        return f.read()


def _merge_pdf_bytes_in_order(pdf_bytes_list: list[bytes]) -> bytes:
    """
    複数PDF(bytes)を順番通りに結合して、結合PDF(bytes)を返す。
    """
    writer = PdfWriter()
    for b in pdf_bytes_list:
        reader = PdfReader(io.BytesIO(b))
        for page in reader.pages:
            writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()


# ========= ルーティング =========
@app.route("/")
def index():
    files = list_xlsx()
    return render_template("index.html", files=files)


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
                key = f"uploads/{filename}"
                storage.upload(
                    file,
                    key,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                flash(f"アップロードが完了しました: {filename}")
            except Exception as e:
                flash(f"アップロードに失敗しました: {e}")
            return redirect(url_for("upload"))

        flash("ファイルが選択されていません。")
        return redirect(url_for("upload"))

    files = list_xlsx()
    return render_template("upload.html", files=files)


@app.route("/make", methods=["GET", "POST"])
def make():
    files = list_xlsx()

    if request.method == "POST":
        filename = request.form.get("filename", "")
        mode = request.form.get("mode", "en-ja")

        # 出題数（必須）
        try:
            num_questions = int(request.form.get("num_questions", ""))
        except ValueError:
            flash("出題数は整数で指定してください。")
            return redirect(url_for("make", file=filename))
        if num_questions <= 0:
            flash("出題数は1以上にしてください。")
            return redirect(url_for("make", file=filename))

        # 作成部数（任意：空欄OK → 1）
        try:
            num_sets = parse_optional_positive_int(
                request.form.get("num_sets"),
                default=1,
                min_v=1,
                max_v=cfg.ABSOLUTE_MAX_SETS_PER_REQUEST,
                label="作成部数",
            )
        except ValueError as e:
            flash(str(e))
            return redirect(url_for("make", file=filename))

        # Public/認証ありでの上限チェック（サーバ側で強制）
        is_auth = bool(getattr(g, "is_auth", False))
        enforce_sets_limits(num_sets, is_auth=is_auth)
        consume_daily_quota(num_sets, is_auth=is_auth)

        # ファイルチェック
        if not filename or filename not in files:
            flash("不正なファイル名です。")
            return redirect(url_for("make"))

        # Excel 読み込み
        try:
            data = storage.open_xlsx_as_bytes(filename)
            df = pd.read_excel(io.BytesIO(data), engine="openpyxl")

            required = {"word", "meaning"}
            missing = required - set(df.columns)
            if missing:
                flash(f"必要な列がありません: {', '.join(sorted(missing))}")
                return redirect(url_for("make", file=filename))

            base_name_for_title = os.path.splitext(os.path.basename(filename))[0]

            has_section_col = "section" in df.columns
            has_number_col = "number" in df.columns

            title_range_part = ""

            # ===== セクションモード =====
            if has_section_col:
                sections_selected = request.form.getlist("sections")
                if not sections_selected:
                    flash("セクションを1つ以上選択してください。")
                    return redirect(url_for("make", file=filename))

                df["__section_str__"] = df["section"].astype(str)
                df = df[df["__section_str__"].isin(sections_selected)]
                if df.empty:
                    flash("選択したセクションに該当する問題がありません。")
                    return redirect(url_for("make", file=filename))

                # number 列があれば、表示用に整数へ（必須ではない）
                if has_number_col:
                    num_series = pd.to_numeric(df["number"], errors="coerce")
                    df.loc[num_series.notna(), "number"] = (
                        num_series.loc[num_series.notna()].astype(int)
                    )

                title_range_part = "sections: " + ", ".join(sections_selected)

            # ===== 番号レンジモード =====
            else:
                if not has_number_col:
                    flash("番号範囲で出題するには number 列が必要です。")
                    return redirect(url_for("make", file=filename))

                num_series = pd.to_numeric(df["number"], errors="coerce")
                df = df.loc[num_series.notna()].copy()
                if df.empty:
                    flash("number 列に有効な数値がありません。")
                    return redirect(url_for("make", file=filename))
                df["number"] = num_series.loc[df.index].astype(int)

                start_num = request.form.get("start_num", "")
                end_num = request.form.get("end_num", "")
                try:
                    start_num = int(start_num)
                    end_num = int(end_num)
                except ValueError:
                    flash("開始番号・終了番号は整数で指定してください。")
                    return redirect(url_for("make", file=filename))
                if start_num > end_num:
                    flash("開始番号は終了番号以下にしてください。")
                    return redirect(url_for("make", file=filename))

                df = df[(df["number"] >= start_num) & (df["number"] <= end_num)]
                if df.empty:
                    flash("指定範囲に該当する問題がありません。")
                    return redirect(url_for("make", file=filename))

                title_range_part = f"No.{start_num}–{end_num}"

        except Exception as e:
            flash(f"Excelの読み込みに失敗しました: {e}")
            return redirect(url_for("make"))

        # ===== 共通部分 =====
        n = min(num_questions, len(df))

        if mode == "en-ja":
            question_col, answer_col = "word", "meaning"
            title_base = "英和"
        elif mode == "ja-en":
            question_col, answer_col = "meaning", "word"
            title_base = "和英"
        else:
            flash("不正な出題モードです。")
            return redirect(url_for("make", file=filename))

        if title_range_part:
            title_common = f"{base_name_for_title} / {title_range_part} / {n}問"
        else:
            title_common = f"{base_name_for_title} / {n}問"

        title_q_base = f"{title_base}：問題（{title_common}）"
        title_a_base = f"{title_base}：解答（{title_common}）"

        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

        # ✅ download へ q/a を複数渡す（順番は q,a,q,a,...）
        download_args: list[tuple[str, str]] = []

        try:
            for set_idx in range(1, num_sets + 1):
                sample = df.sample(n=n).reset_index(drop=True)

                uid = uuid.uuid4().hex[:8]
                suffix = f"_v{set_idx}" if num_sets > 1 else ""
                q_name = f"questions_{title_base}_{stamp}{suffix}_{uid}.pdf"
                a_name = f"answers_{title_base}_{stamp}{suffix}_{uid}.pdf"

                if num_sets > 1:
                    title_q = f"{title_q_base} / 第{set_idx}部"
                    title_a = f"{title_a_base} / 第{set_idx}部"
                else:
                    title_q = title_q_base
                    title_a = title_a_base

                q_pdf = build_pdf(
                    sample,
                    styles,
                    with_answers=False,
                    question_col=question_col,
                    answer_col=answer_col,
                    title=title_q,
                ).read()

                a_pdf = build_pdf(
                    sample,
                    styles,
                    with_answers=True,
                    question_col=question_col,
                    answer_col=answer_col,
                    title=title_a,
                ).read()

                if cfg.USE_R2:
                    q_key = f"generated/{q_name}"
                    a_key = f"generated/{a_name}"
                    storage.upload(q_pdf, q_key, "application/pdf")
                    storage.upload(a_pdf, a_key, "application/pdf")
                    download_args.append(("q", q_key))
                    download_args.append(("a", a_key))
                else:
                    q_path = os.path.join(PDF_LOCAL_DIR, q_name)
                    a_path = os.path.join(PDF_LOCAL_DIR, a_name)
                    with open(q_path, "wb") as f:
                        f.write(q_pdf)
                    with open(a_path, "wb") as f:
                        f.write(a_pdf)
                    download_args.append(("q", q_name))
                    download_args.append(("a", a_name))

            if num_sets == 1:
                flash("問題と解答PDFを作成しました！")
            else:
                flash(f"問題と解答PDFを {num_sets} 部作成しました！")

            return redirect(url_for("download") + "?" + urlencode(download_args, doseq=True))

        except Exception as e:
            flash(f"PDFの作成に失敗しました: {e}")
            return redirect(url_for("make"))

    # ===== GET: section 有無だけ判定してテンプレに渡す =====
    selected_file = request.args.get("file", "")
    has_section = False
    sections: list[str] = []

    if selected_file in files:
        try:
            data = storage.open_xlsx_as_bytes(selected_file)
            df_preview = pd.read_excel(io.BytesIO(data), engine="openpyxl")
            if "section" in df_preview.columns:
                has_section = True
                sections = sorted({str(s) for s in df_preview["section"].dropna().unique()})
        except Exception as e:
            flash(f"Excelの読み込みに失敗しました: {e}")

    return render_template(
        "make.html",
        files=files,
        selected_file=selected_file,
        has_section=has_section,
        sections=sections,
        is_auth=bool(getattr(g, "is_auth", False)),
        public_max_sets_per_request=cfg.PUBLIC_MAX_SETS_PER_REQUEST,
        public_max_sets_per_day=cfg.PUBLIC_MAX_SETS_PER_DAY,
        auth_max_sets_per_request=cfg.AUTH_MAX_SETS_PER_REQUEST,
        auth_max_sets_per_day=cfg.AUTH_MAX_SETS_PER_DAY,
        absolute_max_sets_per_request=cfg.ABSOLUTE_MAX_SETS_PER_REQUEST,
        absolute_max_sets_per_day=cfg.ABSOLUTE_MAX_SETS_PER_DAY,
    )


@app.route("/download")
def download():
    qs = request.args.getlist("q")
    ans = request.args.getlist("a")
    print("[/download] qs:", qs, "as:", ans, "USE_R2:", cfg.USE_R2, flush=True)

    if cfg.USE_R2:
        items = []
        try:
            for i, (q, a) in enumerate(zip(qs, ans), start=1):
                q_url = a_url = None
                if q and (q.startswith("generated/") or q.startswith("uploads/")):
                    q_url = storage.presign_get(q, cfg.PRESIGN_EXPIRES)
                if a and (a.startswith("generated/") or a.startswith("uploads/")):
                    a_url = storage.presign_get(a, cfg.PRESIGN_EXPIRES)
                items.append({"idx": i, "q_url": q_url, "a_url": a_url, "q": q, "a": a})
            return render_template("download.html", items=items, use_r2=True)
        except Exception as e:
            app.logger.exception(f"presign_get failed: {e}")
            flash("ダウンロード用URLの生成に失敗しました。時間をおいて再試行してください。")
            return render_template("download.html", items=[], use_r2=True)

    items = []
    for i, (q, a) in enumerate(zip(qs, ans), start=1):
        items.append({"idx": i, "q": q, "a": a})
    return render_template("download.html", items=items, use_r2=False)


# ===== 保存・共有向け：ZIP一括 =====
@app.route("/download_zip")
def download_zip():
    qs = request.args.getlist("q")
    ans = request.args.getlist("a")
    print("[/download_zip] qs:", qs, "as:", ans, "USE_R2:", cfg.USE_R2, flush=True)

    if not qs or not ans:
        flash("ZIPにまとめるファイルが指定されていません。")
        return redirect(url_for("download"))

    pair_count = min(len(qs), len(ans))
    if pair_count <= 0:
        flash("ZIPにまとめるファイルが不足しています。")
        return redirect(url_for("download"))

    zip_buf = io.BytesIO()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    try:
        with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i in range(pair_count):
                q_id = qs[i]
                a_id = ans[i]

                q_bytes = _read_pdf_bytes_from_identifier(q_id)
                a_bytes = _read_pdf_bytes_from_identifier(a_id)

                folder = f"copy_{i+1:02d}"
                zf.writestr(f"{folder}/questions.pdf", q_bytes)
                zf.writestr(f"{folder}/answers.pdf", a_bytes)

        zip_buf.seek(0)
        zip_name = f"tests_bundle_{stamp}_{pair_count}sets.zip"
        return send_file(
            zip_buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=zip_name,
            max_age=0,
        )

    except Exception as e:
        app.logger.exception(f"download_zip failed: {e}")
        flash(f"ZIPの作成に失敗しました: {e}")
        args = [("q", x) for x in qs] + [("a", x) for x in ans]
        return redirect(url_for("download") + "?" + urlencode(args, doseq=True))


# ===== 印刷向け：結合PDF =====
@app.route("/download_merge_questions")
def download_merge_questions():
    qs = request.args.getlist("q")
    print("[/download_merge_questions] qs:", qs, "USE_R2:", cfg.USE_R2, flush=True)

    if not qs:
        flash("結合する問題PDFが指定されていません。")
        return redirect(url_for("download"))

    try:
        pdfs = [_read_pdf_bytes_from_identifier(q) for q in qs]
        merged = _merge_pdf_bytes_in_order(pdfs)

        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"questions_merged_{stamp}_{len(qs)}sets.pdf"
        return send_file(
            io.BytesIO(merged),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )
    except Exception as e:
        app.logger.exception(f"download_merge_questions failed: {e}")
        flash(f"問題PDFの結合に失敗しました: {e}")
        return redirect(url_for("download") + "?" + urlencode([("q", x) for x in qs], doseq=True))


@app.route("/download_merge_answers")
def download_merge_answers():
    ans = request.args.getlist("a")
    print("[/download_merge_answers] as:", ans, "USE_R2:", cfg.USE_R2, flush=True)

    if not ans:
        flash("結合する解答PDFが指定されていません。")
        return redirect(url_for("download"))

    try:
        pdfs = [_read_pdf_bytes_from_identifier(a) for a in ans]
        merged = _merge_pdf_bytes_in_order(pdfs)

        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"answers_merged_{stamp}_{len(ans)}sets.pdf"
        return send_file(
            io.BytesIO(merged),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )
    except Exception as e:
        app.logger.exception(f"download_merge_answers failed: {e}")
        flash(f"解答PDFの結合に失敗しました: {e}")
        return redirect(url_for("download") + "?" + urlencode([("a", x) for x in ans], doseq=True))


@app.route("/download_file/<filename>")
def download_file(filename):
    filename = safe_filename(filename)
    _, ext = os.path.splitext(filename)
    if ext.lower() not in cfg.ALLOWED_DOWNLOAD_EXTENSIONS:
        flash("許可されていないファイル形式です。")
        return redirect(url_for("download"))

    if ext.lower() == ".pdf":
        base_dir = PDF_LOCAL_DIR
    else:
        base_dir = cfg.UPLOAD_FOLDER

    full_path = os.path.join(base_dir, filename)
    if not os.path.isfile(full_path):
        flash("指定されたファイルが存在しません。")
        return redirect(url_for("download"))

    try:
        return send_file(
            full_path,
            as_attachment=True,
            download_name=filename,
            conditional=True,
            max_age=0,
        )
    except Exception as e:
        app.logger.exception(f"send_file failed for {filename}: {e}")
        abort(500)


if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
    )