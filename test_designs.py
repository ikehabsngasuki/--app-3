#!/usr/bin/env python3
"""Test script to generate PDFs with different design styles."""

import io
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Flowable, Table, TableStyle, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from models.question import (
    QuestionType, VocabularyQuestion, MultipleChoiceQuestion, ReorderQuestion
)


# === Font Registration ===
def register_fonts():
    """Register Japanese fonts."""
    fonts_dir = os.path.join(os.path.dirname(__file__), "fonts")
    candidates = [
        "NotoSansJP-Regular.ttf",
        "NotoSansCJKjp-Regular.otf",
        "NotoSansJP-VariableFont_wght.ttf",
    ]
    for fname in candidates:
        p = os.path.join(fonts_dir, fname)
        if os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont("NotoSansJP", p))
                return "NotoSansJP"
            except:
                pass
    return "Helvetica"


# === Sample Data ===
def create_sample_questions():
    """Create sample questions for testing."""
    questions = []

    # Vocabulary questions (1-6)
    vocab_data = [
        ("apple", "りんご"),
        ("banana", "バナナ"),
        ("cherry", "さくらんぼ"),
        ("dolphin", "イルカ"),
        ("elephant", "象"),
        ("flower", "花"),
    ]
    for i, (en, ja) in enumerate(vocab_data, 1):
        q = VocabularyQuestion(type=QuestionType.VOCABULARY, word=en, meaning=ja)
        q.number = i
        questions.append(q)

    # Multiple choice questions (7-9)
    mc_data = [
        ("He ___ to school every day.", ["go", "goes", "going", "went"], 2, "三単現のs"),
        ("The book ___ on the desk.", ["is", "are", "be", "been"], 1, "単数主語"),
        ("I have ___ finished my homework.", ["already", "yet", "still", "ever"], 1, "完了形でalready"),
    ]
    for i, (q_text, choices, ans, exp) in enumerate(mc_data, 7):
        q = MultipleChoiceQuestion(type=QuestionType.MULTIPLE_CHOICE, question=q_text, choices=choices, answer=ans, explanation=exp)
        q.number = i
        questions.append(q)

    # Reorder questions (10-12)
    reorder_data = [
        ("彼は毎日学校に行きます。", ["he", "goes", "to", "school", "every day"], "He goes to school every day.", "He"),
        ("私は昨日本を読みました。", ["I", "read", "a book", "yesterday"], "I read a book yesterday.", "I"),
        ("彼女は美しい花が好きです。", ["she", "likes", "beautiful", "flowers"], "She likes beautiful flowers.", "She"),
    ]
    for i, (prompt, words, answer, hint) in enumerate(reorder_data, 10):
        q = ReorderQuestion(type=QuestionType.REORDER, prompt=prompt, words=words, answer=answer, hint=hint)
        q.number = i
        questions.append(q)

    return questions


# =============================================================================
# 案A: ミニマルライン（罫線ベース）
# =============================================================================

class DesignA_SectionHeader(Flowable):
    """Section header with horizontal lines."""

    def __init__(self, text: str, font_name: str, width: float):
        super().__init__()
        self.text = text
        self.font_name = font_name
        self.width = width
        self.height = 28

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        # Top line
        self.canv.setStrokeColor(colors.HexColor("#333333"))
        self.canv.setLineWidth(1.5)
        self.canv.line(0, self.height - 2, self.width, self.height - 2)

        # Section text
        self.canv.setFillColor(colors.HexColor("#333333"))
        self.canv.setFont(self.font_name, 11)
        self.canv.drawString(4, 8, f"■ {self.text}")


class DesignA_VocabRow(Flowable):
    """Vocabulary row for Design A - minimal line style."""

    def __init__(self, left_q, right_q, font_name: str, width: float, with_answer: bool = False):
        super().__init__()
        self.left_q = left_q
        self.right_q = right_q
        self.font_name = font_name
        self.width = width
        self.with_answer = with_answer
        self.height = 36
        self.col_width = (width - 20) / 2

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 8

        # Left question
        if self.left_q:
            self._draw_vocab_item(0, y, self.left_q)

        # Right question
        if self.right_q:
            self._draw_vocab_item(self.col_width + 20, y, self.right_q)

    def _draw_vocab_item(self, x, y, q):
        # Number and word
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.font_name, 11)
        num_text = f"{q.number}."
        self.canv.drawString(x, y, num_text)

        word = q.get_question_text("en-ja")
        self.canv.drawString(x + 24, y, word)

        # Answer line or answer
        line_x = x + 24
        line_y = y - 18
        line_width = self.col_width - 40

        if self.with_answer:
            self.canv.setFillColor(colors.red)
            self.canv.setFont(self.font_name, 10)
            self.canv.drawString(line_x, line_y + 2, q.get_answer_text("en-ja"))
        else:
            self.canv.setStrokeColor(colors.HexColor("#999999"))
            self.canv.setLineWidth(0.5)
            self.canv.line(line_x, line_y, line_x + line_width, line_y)


class DesignA_MultipleChoice(Flowable):
    """Multiple choice question for Design A."""

    def __init__(self, question, font_name: str, width: float, with_answer: bool = False):
        super().__init__()
        self.question = question
        self.font_name = font_name
        self.width = width
        self.with_answer = with_answer
        self.height = 52

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 4

        # Question number and text
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.font_name, 11)
        self.canv.drawString(0, y - 12, f"{self.question.number}. {self.question.question}")

        # Choices in one row
        y -= 32
        markers = ["①", "②", "③", "④"]
        choice_width = (self.width - 24) / 4

        for i, (marker, choice) in enumerate(zip(markers, self.question.choices)):
            x = 24 + i * choice_width

            if self.with_answer and i + 1 == self.question.answer:
                self.canv.setFillColor(colors.red)
            else:
                self.canv.setFillColor(colors.black)

            self.canv.setFont(self.font_name, 10)
            self.canv.drawString(x, y, f"{marker} {choice}")


class DesignA_Reorder(Flowable):
    """Reorder question for Design A."""

    def __init__(self, question, font_name: str, width: float, with_answer: bool = False):
        super().__init__()
        self.question = question
        self.font_name = font_name
        self.width = width
        self.with_answer = with_answer
        self.height = 64

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 4

        # Question number and prompt
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.font_name, 11)
        self.canv.drawString(0, y - 12, f"{self.question.number}. {self.question.prompt}")

        # Words
        y -= 28
        words_text = f"[ {self.question.get_words_display()} ]"
        self.canv.setFillColor(colors.HexColor("#444444"))
        self.canv.setFont(self.font_name, 10)
        self.canv.drawString(24, y, words_text)

        # Hint if present
        if self.question.hint:
            self.canv.setFillColor(colors.gray)
            self.canv.setFont(self.font_name, 9)
            hint_x = 24 + self.canv.stringWidth(words_text, self.font_name, 10) + 12
            self.canv.drawString(hint_x, y, f"※{self.question.hint}で始める")

        # Answer line or answer
        y -= 20
        if self.with_answer:
            self.canv.setFillColor(colors.red)
            self.canv.setFont(self.font_name, 10)
            self.canv.drawString(24, y, self.question.answer)
        else:
            self.canv.setStrokeColor(colors.HexColor("#999999"))
            self.canv.setLineWidth(0.5)
            self.canv.line(24, y, self.width - 40, y)


def build_design_a_pdf(questions, with_answers=False, title="Design A: ミニマルライン"):
    """Build PDF with Design A style."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)

    font_name = register_fonts()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleJP", fontName=font_name, fontSize=16, leading=20, spaceAfter=12))

    PAGE_WIDTH, _ = A4
    usable_width = PAGE_WIDTH - 60

    story = []

    # Title
    story.append(Paragraph(title, styles["TitleJP"]))
    story.append(Spacer(1, 8))

    # Group by type
    vocab_qs = [q for q in questions if q.type == QuestionType.VOCABULARY]
    mc_qs = [q for q in questions if q.type == QuestionType.MULTIPLE_CHOICE]
    reorder_qs = [q for q in questions if q.type == QuestionType.REORDER]

    # Vocabulary section
    if vocab_qs:
        nums = [q.number for q in vocab_qs]
        story.append(DesignA_SectionHeader(f"単語 ({min(nums)}-{max(nums)})", font_name, usable_width))
        story.append(Spacer(1, 8))

        for i in range(0, len(vocab_qs), 2):
            left = vocab_qs[i]
            right = vocab_qs[i + 1] if i + 1 < len(vocab_qs) else None
            story.append(DesignA_VocabRow(left, right, font_name, usable_width, with_answers))

        story.append(Spacer(1, 16))

    # Multiple choice section
    if mc_qs:
        nums = [q.number for q in mc_qs]
        story.append(DesignA_SectionHeader(f"4択問題 ({min(nums)}-{max(nums)})", font_name, usable_width))
        story.append(Spacer(1, 8))

        for q in mc_qs:
            story.append(DesignA_MultipleChoice(q, font_name, usable_width, with_answers))
            story.append(Spacer(1, 4))

        story.append(Spacer(1, 12))

    # Reorder section
    if reorder_qs:
        nums = [q.number for q in reorder_qs]
        story.append(DesignA_SectionHeader(f"並べ替え ({min(nums)}-{max(nums)})", font_name, usable_width))
        story.append(Spacer(1, 8))

        for q in reorder_qs:
            story.append(DesignA_Reorder(q, font_name, usable_width, with_answers))
            story.append(Spacer(1, 4))

    doc.build(story)
    buffer.seek(0)
    return buffer


# =============================================================================
# 案C: 余白区切り型（装飾なし）
# =============================================================================

class DesignC_SectionHeader(Flowable):
    """Minimal section header with thin line."""

    def __init__(self, text: str, font_name: str, width: float):
        super().__init__()
        self.text = text
        self.font_name = font_name
        self.width = width
        self.height = 24

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        # Section text
        self.canv.setFillColor(colors.HexColor("#555555"))
        self.canv.setFont(self.font_name, 10)
        text_width = self.canv.stringWidth(self.text, self.font_name, 10)
        self.canv.drawString(0, 8, self.text)

        # Thin line after text
        self.canv.setStrokeColor(colors.HexColor("#CCCCCC"))
        self.canv.setLineWidth(0.5)
        self.canv.line(text_width + 12, 12, self.width, 12)


class DesignC_VocabRow(Flowable):
    """Vocabulary row for Design C - whitespace style."""

    def __init__(self, left_q, right_q, font_name: str, width: float, with_answer: bool = False):
        super().__init__()
        self.left_q = left_q
        self.right_q = right_q
        self.font_name = font_name
        self.width = width
        self.with_answer = with_answer
        self.height = 44  # More vertical space
        self.col_width = (width - 40) / 2

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 10

        # Left question
        if self.left_q:
            self._draw_vocab_item(8, y, self.left_q)

        # Right question
        if self.right_q:
            self._draw_vocab_item(self.col_width + 48, y, self.right_q)

    def _draw_vocab_item(self, x, y, q):
        # Number (slightly muted)
        self.canv.setFillColor(colors.HexColor("#666666"))
        self.canv.setFont(self.font_name, 10)
        num_text = f"{q.number}."
        self.canv.drawRightString(x + 20, y, num_text)

        # Word
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.font_name, 12)
        word = q.get_question_text("en-ja")
        self.canv.drawString(x + 28, y, word)

        # Answer line or answer (indented)
        line_x = x + 28
        line_y = y - 22
        line_width = self.col_width - 50

        if self.with_answer:
            self.canv.setFillColor(colors.red)
            self.canv.setFont(self.font_name, 11)
            self.canv.drawString(line_x, line_y + 2, q.get_answer_text("en-ja"))
        else:
            self.canv.setStrokeColor(colors.HexColor("#CCCCCC"))
            self.canv.setLineWidth(0.5)
            self.canv.line(line_x, line_y, line_x + line_width, line_y)


class DesignC_MultipleChoice(Flowable):
    """Multiple choice question for Design C."""

    def __init__(self, question, font_name: str, width: float, with_answer: bool = False):
        super().__init__()
        self.question = question
        self.font_name = font_name
        self.width = width
        self.with_answer = with_answer
        self.height = 64  # More breathing room

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 8

        # Question number (muted, right-aligned)
        self.canv.setFillColor(colors.HexColor("#666666"))
        self.canv.setFont(self.font_name, 10)
        self.canv.drawRightString(28, y - 4, f"{self.question.number}.")

        # Question text
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.font_name, 11)
        self.canv.drawString(36, y - 4, self.question.question)

        # Choices with more spacing
        y -= 36
        markers = ["①", "②", "③", "④"]
        choice_width = (self.width - 60) / 4

        for i, (marker, choice) in enumerate(zip(markers, self.question.choices)):
            x = 36 + i * choice_width

            if self.with_answer and i + 1 == self.question.answer:
                self.canv.setFillColor(colors.red)
            else:
                self.canv.setFillColor(colors.HexColor("#333333"))

            self.canv.setFont(self.font_name, 10)
            self.canv.drawString(x, y, f"{marker} {choice}")


class DesignC_Reorder(Flowable):
    """Reorder question for Design C."""

    def __init__(self, question, font_name: str, width: float, with_answer: bool = False):
        super().__init__()
        self.question = question
        self.font_name = font_name
        self.width = width
        self.with_answer = with_answer
        self.height = 76  # More space

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        y = self.height - 8

        # Question number (muted)
        self.canv.setFillColor(colors.HexColor("#666666"))
        self.canv.setFont(self.font_name, 10)
        self.canv.drawRightString(28, y - 4, f"{self.question.number}.")

        # Prompt
        self.canv.setFillColor(colors.black)
        self.canv.setFont(self.font_name, 11)
        self.canv.drawString(36, y - 4, self.question.prompt)

        # Words (indented more)
        y -= 28
        words_text = f"[ {self.question.get_words_display()} ]"
        self.canv.setFillColor(colors.HexColor("#555555"))
        self.canv.setFont(self.font_name, 10)
        self.canv.drawString(48, y, words_text)

        # Hint
        if self.question.hint:
            self.canv.setFillColor(colors.HexColor("#888888"))
            self.canv.setFont(self.font_name, 9)
            hint_x = 48 + self.canv.stringWidth(words_text, self.font_name, 10) + 16
            self.canv.drawString(hint_x, y, f"※{self.question.hint}で始める")

        # Answer line or answer
        y -= 24
        if self.with_answer:
            self.canv.setFillColor(colors.red)
            self.canv.setFont(self.font_name, 11)
            self.canv.drawString(48, y, self.question.answer)
        else:
            self.canv.setStrokeColor(colors.HexColor("#CCCCCC"))
            self.canv.setLineWidth(0.5)
            self.canv.line(48, y, self.width - 60, y)


def build_design_c_pdf(questions, with_answers=False, title="Design C: 余白区切り型"):
    """Build PDF with Design C style."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)

    font_name = register_fonts()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleJP", fontName=font_name, fontSize=14, leading=18, spaceAfter=16,
                               textColor=colors.HexColor("#333333")))

    PAGE_WIDTH, _ = A4
    usable_width = PAGE_WIDTH - 72

    story = []

    # Title (more subtle)
    story.append(Paragraph(title, styles["TitleJP"]))
    story.append(Spacer(1, 12))

    # Group by type
    vocab_qs = [q for q in questions if q.type == QuestionType.VOCABULARY]
    mc_qs = [q for q in questions if q.type == QuestionType.MULTIPLE_CHOICE]
    reorder_qs = [q for q in questions if q.type == QuestionType.REORDER]

    # Vocabulary section
    if vocab_qs:
        story.append(DesignC_SectionHeader("単語", font_name, usable_width))
        story.append(Spacer(1, 12))

        for i in range(0, len(vocab_qs), 2):
            left = vocab_qs[i]
            right = vocab_qs[i + 1] if i + 1 < len(vocab_qs) else None
            story.append(DesignC_VocabRow(left, right, font_name, usable_width, with_answers))

        story.append(Spacer(1, 24))

    # Multiple choice section
    if mc_qs:
        story.append(DesignC_SectionHeader("4択問題", font_name, usable_width))
        story.append(Spacer(1, 12))

        for q in mc_qs:
            story.append(DesignC_MultipleChoice(q, font_name, usable_width, with_answers))
            story.append(Spacer(1, 8))

        story.append(Spacer(1, 20))

    # Reorder section
    if reorder_qs:
        story.append(DesignC_SectionHeader("並べ替え", font_name, usable_width))
        story.append(Spacer(1, 12))

        for q in reorder_qs:
            story.append(DesignC_Reorder(q, font_name, usable_width, with_answers))
            story.append(Spacer(1, 8))

    doc.build(story)
    buffer.seek(0)
    return buffer


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    questions = create_sample_questions()

    output_dir = "/tmp"

    # Design A - Questions
    pdf_a_q = build_design_a_pdf(questions, with_answers=False)
    with open(os.path.join(output_dir, "design_a_questions.pdf"), "wb") as f:
        f.write(pdf_a_q.read())
    print("Generated: design_a_questions.pdf")

    # Design A - Answers
    pdf_a_a = build_design_a_pdf(questions, with_answers=True, title="Design A: ミニマルライン【解答】")
    with open(os.path.join(output_dir, "design_a_answers.pdf"), "wb") as f:
        f.write(pdf_a_a.read())
    print("Generated: design_a_answers.pdf")

    # Design C - Questions
    pdf_c_q = build_design_c_pdf(questions, with_answers=False)
    with open(os.path.join(output_dir, "design_c_questions.pdf"), "wb") as f:
        f.write(pdf_c_q.read())
    print("Generated: design_c_questions.pdf")

    # Design C - Answers
    pdf_c_a = build_design_c_pdf(questions, with_answers=True, title="Design C: 余白区切り型【解答】")
    with open(os.path.join(output_dir, "design_c_answers.pdf"), "wb") as f:
        f.write(pdf_c_a.read())
    print("Generated: design_c_answers.pdf")

    print("\nAll PDFs generated in /tmp/")
    print("  - design_a_questions.pdf / design_a_answers.pdf")
    print("  - design_c_questions.pdf / design_c_answers.pdf")
