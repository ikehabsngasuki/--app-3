"""Question pool management and sampling."""

import random
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

from models.question import QuestionType, Question


@dataclass
class SampleRequest:
    """Request for sampling questions."""
    # Per-type counts (if None, not included in sampling)
    vocabulary_count: Optional[int] = None
    multiple_choice_count: Optional[int] = None
    reorder_count: Optional[int] = None

    # Filters
    sections: Optional[List[str]] = None
    number_range: Optional[Tuple[int, int]] = None

    # For vocabulary
    vocab_direction: str = "en-ja"  # "en-ja" or "ja-en"

    @property
    def total_requested(self) -> int:
        """Total number of questions requested."""
        total = 0
        if self.vocabulary_count:
            total += self.vocabulary_count
        if self.multiple_choice_count:
            total += self.multiple_choice_count
        if self.reorder_count:
            total += self.reorder_count
        return total

    @classmethod
    def for_simple_mode(
        cls,
        pattern: str,
        count: int,
        type_counts: Dict[QuestionType, int],
        vocab_direction: str = "en-ja"
    ) -> "SampleRequest":
        """Create a sample request for simple mode.

        Args:
            pattern: "vocabulary", "multiple_choice", "reorder", or "mixed"
            count: Total number of questions
            type_counts: Available counts per type from ParseResult
            vocab_direction: Direction for vocabulary questions
        """
        request = cls(vocab_direction=vocab_direction)

        if pattern == "vocabulary":
            request.vocabulary_count = count
        elif pattern == "multiple_choice":
            request.multiple_choice_count = count
        elif pattern == "reorder":
            request.reorder_count = count
        elif pattern == "mixed":
            # Distribute evenly across available types
            available_types = [qt for qt, c in type_counts.items() if c > 0]
            if not available_types:
                return request

            base_count = count // len(available_types)
            remainder = count % len(available_types)

            for i, qt in enumerate(available_types):
                type_count = base_count + (1 if i < remainder else 0)
                if qt == QuestionType.VOCABULARY:
                    request.vocabulary_count = type_count
                elif qt == QuestionType.MULTIPLE_CHOICE:
                    request.multiple_choice_count = type_count
                elif qt == QuestionType.REORDER:
                    request.reorder_count = type_count

        return request


class QuestionPool:
    """Manages a pool of questions and provides sampling functionality."""

    def __init__(self, questions: List[Question]):
        """Initialize with a list of questions.

        Args:
            questions: List of Question objects from SheetParser.
        """
        self._questions = questions
        self._by_type: Dict[QuestionType, List[Question]] = {}

        # Index by type
        for q in questions:
            if q.type not in self._by_type:
                self._by_type[q.type] = []
            self._by_type[q.type].append(q)

    def __len__(self) -> int:
        return len(self._questions)

    @property
    def questions(self) -> List[Question]:
        """All questions in the pool."""
        return self._questions.copy()

    def get_by_type(self, q_type: QuestionType) -> List[Question]:
        """Get all questions of a specific type."""
        return self._by_type.get(q_type, []).copy()

    def get_type_counts(self) -> Dict[QuestionType, int]:
        """Get count of questions per type."""
        return {qt: len(qs) for qt, qs in self._by_type.items()}

    def get_sections(self) -> List[str]:
        """Get all unique sections."""
        sections = set()
        for q in self._questions:
            if q.section:
                sections.add(q.section)
        return sorted(sections)

    def filter(
        self,
        types: Optional[List[QuestionType]] = None,
        sections: Optional[List[str]] = None,
        number_range: Optional[Tuple[int, int]] = None,
    ) -> "QuestionPool":
        """Create a new pool with filtered questions.

        Args:
            types: Only include these question types (None = all)
            sections: Only include these sections (None = all)
            number_range: Only include questions in this number range (None = all)

        Returns:
            A new QuestionPool with filtered questions.
        """
        filtered = []

        for q in self._questions:
            # Type filter
            if types is not None and q.type not in types:
                continue

            # Section filter
            if sections is not None:
                if q.section is None or q.section not in sections:
                    continue

            # Number range filter
            if number_range is not None:
                if q.number is None:
                    continue
                start, end = number_range
                if q.number < start or q.number > end:
                    continue

            filtered.append(q)

        return QuestionPool(filtered)

    def sample(
        self,
        request: SampleRequest,
        seed: Optional[int] = None,
    ) -> Tuple[List[Question], Dict[str, str]]:
        """Sample questions according to the request.

        Args:
            request: SampleRequest specifying how many of each type.
            seed: Random seed for reproducibility.

        Returns:
            Tuple of (sampled questions, warnings dict)
        """
        if seed is not None:
            random.seed(seed)

        # Apply filters first
        pool = self
        if request.sections:
            pool = pool.filter(sections=request.sections)
        if request.number_range:
            pool = pool.filter(number_range=request.number_range)

        sampled = []
        warnings = {}

        # Sample each type
        type_requests = [
            (QuestionType.VOCABULARY, request.vocabulary_count),
            (QuestionType.MULTIPLE_CHOICE, request.multiple_choice_count),
            (QuestionType.REORDER, request.reorder_count),
        ]

        for q_type, count in type_requests:
            if count is None or count <= 0:
                continue

            available = pool.get_by_type(q_type)

            if len(available) < count:
                warnings[q_type.value] = (
                    f"{q_type.get_display_name()}: "
                    f"要求 {count}問 / 利用可能 {len(available)}問"
                )
                # Use all available
                sampled.extend(available)
            else:
                # Random sample
                sampled.extend(random.sample(available, count))

        return sampled, warnings

    def sample_balanced(
        self,
        total: int,
        seed: Optional[int] = None,
    ) -> Tuple[List[Question], Dict[str, str]]:
        """Sample questions balanced across all types.

        Args:
            total: Total number of questions to sample.
            seed: Random seed for reproducibility.

        Returns:
            Tuple of (sampled questions, warnings dict)
        """
        type_counts = self.get_type_counts()
        request = SampleRequest.for_simple_mode("mixed", total, type_counts)
        return self.sample(request, seed)


def assign_numbers(questions: List[Question]) -> List[Question]:
    """Assign sequential numbers to questions.

    Questions are ordered by type (vocabulary, multiple_choice, reorder)
    and then assigned sequential numbers starting from 1.

    Args:
        questions: List of questions to number.

    Returns:
        New list with assigned numbers (original list not modified).
    """
    # Group by type
    by_type: Dict[QuestionType, List[Question]] = {}
    for q in questions:
        if q.type not in by_type:
            by_type[q.type] = []
        by_type[q.type].append(q)

    # Order: vocabulary, multiple_choice, reorder
    type_order = [
        QuestionType.VOCABULARY,
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.REORDER,
    ]

    numbered = []
    current_number = 1

    for q_type in type_order:
        if q_type not in by_type:
            continue

        for q in by_type[q_type]:
            # Create a copy with the new number
            # Since dataclasses are mutable, we'll update in place
            # but track the assignment
            q.number = current_number
            numbered.append(q)
            current_number += 1

    return numbered


def get_type_ranges(questions: List[Question]) -> Dict[QuestionType, Tuple[int, int]]:
    """Get the number range for each question type.

    Args:
        questions: List of numbered questions.

    Returns:
        Dict mapping type to (start, end) number range.
    """
    ranges: Dict[QuestionType, Tuple[int, int]] = {}

    for q in questions:
        if q.number is None:
            continue

        if q.type not in ranges:
            ranges[q.type] = (q.number, q.number)
        else:
            start, end = ranges[q.type]
            ranges[q.type] = (min(start, q.number), max(end, q.number))

    return ranges
