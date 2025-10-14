# app.py
import io
import uuid
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
import os
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

# ===== ユーティリティ =====
def allowed_download(name: str) -> bool:
    _, ext = os.path.splitext(name)
    return ext.lower() in cfg.ALLOWED_DOWNLOAD_EXTENSIONS

def list_xlsx():
    return storage.list_xlsx(prefix="uploads/")

# ===== ルーティング =====
@app.route("/")
def index():
    files = list_xlsx()
    return render_template("index.html", files=files)

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        if "file" not in request.files:
            flash("ファイルが選択されていません。")
            return redirect(url_for("upload"))

        file = request.files["file"]
        if not file or file.filename == "":
            flash("ファイルが選択されていません。")
            return redirect(url_for("upload"))

        filename = safe_filename(file.filename)
        _, ext = os.path.splitext(filename)
        if ext.lower() not in cfg.ALLOWED_UPLOAD_EXTENSIONS:
            flash(".xlsx のみアップロード可です。")
            return redirect(url_for("upload"))

        try:
            key = f"uploads/{filename}"
            storage.upload(file, key, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            flash(f"アップロードに失敗しました: {e}")
            return redirect(url_for("upload"))

        flash("アップロードが完了しました。")
        return redirect(url_for("upload"))

    files = list_xlsx()
    return render_template("upload.html", files=files)

@app.route("/make", methods=["GET", "POST"])
def make():
    files = list_xlsx()

    if request.method == "POST":
        filename = request.form.get("filename", "")
        start_num = request.form.get("start_num", "")
        end_num = request.form.get("end_num", "")
        num_questions = request.form.get("num_questions", "")
        mode = request.form.get("mode", "en-ja")  # 英和/和英

        if filename not in files:
            flash("不正なファイル名です。")
            return redirect(url_for("make"))

        try:
            start_num = int(start_num); end_num = int(end_num); num_questions = int(num_questions)
        except ValueError:
            flash("開始番号・終了番号・出題数は整数で指定してください。")
            return redirect(url_for("make"))

        if start_num > end_num:
            flash("開始番号は終了番号以下にしてください。"); return redirect(url_for("make"))
        if num_questions <= 0:
            flash("出題数は1以上にしてください。"); return redirect(url_for("make"))

        # Excel 読み込み（R2/ローカルどちらでも bytes を経由）
        try:
            xlsx_key = f"uploads/{filename}"
            data = storage.open_xlsx_as_bytes(xlsx_key)
            df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
        except Exception as e:
            flash(f"Excelの読み込みに失敗しました: {e}")
            return redirect(url_for("make"))

        required = {"number", "word", "meaning"}
        missing = required - set(df.columns)
        if missing:
            flash(f"必要な列がありません: {', '.join(sorted(missing))}")
            return redirect(url_for("make"))

        num_series = pd.to_numeric(df["number"], errors="coerce")
        df = df.loc[num_series.notna()].copy()
        if df.empty:
            flash("number 列に有効な数値がありません。"); return redirect(url_for("make"))
        df["number"] = num_series.loc[df.index].astype(int)

        df_range = df[(df["number"] >= start_num) & (df["number"] <= end_num)]
        if df_range.empty:
            flash("指定範囲に該当する問題がありません。"); return redirect(url_for("make"))

        n = min(num_questions, len(df_range))
        sample = df_range.sample(n=n).reset_index(drop=True)

        # 出題モードに応じて列を切替
        if mode == "en-ja":
            question_col, answer_col = "word", "meaning"     # 英→和
            title_base = "英和"
        elif mode == "ja-en":
            question_col, answer_col = "meaning", "word"     # 和→英
            title_base = "和英"
        else:
            flash("不正な出題モードです。"); return redirect(url_for("make"))

        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        q_name = f"questions_{title_base}_{stamp}_{uid}.pdf"
        a_name = f"answers_{title_base}_{stamp}_{uid}.pdf"

        try:
            q_pdf = build_pdf(
                sample, styles,
                with_answers=False,
                question_col=question_col,
                answer_col=answer_col,
                title=f"{title_base}：問題"
            ).read()
            a_pdf = build_pdf(
                sample, styles,
                with_answers=True,
                question_col=question_col,
                answer_col=answer_col,
                title=f"{title_base}：解答"
            ).read()

            if cfg.USE_R2:
                q_key = f"generated/{q_name}"
                a_key = f"generated/{a_name}"
                storage.upload(q_pdf, q_key, "application/pdf")
                storage.upload(a_pdf, a_key, "application/pdf")
                return redirect(url_for("download", q=q_key, a=a_key))
            else:
                # ローカル保存（開発用）
                with open(os.path.join(cfg.UPLOAD_FOLDER, q_name), "wb") as f: f.write(q_pdf)
                with open(os.path.join(cfg.UPLOAD_FOLDER, a_name), "wb") as f: f.write(a_pdf)
                flash("問題と解答PDFを作成しました！")
                return redirect(url_for("download", q=q_name, a=a_name))
        except Exception as e:
            flash(f"PDFの作成に失敗しました: {e}")
            return redirect(url_for("make"))

    return render_template("make.html", files=files)

@app.route("/download")
def download():
    from flask import request
    q = request.args.get("q")
    a = request.args.get("a")
    print("[/download] query:", q, a, "USE_R2:", cfg.USE_R2, flush=True)

    if cfg.USE_R2:
        q_url = a_url = None
        try:
            if q and (q.startswith("generated/") or q.startswith("uploads/")):
                q_url = storage.presign_get(q, cfg.PRESIGN_EXPIRES)
            if a and (a.startswith("generated/") or a.startswith("uploads/")):
                a_url = storage.presign_get(a, cfg.PRESIGN_EXPIRES)
            print("[/download] presigned:", bool(q_url), bool(a_url), flush=True)
            return render_template("download.html", q_url=q_url, a_url=a_url)
        except Exception as e:
            print("[/download] presign ERROR:", repr(e), flush=True)
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
        return send_file(
            full_path,
            as_attachment=True,
            download_name=filename,
            conditional=True,
            max_age=0
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
