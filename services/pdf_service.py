# services/pdf_service.py
"""PDF generation service for vocabulary tests and mixed question types."""

import io
import os
from typing import Any, List, Dict, Optional, Tuple
import pandas as pd
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Flowable, Table, TableStyle, Spacer, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Import question models
from models.question import (
    QuestionType, Question, VocabularyQuestion,
    MultipleChoiceQuestion, ReorderQuestion
)


# === Font Registration ===
def register_fonts(fonts_dir: str):
    """Register Japanese fonts for PDF generation."""
    font_name = "Helvetica"
    candidates = [
        "NotoSansJP-Regular.ttf",
        "NotoSansCJKjp-Regular.otf",
        "NotoSansJP-VariableFont_wght.ttf",
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


# === Style Builders ===
def build_styles(font_name: str):
    """Build paragraph styles for PDF generation."""
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="TitleJP", parent=styles["Heading1"],
        fontName=font_name, fontSize=18, leading=22, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="SubTitle", parent=styles["Normal"],
        fontName=font_name, fontSize=10, leading=12, spaceAfter=12,
        textColor=colors.gray,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeader", parent=styles["Heading2"],
        fontName=font_name, fontSize=12, leading=14,
        spaceBefore=16, spaceAfter=8,
        textColor=colors.HexColor("#333333"),
    ))
    styles.add(ParagraphStyle(
        name="Q", parent=styles["Normal"],
        fontName=font_name, fontSize=13, leading=15,
        wordWrap='CJK', splitLongWords=1,
    ))
    styles.add(ParagraphStyle(
        name="QSmall", parent=styles["Normal"],
        fontName=font_name, fontSize=11, leading=13,
        wordWrap='CJK', splitLongWords=1,
    ))
    styles.add(ParagraphStyle(
        name="A", parent=styles["Normal"],
        fontName=font_name, fontSize=10, leading=13, textColor=colors.red,
        wordWrap='CJK', splitLongWords=1,
    ))
    styles.add(ParagraphStyle(
        name="Choice", parent=styles["Normal"],
        fontName=font_name, fontSize=10, leading=12,
        wordWrap='CJK', splitLongWords=1,
    ))
    styles.add(ParagraphStyle(
        name="Hint", parent=styles["Normal"],
        fontName=font_name, fontSize=9, leading=11,
        textColor=colors.gray,
    ))
    return styles


# === Utility Functions ===
def measure_para_height(text: str, style, box_width: float, padding: int = 8, min_h: int = 40) -> int:
    """Measure required height for paragraph text."""
    p = Paragraph(text or "", style)
    _, h = p.wrap(box_width - 2 * padding, 10 ** 6)
    return max(min_h, int(h + 2 * padding))


def cell_to_text(v: Any, *, strip: bool = True, uppercase_bool: bool = False) -> str:
    """Convert DataFrame cell value to display string."""
    if pd.isna(v):
        return ""
    if isinstance(v, bool):
        return ("TRUE" if v else "FALSE") if uppercase_bool else str(v)
    s = str(v)
    return s.strip() if strip else s


# === Flowable Classes ===
class NumberBox(Flowable):
    """Rounded box with a number in the center."""

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
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.font_name, 10)
        self.canv.drawCentredString(self.width / 2, self.height / 2 - 4, str(self.number))


class RoundedBox(Flowable):
    """Rounded box with text content."""

    def __init__(self, text, styles, width=100, height=40, radius=6, padding=4):
        super().__init__()
        self.text = text
        self.styles = styles
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
        p = Paragraph(self.text, self.styles["Q"])
        w, h = p.wrap(self.width - 2 * self.padding, self.height - 2 * self.padding)
        p.drawOn(self.canv, self.padding, max(0, (self.height - h) / 2))


class AnswerBox(Flowable):
    """Rounded box for answer display."""

    def __init__(self, styles, width=100, height=40, radius=6, answer=None):
        super().__init__()
        self.styles = styles
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
            p = Paragraph(self.answer, self.styles["A"])
            w, h = p.wrap(self.width - 8, self.height - 8)
            p.drawOn(self.canv, 4, max(0, (self.height - h) / 2))


class SectionHeaderFlowable(Flowable):
    """Minimal section header with thin line (Design C style)."""

    def __init__(self, text: str, font_name: str = "Helvetica", width: float = 500):
        super().__init__()
        self.text = text
        self.font_name = font_name
        self.width = width
        self.height = 24

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        # Section text (muted color)
        self.canv.setFillColor(colors.HexColor("#555555"))
        self.canv.setFont(self.font_name, 10)
        text_width = self.canv.stringWidth(self.text, self.font_name, 10)
        self.canv.drawString(0, 8, self.text)

        # Thin line after text
        self.canv.setStrokeColor(colors.HexColor("#CCCCCC"))
        self.canv.setLineWidth(0.5)
        self.canv.line(text_width + 12, 12, self.width, 12)


class MultipleChoiceFlowable(Flowable):
    """Multiple choice question with Design C style (whitespace-based)."""

    def __init__(
        self,
        question: MultipleChoiceQuestion,
        styles,
        width: float = 500,
        with_answer: bool = False,
        show_explanation: bool = False,
    ):
        super().__init__()
        self.question = question
        self.styles = styles
        self.width = width
        self.with_answer = with_answer
        self.show_explanation = show_explanation
        self.height = 64  # Generous whitespace

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 8

        # Question number (muted, right-aligned)
        self.canv.setFillColor(colors.HexColor("#666666"))
        self.canv.setFont(self.styles["Q"].fontName, 10)
        self.canv.drawRightString(28, y - 4, f"{self.question.number}.")

        # Question text
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.styles["Q"].fontName, 11)
        self.canv.drawString(36, y - 4, self.question.question)

        # Choices with spacing
        y -= 36
        markers = ["①", "②", "③", "④"]
        choice_width = (self.width - 60) / 4

        for i, (marker, choice) in enumerate(zip(markers, self.question.choices)):
            x = 36 + i * choice_width

            if self.with_answer and i + 1 == self.question.answer:
                self.canv.setFillColor(colors.red)
            else:
                self.canv.setFillColor(colors.HexColor("#333333"))

            self.canv.setFont(self.styles["Choice"].fontName, 10)
            self.canv.drawString(x, y, f"{marker} {choice}")


class ReorderFlowable(Flowable):
    """Reorder question with Design C style (whitespace-based).
    
    Now supports question_template, prefix, suffix for complete question display.
    """

    def __init__(
        self,
        question: ReorderQuestion,
        styles,
        width: float = 500,
        with_answer: bool = False,
    ):
        super().__init__()
        self.question = question
        self.styles = styles
        self.width = width
        self.with_answer = with_answer
        # Increase height if question_template exists (needs more space)
        self.height = 96 if question.question_template else 76

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 8
        font_name = self.styles["Q"].fontName

        # Question number (muted, right-aligned)
        self.canv.setFillColor(colors.HexColor("#666666"))
        self.canv.setFont(font_name, 10)
        self.canv.drawRightString(28, y - 4, f"{self.question.number}.")

        # Prompt (Japanese instruction)
        self.canv.setFillColor(colors.black)
        self.canv.setFont(font_name, 11)
        self.canv.drawString(36, y - 4, self.question.prompt)

        # Question template (if available) - shows the sentence structure with blanks
        if self.question.question_template:
            y -= 22
            question_display = self.question.get_question_display()
            self.canv.setFillColor(colors.HexColor("#333333"))
            self.canv.setFont(font_name, 10)
            self.canv.drawString(48, y, question_display)

        # Words to arrange (indented)
        y -= 24
        words_text = f"[ {self.question.get_words_display()} ]"
        self.canv.setFillColor(colors.HexColor("#555555"))
        self.canv.setFont(self.styles["QSmall"].fontName, 10)
        self.canv.drawString(48, y, words_text)

        # Hint
        if self.question.hint:
            self.canv.setFillColor(colors.HexColor("#888888"))
            self.canv.setFont(self.styles["Hint"].fontName, 9)
            hint_x = 48 + self.canv.stringWidth(words_text, self.styles["QSmall"].fontName, 10) + 16
            self.canv.drawString(hint_x, y, f"※{self.question.hint}で始める")

        # Answer line or answer
        y -= 24
        if self.with_answer:
            # Use get_full_answer() to include prefix/suffix
            full_answer = self.question.get_full_answer()
            self.canv.setFillColor(colors.red)
            self.canv.setFont(font_name, 11)
            self.canv.drawString(48, y, full_answer)
        else:
            self.canv.setStrokeColor(colors.HexColor("#CCCCCC"))
            self.canv.setLineWidth(0.5)
            self.canv.line(48, y, self.width - 60, y)


# === Legacy PDF Builder (for backward compatibility) ===
def build_pdf(
    df: pd.DataFrame,
    styles,
    with_answers: bool = False,
    *,
    question_col: str = "word",
    answer_col: str = "meaning",
    title=None,
):
    """Build PDF from DataFrame (legacy vocabulary format)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    story = []

    if title:
        story.append(Paragraph(title, styles.get("TitleJP", styles["Q"])))
        story.append(Spacer(1, 6))

    PAGE_WIDTH, PAGE_HEIGHT = A4
    usable_width = PAGE_WIDTH - doc.leftMargin - doc.rightMargin
    gap = 12
    num_width = 40
    base_row_h = 40

    remaining_width = usable_width - num_width * 2 - gap * 5
    q_width = remaining_width * 0.5 / 2
    a_width = remaining_width * 0.5 / 2

    colWidths = [num_width, gap, q_width, gap, a_width,
                 gap, num_width, gap, q_width, gap, a_width]

    font_for_boxes = styles["Q"].fontName
    padding = 8

    data = []
    row = []
    pair = []

    for i, r in df.iterrows():
        try:
            disp_no = int(r.get("number", ""))
        except Exception:
            disp_no = r.get("number", "")

        q_text = cell_to_text(r.get(question_col, None))
        ans_text = cell_to_text(r.get(answer_col, None)) if with_answers else ""

        h_q = measure_para_height(q_text, styles["Q"], q_width, padding=padding, min_h=base_row_h)
        h_a = measure_para_height(ans_text, styles["A"], a_width, padding=padding, min_h=base_row_h) if with_answers else base_row_h
        need_h = max(base_row_h, h_q, h_a)

        pair.append((disp_no, q_text, ans_text, need_h))

        if len(pair) == 2 or i == len(df) - 1:
            left = pair[0]
            right = pair[1] if len(pair) == 2 else None
            row_h = max(left[3], right[3] if right else base_row_h)

            row.extend([
                NumberBox(left[0], num_width, row_h, font_name=font_for_boxes), "",
                RoundedBox(left[1], styles, q_width, row_h, padding=padding), "",
                AnswerBox(styles, a_width, row_h, answer=left[2] if with_answers else None)
            ])

            if right:
                row.extend([
                    "", NumberBox(right[0], num_width, row_h, font_name=font_for_boxes), "",
                    RoundedBox(right[1], styles, q_width, row_h, padding=padding), "",
                    AnswerBox(styles, a_width, row_h, answer=right[2] if with_answers else None)
                ])
            else:
                row.extend(["", "", "", "", ""])

            data.append(row)
            row = []
            pair = []

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


# === New Mixed PDF Builder ===
def build_mixed_pdf(
    questions: List[Question],
    styles,
    with_answers: bool = False,
    *,
    title: str = None,
    subtitle: str = None,
    vocab_direction: str = "en-ja",
    show_explanations: bool = True,
) -> io.BytesIO:
    """Build PDF with mixed question types.

    Args:
        questions: List of Question objects (already numbered in order).
        styles: ReportLab styles dictionary.
        with_answers: Whether to show answers.
        title: PDF title.
        subtitle: Subtitle (e.g., date, range info).
        vocab_direction: Direction for vocabulary questions.
        show_explanations: Whether to show explanations for MC questions.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20, rightMargin=20,
        topMargin=20, bottomMargin=20
    )
    story = []

    PAGE_WIDTH, PAGE_HEIGHT = A4
    usable_width = PAGE_WIDTH - doc.leftMargin - doc.rightMargin

    # Title
    if title:
        story.append(Paragraph(title, styles.get("TitleJP", styles["Q"])))
    if subtitle:
        story.append(Paragraph(subtitle, styles.get("SubTitle", styles["Normal"])))
    if title or subtitle:
        story.append(Spacer(1, 12))

    # Group questions by type
    grouped: Dict[QuestionType, List[Question]] = {}
    for q in questions:
        if q.type not in grouped:
            grouped[q.type] = []
        grouped[q.type].append(q)

    # Type order
    type_order = [QuestionType.VOCABULARY, QuestionType.MULTIPLE_CHOICE, QuestionType.REORDER]
    font_name = styles["Q"].fontName

    for q_type in type_order:
        if q_type not in grouped:
            continue

        type_questions = grouped[q_type]
        if not type_questions:
            continue

        # Get number range for section header
        numbers = [q.number for q in type_questions if q.number is not None]
        if numbers:
            range_text = f"({min(numbers)}-{max(numbers)})"
        else:
            range_text = ""

        # Section header
        section_text = f"{q_type.get_display_name()} {range_text}"
        story.append(SectionHeaderFlowable(section_text, font_name, usable_width))
        story.append(Spacer(1, 8))

        if q_type == QuestionType.VOCABULARY:
            # Use existing 2-column layout for vocabulary
            story.extend(_build_vocabulary_section(
                type_questions, styles, usable_width, with_answers, vocab_direction
            ))
        elif q_type == QuestionType.MULTIPLE_CHOICE:
            # Multiple choice layout
            for q in type_questions:
                flowable = MultipleChoiceFlowable(
                    q, styles, usable_width,
                    with_answer=with_answers,
                    show_explanation=show_explanations
                )
                story.append(KeepTogether([flowable, Spacer(1, 8)]))
        elif q_type == QuestionType.REORDER:
            # Reorder layout
            for q in type_questions:
                flowable = ReorderFlowable(
                    q, styles, usable_width,
                    with_answer=with_answers
                )
                story.append(KeepTogether([flowable, Spacer(1, 8)]))

        story.append(Spacer(1, 16))

    doc.build(story)
    buffer.seek(0)
    return buffer


class VocabularyRowFlowable(Flowable):
    """Vocabulary row with Design C style (whitespace-based, 2-column)."""

    def __init__(self, left_q, right_q, styles, width: float, with_answer: bool = False, direction: str = "en-ja"):
        super().__init__()
        self.left_q = left_q
        self.right_q = right_q
        self.styles = styles
        self.width = width
        self.with_answer = with_answer
        self.direction = direction
        self.height = 44  # Generous vertical space
        self.col_width = (width - 40) / 2

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 10
        font_name = self.styles["Q"].fontName

        # Left question
        if self.left_q:
            self._draw_vocab_item(8, y, self.left_q, font_name)

        # Right question
        if self.right_q:
            self._draw_vocab_item(self.col_width + 48, y, self.right_q, font_name)

    def _draw_vocab_item(self, x, y, q, font_name):
        # Number (muted, right-aligned)
        self.canv.setFillColor(colors.HexColor("#666666"))
        self.canv.setFont(font_name, 10)
        num_text = f"{q.number}."
        self.canv.drawRightString(x + 20, y, num_text)

        # Word
        self.canv.setFillColor(colors.black)
        self.canv.setFont(font_name, 12)
        word = q.get_question_text(self.direction)
        self.canv.drawString(x + 28, y, word)

        # Answer line or answer (indented)
        line_x = x + 28
        line_y = y - 22
        line_width = self.col_width - 50

        if self.with_answer:
            self.canv.setFillColor(colors.red)
            self.canv.setFont(font_name, 11)
            self.canv.drawString(line_x, line_y + 2, q.get_answer_text(self.direction))
        else:
            self.canv.setStrokeColor(colors.HexColor("#CCCCCC"))
            self.canv.setLineWidth(0.5)
            self.canv.line(line_x, line_y, line_x + line_width, line_y)


def _build_vocabulary_section(
    questions: List[VocabularyQuestion],
    styles,
    usable_width: float,
    with_answers: bool,
    direction: str = "en-ja",
) -> List:
    """Build vocabulary section with Design C style (whitespace-based, 2-column)."""
    story = []

    for i in range(0, len(questions), 2):
        left = questions[i]
        right = questions[i + 1] if i + 1 < len(questions) else None
        row = VocabularyRowFlowable(left, right, styles, usable_width, with_answers, direction)
        story.append(row)

    return story


def build_answer_sheet_compact(
    questions: List[Question],
    styles,
    *,
    title: str = None,
    vocab_direction: str = "en-ja",
) -> io.BytesIO:
    """Build a compact answer sheet listing all answers.

    Args:
        questions: List of Question objects.
        styles: ReportLab styles dictionary.
        title: PDF title.
        vocab_direction: Direction for vocabulary questions.

    Returns:
        BytesIO buffer containing the PDF.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20, rightMargin=20,
        topMargin=20, bottomMargin=20
    )
    story = []

    # Title
    if title:
        story.append(Paragraph(f"{title}【解答】", styles.get("TitleJP", styles["Q"])))
        story.append(Spacer(1, 12))

    # Group by type
    grouped: Dict[QuestionType, List[Question]] = {}
    for q in questions:
        if q.type not in grouped:
            grouped[q.type] = []
        grouped[q.type].append(q)

    type_order = [QuestionType.VOCABULARY, QuestionType.MULTIPLE_CHOICE, QuestionType.REORDER]

    for q_type in type_order:
        if q_type not in grouped:
            continue

        type_questions = grouped[q_type]
        if not type_questions:
            continue

        # Section header
        story.append(Paragraph(f"━━ {q_type.get_display_name()} 解答 ━━", styles["SectionHeader"]))
        story.append(Spacer(1, 4))

        if q_type == QuestionType.VOCABULARY:
            # Compact format: "1. answer  2. answer  3. answer"
            answers = []
            for q in type_questions:
                num = q.number if q.number else "?"
                ans = q.get_answer_text(vocab_direction)
                answers.append(f"{num}. {ans}")

            # Join with spaces, wrap at reasonable points
            text = "    ".join(answers)
            story.append(Paragraph(text, styles["Choice"]))

        elif q_type == QuestionType.MULTIPLE_CHOICE:
            # Format: "1. ① answer  2. ② answer"
            markers = ["①", "②", "③", "④"]
            answers = []
            for q in type_questions:
                num = q.number if q.number else "?"
                marker = markers[q.answer - 1] if 1 <= q.answer <= 4 else "?"
                answers.append(f"{num}. {marker}")

            text = "    ".join(answers)
            story.append(Paragraph(text, styles["Choice"]))

            # Show explanations if available
            explanations = [(q.number, q.explanation) for q in type_questions if q.explanation]
            if explanations:
                story.append(Spacer(1, 8))
                for num, exp in explanations:
                    story.append(Paragraph(f"{num}. → {exp}", styles["Hint"]))

        elif q_type == QuestionType.REORDER:
            # One answer per line - use get_full_answer() for complete answer
            for q in type_questions:
                num = q.number if q.number else "?"
                full_answer = q.get_full_answer()
                story.append(Paragraph(f"{num}. {full_answer}", styles["Choice"]))

        story.append(Spacer(1, 12))

    doc.build(story)
    buffer.seek(0)
    return buffer