"""Excel sheet parser for extracting questions from different sheet types."""

import io
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import pandas as pd

from models.question import (
    QuestionType,
    Question,
    VocabularyQuestion,
    MultipleChoiceQuestion,
    ReorderQuestion,
)


@dataclass
class ParseResult:
    """Result of parsing an Excel file."""
    questions: List[Question] = field(default_factory=list)
    type_counts: Dict[QuestionType, int] = field(default_factory=dict)
    sections: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        """Total number of questions."""
        return len(self.questions)

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0

    @property
    def available_types(self) -> List[QuestionType]:
        """List of question types that have at least one question."""
        return [qt for qt, count in self.type_counts.items() if count > 0]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": not self.has_errors,
            "types": [
                {
                    "id": qt.value,
                    "name": qt.get_display_name(),
                    "count": count,
                }
                for qt, count in self.type_counts.items()
            ],
            "sections": self.sections,
            "total": self.total_count,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class SheetParser:
    """Parser for Excel files containing questions."""

    # Column name aliases for flexibility
    COLUMN_ALIASES = {
        # Vocabulary
        "word": ["word", "english", "英語", "単語"],
        "meaning": ["meaning", "japanese", "日本語", "意味"],
        # Multiple choice
        "question": ["question", "問題", "問題文"],
        "choice1": ["choice1", "選択肢1", "1"],
        "choice2": ["choice2", "選択肢2", "2"],
        "choice3": ["choice3", "選択肢3", "3"],
        "choice4": ["choice4", "選択肢4", "4"],
        "answer": ["answer", "正解", "解答"],
        "explanation": ["explanation", "解説", "説明"],
        # Reorder
        "prompt": ["prompt", "指示", "日本語", "問題"],
        "words": ["words", "語句", "並べ替え"],
        "hint": ["hint", "ヒント"],
        "question_template": ["question_template", "問題テンプレート", "テンプレート"],
        "prefix": ["prefix", "冒頭", "前置き"],
        "suffix": ["suffix", "末尾", "後置き"],
        # Common
        "number": ["number", "no", "番号", "#"],
        "section": ["section", "セクション", "単元", "lesson", "レッスン"],
        "book": ["book", "教材", "テキスト"],
        "tag": ["tag", "タグ", "分類"],
    }

    def parse(self, file_bytes: bytes) -> ParseResult:
        """Parse an Excel file and extract all questions.

        Args:
            file_bytes: Raw bytes of the Excel file.

        Returns:
            ParseResult containing all extracted questions and metadata.
        """
        result = ParseResult()

        try:
            # Load Excel file
            excel_file = pd.ExcelFile(io.BytesIO(file_bytes))
            sheet_names = excel_file.sheet_names

            if not sheet_names:
                result.errors.append("Excelファイルにシートがありません")
                return result

            # Track found types
            found_any_valid_sheet = False

            for sheet_name in sheet_names:
                # Try to determine question type from sheet name
                q_type = QuestionType.from_sheet_name(sheet_name)

                # Read the sheet
                try:
                    df = pd.read_excel(excel_file, sheet_name=sheet_name)
                except Exception as e:
                    result.warnings.append(f"シート「{sheet_name}」の読み込みに失敗: {str(e)}")
                    continue

                if df.empty:
                    result.warnings.append(f"シート「{sheet_name}」は空です")
                    continue

                # Normalize column names
                df = self._normalize_columns(df)

                # If type not determined by name, try to detect from columns
                if q_type is None:
                    q_type = self._detect_type_from_columns(df)

                if q_type is None:
                    result.warnings.append(
                        f"シート「{sheet_name}」の問題タイプを判定できません"
                    )
                    continue

                # Validate required columns
                validation_errors = self._validate_columns(df, q_type, sheet_name)
                if validation_errors:
                    result.errors.extend(validation_errors)
                    continue

                # Parse questions from this sheet
                questions, parse_warnings = self._parse_sheet(df, q_type, sheet_name)
                result.questions.extend(questions)
                result.warnings.extend(parse_warnings)

                # Update type counts
                if q_type not in result.type_counts:
                    result.type_counts[q_type] = 0
                result.type_counts[q_type] += len(questions)

                found_any_valid_sheet = True

            if not found_any_valid_sheet and not result.errors:
                result.errors.append(
                    "有効な問題シートが見つかりません。"
                    "シート名を「vocabulary」「grammar」「reorder」などに変更するか、"
                    "word/meaning列を含むシートを用意してください。"
                )

            # Extract unique sections
            result.sections = self._extract_sections(result.questions)

        except Exception as e:
            result.errors.append(f"Excelファイルの解析に失敗しました: {str(e)}")

        return result

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names to standard names."""
        column_mapping = {}

        for col in df.columns:
            col_lower = str(col).lower().strip()

            for standard_name, aliases in self.COLUMN_ALIASES.items():
                if col_lower in [a.lower() for a in aliases]:
                    column_mapping[col] = standard_name
                    break

        if column_mapping:
            df = df.rename(columns=column_mapping)

        return df

    def _detect_type_from_columns(self, df: pd.DataFrame) -> Optional[QuestionType]:
        """Detect question type from column names."""
        columns = set(df.columns.str.lower())

        # Check for vocabulary (word + meaning)
        if "word" in columns and "meaning" in columns:
            return QuestionType.VOCABULARY

        # Check for multiple choice
        mc_required = {"question", "choice1", "choice2", "choice3", "choice4", "answer"}
        if mc_required.issubset(columns):
            return QuestionType.MULTIPLE_CHOICE

        # Check for reorder
        if "prompt" in columns and "words" in columns and "answer" in columns:
            return QuestionType.REORDER

        return None

    def _validate_columns(
        self, df: pd.DataFrame, q_type: QuestionType, sheet_name: str
    ) -> List[str]:
        """Validate that required columns exist."""
        errors = []
        required = q_type.get_required_columns()
        existing = set(df.columns.str.lower())

        missing = [col for col in required if col.lower() not in existing]
        if missing:
            errors.append(
                f"シート「{sheet_name}」に必須カラムがありません: {', '.join(missing)}"
            )

        return errors

    def _parse_sheet(
        self, df: pd.DataFrame, q_type: QuestionType, sheet_name: str
    ) -> Tuple[List[Question], List[str]]:
        """Parse questions from a single sheet."""
        questions = []
        warnings = []

        for idx, row in df.iterrows():
            row_num = idx + 2  # Excel row number (1-indexed, plus header)

            try:
                question = self._parse_row(row, q_type, row_num)
                if question:
                    questions.append(question)
            except Exception as e:
                warnings.append(f"シート「{sheet_name}」{row_num}行目: {str(e)}")

        return questions, warnings

    def _parse_row(
        self, row: pd.Series, q_type: QuestionType, row_num: int
    ) -> Optional[Question]:
        """Parse a single row into a Question object."""

        # Helper to safely get value
        def get_val(key: str, default=None):
            if key in row.index:
                val = row[key]
                if pd.isna(val):
                    return default
                return val
            return default

        def get_str(key: str, default: str = "") -> str:
            val = get_val(key, default)
            return str(val).strip() if val else default

        def get_int(key: str, default: Optional[int] = None) -> Optional[int]:
            val = get_val(key)
            if val is None:
                return default
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return default

        # Common fields
        number = get_int("number")
        section = get_str("section") or None
        book = get_str("book") or None
        tag = get_str("tag") or None

        if q_type == QuestionType.VOCABULARY:
            word = get_str("word")
            meaning = get_str("meaning")

            if not word and not meaning:
                return None  # Skip empty rows

            if not word or not meaning:
                raise ValueError("word と meaning の両方が必要です")

            return VocabularyQuestion(
                type=q_type,
                number=number,
                section=section,
                book=book,
                tag=tag,
                word=word,
                meaning=meaning,
                _source_row=row_num,
            )

        elif q_type == QuestionType.MULTIPLE_CHOICE:
            question = get_str("question")
            choices = [
                get_str("choice1"),
                get_str("choice2"),
                get_str("choice3"),
                get_str("choice4"),
            ]
            answer_raw = get_val("answer")
            explanation = get_str("explanation") or None

            if not question and not any(choices):
                return None  # Skip empty rows

            if not question:
                raise ValueError("question が必要です")

            # Parse answer
            answer = self._parse_mc_answer(answer_raw, choices)

            return MultipleChoiceQuestion(
                type=q_type,
                number=number,
                section=section,
                book=book,
                tag=tag,
                question=question,
                choices=choices,
                answer=answer,
                explanation=explanation,
                _source_row=row_num,
            )

        elif q_type == QuestionType.REORDER:
            prompt = get_str("prompt")
            words_str = get_str("words")
            answer = get_str("answer")
            hint = get_str("hint") or None
            question_template = get_str("question_template") or None
            prefix = get_str("prefix") or None
            suffix = get_str("suffix") or None

            if not prompt and not words_str:
                return None  # Skip empty rows

            if not prompt or not words_str or not answer:
                raise ValueError("prompt, words, answer のすべてが必要です")

            words = ReorderQuestion.parse_words(words_str)

            return ReorderQuestion(
                type=q_type,
                number=number,
                section=section,
                book=book,
                tag=tag,
                prompt=prompt,
                words=words,
                answer=answer,
                hint=hint,
                question_template=question_template,
                prefix=prefix,
                suffix=suffix,
                _source_row=row_num,
            )

        return None

    def _parse_mc_answer(self, answer_raw, choices: List[str]) -> int:
        """Parse multiple choice answer to index (1-4)."""
        if answer_raw is None:
            raise ValueError("answer が必要です")

        # Try as integer first
        try:
            answer_int = int(float(answer_raw))
            if 1 <= answer_int <= 4:
                return answer_int
        except (ValueError, TypeError):
            pass

        # Try as text matching
        answer_str = str(answer_raw).strip().lower()
        for i, choice in enumerate(choices, 1):
            if choice.lower().strip() == answer_str:
                return i

        raise ValueError(f"answer は 1-4 の数値か選択肢のテキストで指定してください: {answer_raw}")

    def _extract_sections(self, questions: List[Question]) -> List[str]:
        """Extract unique section names from questions."""
        sections = set()
        for q in questions:
            if q.section:
                sections.add(q.section)
        return sorted(sections)


# Singleton instance for convenience
_parser = SheetParser()


def parse_excel(file_bytes: bytes) -> ParseResult:
    """Parse an Excel file and return questions.

    This is a convenience function wrapping SheetParser.parse().
    """
    return _parser.parse(file_bytes)