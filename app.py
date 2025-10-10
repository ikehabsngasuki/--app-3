import os
import io
import uuid
import datetime as dt

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_from_directory
)
from werkzeug.utils import secure_filename

import pandas as pd

from reportlab.platypus import SimpleDocTemplate, Paragraph, Flowable, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import re

def safe_filename(name: str) -> str:
    """
    日本語など非ASCIIは保持しつつ、危険な文字とパス要素だけ除去する。
    """
    # パストラバーサル無効化（../ や / を除去）
    name = os.path.basename(name)
    # ヌルバイト除去
    name = name.replace("\x00", "")
    # Windows等で問題になりやすい記号をアンダースコアに
    # （例）\ / : * ? " < > | を _
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    # 前後の空白除去
    return name.strip()


# ======================
# 基本設定
# ======================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)  # ← 念のため作成

ALLOWED_UPLOAD_EXTENSIONS = {".xlsx"}
ALLOWED_DOWNLOAD_EXTENSIONS = {".pdf", ".xlsx"}

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-me")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

# ======================
# フォント（手元の VariableFont を最優先。無ければ既存候補 → Helvetica）
# ======================
FONT_NAME = "Helvetica"
CANDIDATE_FILES = [
    "NotoSnas.JP-VariablFont_wght.ttf",   # ← そのまま最優先（手元のファイル名）
    "NotoSansJP-VariableFont_wght.ttf",
    "NotoSansCJKjp-Regular.otf",
    "NotoSansJP-Regular.ttf",
]

selected_path = None
for fname in CANDIDATE_FILES:
    p = os.path.join(FONTS_DIR, fname)
    if os.path.exists(p):
        selected_path = p
        break

if selected_path:
    try:
        pdfmetrics.registerFont(TTFont("NotoSansJP", selected_path))
        FONT_NAME = "NotoSansJP"
        print(f"[Font] OK: {selected_path} を使用します（内部名: {FONT_NAME}）")
    except Exception as e:
        print(f"[Font] 登録失敗: {selected_path}: {e}")
        print("[Font] Helvetica にフォールバックします。")
else:
    print("[Font] 候補フォントが見つかりませんでした。Helvetica を使用します。")

print(f"[Font] 使用フォント: {FONT_NAME}")

# スタイル
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="Q", parent=styles["Normal"],
    fontName=FONT_NAME, fontSize=13, leading=14
))
styles.add(ParagraphStyle(
    name="A", parent=styles["Normal"],
    fontName=FONT_NAME, fontSize=10, leading=12, textColor=colors.red
))

# ======================
# Flowable（wrap実装で安定させる）
# ======================
class NumberBox(Flowable):
    def __init__(self, number, width=40, height=40, radius=6):
        super().__init__()
        self.number = number
        self.width = width
        self.height = height
        self.radius = radius

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(colors.blue)
        self.canv.setLineWidth(0.5)
        self.canv.roundRect(0, 0, self.width, self.height, self.radius, stroke=1, fill=0)
        self.canv.setFont(FONT_NAME, 10)
        self.canv.drawCentredString(self.width/2, self.height/2 - 4, str(self.number))


class RoundedBox(Flowable):
    def __init__(self, text, width=100, height=40, radius=6, padding=4):
        super().__init__()
        self.text = text
        self.width = width
        self.height = height
        self.radius = radius
        self.padding = padding

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(colors.blue)
        self.canv.setLineWidth(0.5)
        self.canv.roundRect(0, 0, self.width, self.height, self.radius, stroke=1, fill=0)
        p = Paragraph(self.text, styles["Q"])
        w, h = p.wrap(self.width - 2*self.padding, self.height - 2*self.padding)
        p.drawOn(self.canv, self.padding, max(0, (self.height - h)/2))


class AnswerBox(Flowable):
    def __init__(self, width=100, height=40, radius=6, answer=None):
        super().__init__()
        self.width = width
        self.height = height
        self.radius = radius
        self.answer = answer

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(colors.blue)
        self.canv.setLineWidth(0.5)
        self.canv.roundRect(0, 0, self.width, self.height, self.radius, stroke=1, fill=0)
        if self.answer:
            p = Paragraph(self.answer, styles["A"])
            w, h = p.wrap(self.width - 8, self.height - 8)
            p.drawOn(self.canv, 4, max(0, (self.height - h)/2))

# ======================
# PDF 生成（★番号は Excel の number をそのまま表示）
# ======================
def build_pdf(df, with_answers=False):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20
    )
    story = []

    PAGE_WIDTH, PAGE_HEIGHT = A4
    usable_width = PAGE_WIDTH - doc.leftMargin - doc.rightMargin
    gap = 12
    num_width = 40
    row_h = 40

    # 左右2セット（番号/問題/解答）
    remaining_width = usable_width - num_width*2 - gap*5
    q_width = remaining_width * 0.5 / 2
    a_width = remaining_width * 0.5 / 2

    colWidths = [
        num_width, gap, q_width, gap, a_width,
        gap, num_width, gap, q_width, gap, a_width
    ]

    data = []
    row = []

    for i, r in df.iterrows():
        # 表示番号は Excel の number 列を使用
        try:
            disp_no = int(r["number"])
        except Exception:
            disp_no = r["number"]

        q_text = str(r["word"])
        ans_text = str(r["meaning"]) if with_answers else None

        if i % 2 == 0:
            row.extend([
                NumberBox(disp_no, width=num_width, height=row_h), "",
                RoundedBox(q_text, width=q_width, height=row_h), "",
                AnswerBox(width=a_width, height=row_h, answer=ans_text)
            ])
        else:
            row.extend([
                "", NumberBox(disp_no, width=num_width, height=row_h), "",
                RoundedBox(q_text, width=q_width, height=row_h), "",
                AnswerBox(width=a_width, height=row_h, answer=ans_text)
            ])
            data.append(row)
            row = []

    if row:  # 奇数件の埋め草
        while len(row) < len(colWidths):
            row.append("")
        data.append(row)

    table = Table(data, colWidths=colWidths, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer

# ======================
# ユーティリティ
# ======================
def list_xlsx():
    files = []
    for f in os.listdir(app.config["UPLOAD_FOLDER"]):
        full = os.path.join(app.config["UPLOAD_FOLDER"], f)
        if os.path.isfile(full) and os.path.splitext(f)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS:
            files.append(f)
    files.sort(key=lambda x: os.path.getctime(os.path.join(app.config["UPLOAD_FOLDER"], x)), reverse=True)
    return files

def allowed_download(name: str) -> bool:
    _, ext = os.path.splitext(name)
    return ext.lower() in ALLOWED_DOWNLOAD_EXTENSIONS

# ======================
# ルーティング
# ======================
@app.route("/")
def index():
    return render_template("index.html")

# アップロード
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
        if ext.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
            flash(".xlsx のみアップロード可です。")
            return redirect(url_for("upload"))

        try:
            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)
        except Exception as e:
            flash(f"アップロードに失敗しました: {e}")
            return redirect(url_for("upload"))

        flash("アップロードが完了しました。")
        return redirect(url_for("upload"))

    files = list_xlsx()
    return render_template("upload.html", files=files)

# 問題作成
@app.route("/make", methods=["GET", "POST"])
def make():
    files = list_xlsx()

    if request.method == "POST":
        filename = request.form.get("filename", "")
        start_num = request.form.get("start_num", "")
        end_num = request.form.get("end_num", "")
        num_questions = request.form.get("num_questions", "")

        if filename not in files:
            flash("不正なファイル名です。")
            return redirect(url_for("make"))

        # 整数チェック
        try:
            start_num = int(start_num)
            end_num = int(end_num)
            num_questions = int(num_questions)
        except ValueError:
            flash("開始番号・終了番号・出題数は整数で指定してください。")
            return redirect(url_for("make"))

        if start_num > end_num:
            flash("開始番号は終了番号以下にしてください。")
            return redirect(url_for("make"))
        if num_questions <= 0:
            flash("出題数は1以上にしてください。")
            return redirect(url_for("make"))

        # Excel読み込み & 必須列チェック
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        try:
            df = pd.read_excel(path, engine="openpyxl")
        except Exception as e:
            flash(f"Excelの読み込みに失敗しました: {e}")
            return redirect(url_for("make"))

        required = {"number", "word", "meaning"}
        missing = required - set(df.columns)
        if missing:
            flash(f"必要な列がありません: {', '.join(sorted(missing))}")
            return redirect(url_for("make"))

        # number 正規化
        num_series = pd.to_numeric(df["number"], errors="coerce")
        df = df.loc[num_series.notna()].copy()
        if df.empty:
            flash("number 列に有効な数値がありません。")
            return redirect(url_for("make"))
        df["number"] = num_series.loc[df.index].astype(int)

        # 範囲抽出
        df_range = df[(df["number"] >= start_num) & (df["number"] <= end_num)]
        if df_range.empty:
            flash("指定範囲に該当する問題がありません。")
            return redirect(url_for("make"))

        # 毎回ランダム抽出
        n = min(num_questions, len(df_range))
        sample = df_range.sample(n=n).reset_index(drop=True)

        # PDF生成（ユニーク名）
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        q_name = f"questions_{stamp}_{uid}.pdf"
        a_name = f"answers_{stamp}_{uid}.pdf"

        try:
            with open(os.path.join(app.config["UPLOAD_FOLDER"], q_name), "wb") as f:
                f.write(build_pdf(sample, with_answers=False).read())
            with open(os.path.join(app.config["UPLOAD_FOLDER"], a_name), "wb") as f:
                f.write(build_pdf(sample, with_answers=True).read())
        except Exception as e:
            flash(f"PDFの作成に失敗しました: {e}")
            return redirect(url_for("make"))

        flash("問題と解答PDFを作成しました！")
        return redirect(url_for("download", q=q_name, a=a_name))

    return render_template("make.html", files=files)

from flask import abort, send_file

@app.route("/download")
def download():
    q = request.args.get("q")
    a = request.args.get("a")
    return render_template("download.html", q=q, a=a)


@app.route("/download_file/<filename>")
def download_file(filename):
    # ファイル名の正規化（パストラバーサル無効化）
    filename = safe_filename(filename)
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_DOWNLOAD_EXTENSIONS:
        flash("許可されていないファイル形式です。")
        return redirect(url_for("download"))

    full_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.isfile(full_path):
        flash("指定されたファイルが存在しません。")
        return redirect(url_for("download"))

    try:
        # 直接パスを指定して送信（条件付き送信で安定・効率化）
        return send_file(
            full_path,
            as_attachment=True,
            download_name=filename,
            conditional=True,   # Range/If-Modified などを処理
            max_age=0           # キャッシュしない
        )
    except Exception as e:
        app.logger.exception(f"send_file failed for {filename}: {e}")
        # この時は 500 を返して Render のログにトレースが残ります
        abort(500)

if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
    )
