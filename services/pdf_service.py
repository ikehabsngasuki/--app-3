# services/pdf_service.py
import io
import os
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Paragraph, Flowable, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def register_fonts(fonts_dir: str):
    font_name = "Helvetica"
    candidates = [
        "NotoSansJP-Regular.ttf",            # ← 最優先に
        "NotoSansCJKjp-Regular.otf",
        "NotoSansJP-VariableFont_wght.ttf",  # 可変は最後（または外してもOK）
        # "NotoSnas.JP-VariablFont_wght.ttf",  # ← タイポなので削除
    ]
    selected = None
    for fname in candidates:
        p = os.path.join(fonts_dir, fname)
        if os.path.exists(p):
            selected = p
            break

    if selected:
        try:
            pdfmetrics.registerFont(TTFont("NotoSansJP", selected))
            font_name = "NotoSansJP"
            print(f"[Font] OK: {selected} を使用（内部名: {font_name}）")
        except Exception as e:
            print(f"[Font] 登録失敗: {selected}: {e}")
            print("[Font] Helvetica にフォールバックします。")
    else:
        print("[Font] 候補フォントなし。Helvetica を使用。")

    return font_name


def build_styles(font_name: str):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Q", parent=styles["Normal"], fontName=font_name, fontSize=13, leading=14))
    styles.add(ParagraphStyle(name="A", parent=styles["Normal"], fontName=font_name, fontSize=10, leading=12, textColor=colors.red))
    return styles

class NumberBox(Flowable):
    def __init__(self, number, width=40, height=40, radius=6, font_name="Helvetica"):
        super().__init__()
        self.number = number
        self.width = width
        self.height = height
        self.radius = radius
        self.font_name = font_name

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(colors.blue)
        self.canv.setLineWidth(0.5)
        self.canv.roundRect(0, 0, self.width, self.height, self.radius, stroke=1, fill=0)

        # ここを修正：スタイルと同じフォントを使う
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.font_name, 10)

        self.canv.drawCentredString(self.width/2, self.height/2 - 4, str(self.number))


class RoundedBox(Flowable):
    def __init__(self, text, styles, width=100, height=40, radius=6, padding=4):
        super().__init__()
        self.text=text; self.styles=styles; self.width=width; self.height=height; self.radius=radius; self.padding=padding
    def wrap(self, aw, ah): return self.width, self.height
    def draw(self):
        self.canv.setStrokeColor(colors.blue); self.canv.setLineWidth(0.5)
        self.canv.roundRect(0,0,self.width,self.height,self.radius, stroke=1, fill=0)
        p = Paragraph(self.text, self.styles["Q"])
        w,h = p.wrap(self.width-2*self.padding, self.height-2*self.padding)
        p.drawOn(self.canv, self.padding, max(0,(self.height-h)/2))

class AnswerBox(Flowable):
    def __init__(self, styles, width=100, height=40, radius=6, answer=None):
        super().__init__()
        self.styles=styles; self.width=width; self.height=height; self.radius=radius; self.answer=answer
    def wrap(self, aw, ah): return self.width, self.height
    def draw(self):
        self.canv.setStrokeColor(colors.blue); self.canv.setLineWidth(0.5)
        self.canv.roundRect(0,0,self.width,self.height,self.radius, stroke=1, fill=0)
        if self.answer:
            p = Paragraph(self.answer, self.styles["A"])
            w,h = p.wrap(self.width-8, self.height-8)
            p.drawOn(self.canv, 4, max(0,(self.height-h)/2))

def build_pdf(df: pd.DataFrame, styles, with_answers=False):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    story = []

    PAGE_WIDTH, PAGE_HEIGHT = A4
    usable_width = PAGE_WIDTH - doc.leftMargin - doc.rightMargin
    gap = 12; num_width = 40; row_h = 40
    remaining_width = usable_width - num_width*2 - gap*5
    q_width = remaining_width * 0.5 / 2
    a_width = remaining_width * 0.5 / 2

    colWidths = [num_width, gap, q_width, gap, a_width, gap, num_width, gap, q_width, gap, a_width]

    # ★ 追加：段落スタイルと同じフォント名を取得
    font_for_boxes = styles["Q"].fontName

    data = []; row = []
    for i, r in df.iterrows():
        try:
            disp_no = int(r["number"])
        except Exception:
            disp_no = r["number"]

        q_text = str(r["word"])
        ans_text = str(r["meaning"]) if with_answers else None

        if i % 2 == 0:
            row.extend([
                # ★ 修正：font_name を渡す
                NumberBox(disp_no, num_width, row_h, font_name=font_for_boxes), "",
                RoundedBox(q_text, styles, q_width, row_h), "",
                AnswerBox(styles, a_width, row_h, answer=ans_text)
            ])
        else:
            row.extend([
                "", NumberBox(disp_no, num_width, row_h, font_name=font_for_boxes), "",
                RoundedBox(q_text, styles, q_width, row_h), "",
                AnswerBox(styles, a_width, row_h, answer=ans_text)
            ])
            data.append(row); row = []

    if row:
        while len(row) < len(colWidths): row.append("")
        data.append(row)

    table = Table(data, colWidths=colWidths, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer
