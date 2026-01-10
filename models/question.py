"""Question data models for different question types."""

from dataclasses import dataclass, field
from typing import Optional, List, Union
from enum import Enum


class QuestionType(Enum):
    """Enumeration of supported question types."""
    VOCABULARY = "vocabulary"
    MULTIPLE_CHOICE = "multiple_choice"
    REORDER = "reorder"

    @classmethod
    def from_sheet_name(cls, sheet_name: str) -> Optional["QuestionType"]:
        """Determine question type from sheet name."""
        name_lower = sheet_name.lower().strip()

        # Vocabulary type mappings
        if name_lower in ("vocabulary", "vocab", "単語"):
            return cls.VOCABULARY

        # Multiple choice type mappings
        if name_lower in ("multiple_choice", "grammar", "4択", "文法"):
            return cls.MULTIPLE_CHOICE

        # Reorder type mappings
        if name_lower in ("reorder", "並べ替え", "整序"):
            return cls.REORDER

        return None

    def get_display_name(self) -> str:
        """Get Japanese display name for the question type."""
        names = {
            QuestionType.VOCABULARY: "単語",
            QuestionType.MULTIPLE_CHOICE: "4択",
            QuestionType.REORDER: "並べ替え",
        }
        return names.get(self, self.value)

    def get_required_columns(self) -> List[str]:
        """Get required column names for this question type."""
        columns = {
            QuestionType.VOCABULARY: ["word", "meaning"],
            QuestionType.MULTIPLE_CHOICE: [
                "question", "choice1", "choice2", "choice3", "choice4", "answer"
            ],
            QuestionType.REORDER: ["prompt", "words", "answer"],
        }
        return columns.get(self, [])

    def get_optional_columns(self) -> List[str]:
        """Get optional column names for this question type."""
        # Common optional columns
        common = ["number", "section", "book", "tag"]

        type_specific = {
            QuestionType.VOCABULARY: [],
            QuestionType.MULTIPLE_CHOICE: ["explanation"],
            QuestionType.REORDER: ["hint", "question_template", "prefix", "suffix"],
        }

        return common + type_specific.get(self, [])


@dataclass
class BaseQuestion:
    """Base class for all question types."""
    type: QuestionType
    number: Optional[int] = None
    section: Optional[str] = None
    book: Optional[str] = None
    tag: Optional[str] = None

    # Internal tracking - row number in original Excel
    _source_row: Optional[int] = field(default=None, repr=False)


@dataclass
class VocabularyQuestion(BaseQuestion):
    """Vocabulary question - word and meaning pair."""
    word: str = ""
    meaning: str = ""

    def __post_init__(self):
        self.type = QuestionType.VOCABULARY

    def get_question_text(self, direction: str = "en-ja") -> str:
        """Get question text based on direction."""
        if direction == "en-ja":
            return self.word
        else:  # ja-en
            return self.meaning

    def get_answer_text(self, direction: str = "en-ja") -> str:
        """Get answer text based on direction."""
        if direction == "en-ja":
            return self.meaning
        else:  # ja-en
            return self.word


@dataclass
class MultipleChoiceQuestion(BaseQuestion):
    """Multiple choice question with 4 options."""
    question: str = ""
    choices: List[str] = field(default_factory=lambda: ["", "", "", ""])
    answer: int = 1  # 1-4
    explanation: Optional[str] = None

    def __post_init__(self):
        self.type = QuestionType.MULTIPLE_CHOICE
        # Ensure choices has exactly 4 items
        if len(self.choices) < 4:
            self.choices.extend([""] * (4 - len(self.choices)))
        elif len(self.choices) > 4:
            self.choices = self.choices[:4]

    def get_correct_choice(self) -> str:
        """Get the correct choice text."""
        if 1 <= self.answer <= 4:
            return self.choices[self.answer - 1]
        return ""

    def get_shuffled_choices(self, seed: int = None) -> tuple:
        """Get shuffled choices and new answer index.

        Returns:
            (shuffled_choices, new_answer_index)
        """
        import random
        if seed is not None:
            random.seed(seed)

        indexed_choices = list(enumerate(self.choices, 1))
        random.shuffle(indexed_choices)

        new_answer = None
        shuffled = []
        for new_idx, (orig_idx, choice) in enumerate(indexed_choices, 1):
            shuffled.append(choice)
            if orig_idx == self.answer:
                new_answer = new_idx

        return shuffled, new_answer


@dataclass
class ReorderQuestion(BaseQuestion):
    """Sentence reordering question."""
    prompt: str = ""  # Japanese instruction/meaning
    words: List[str] = field(default_factory=list)  # Words to arrange
    answer: str = ""  # Correct sentence
    hint: Optional[str] = None  # Optional hint (e.g., first word)
    question_template: Optional[str] = None  # Template with blanks e.g. "After ... (  ) (  ) ..."
    prefix: Optional[str] = None  # Fixed prefix before blanks
    suffix: Optional[str] = None  # Fixed suffix after blanks

    def __post_init__(self):
        self.type = QuestionType.REORDER

    @classmethod
    def parse_words(cls, words_str: str) -> List[str]:
        """Parse words from string (separated by / or ,)."""
        if not words_str:
            return []

        # Try / separator first, then comma
        if "/" in words_str:
            separator = "/"
        else:
            separator = ","

        return [w.strip() for w in words_str.split(separator) if w.strip()]

    def get_shuffled_words(self, seed: int = None) -> List[str]:
        """Get shuffled word list for display."""
        import random
        if seed is not None:
            random.seed(seed)

        shuffled = self.words.copy()
        random.shuffle(shuffled)
        return shuffled

    def get_words_display(self) -> str:
        """Get words as display string with separators."""
        return " / ".join(self.words)

    def get_question_display(self) -> str:
        """Get question text for display.
        
        Returns question_template if available, otherwise generates from prefix/suffix/words.
        """
        if self.question_template:
            return self.question_template
        
        # Generate from prefix/suffix if available
        prefix = self.prefix or ""
        suffix = self.suffix or ""
        
        # Count words to determine number of blanks
        num_blanks = len(self.words)
        blanks = " (    ) " * num_blanks
        
        if prefix and suffix:
            return f"{prefix} {blanks.strip()} {suffix}"
        elif prefix:
            return f"{prefix} {blanks.strip()}"
        elif suffix:
            return f"{blanks.strip()} {suffix}"
        else:
            return blanks.strip()

    def get_full_answer(self) -> str:
        """Get full answer with prefix and suffix.
        
        Returns answer with prefix/suffix if available, otherwise just answer.
        """
        prefix = self.prefix or ""
        suffix = self.suffix or ""
        
        # Handle special case: "(なし)" means no prefix
        if prefix == "(なし)":
            prefix = ""
        
        parts = []
        if prefix:
            parts.append(prefix)
        parts.append(self.answer)
        
        # Join with space, but avoid double spacing
        result = " ".join(parts)
        
        # Add suffix (already included in answer typically, but check)
        # The suffix is usually already part of the answer, so we skip adding it
        # unless the answer doesn't end with it
        if suffix and not result.rstrip().endswith(suffix.rstrip()):
            result = result.rstrip() + " " + suffix
        
        return result.strip()


# Type alias for any question type
Question = Union[VocabularyQuestion, MultipleChoiceQuestion, ReorderQuestion]


def create_question(q_type: QuestionType, **kwargs) -> Question:
    """Factory function to create a question of the specified type."""
    type_classes = {
        QuestionType.VOCABULARY: VocabularyQuestion,
        QuestionType.MULTIPLE_CHOICE: MultipleChoiceQuestion,
        QuestionType.REORDER: ReorderQuestion,
    }

    cls = type_classes.get(q_type)
    if cls is None:
        raise ValueError(f"Unknown question type: {q_type}")

    return cls(**kwargs)