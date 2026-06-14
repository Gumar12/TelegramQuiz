"""Models and local validation for GPT-normalized quiz questions."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

INVISIBLE_CHARS = str.maketrans("", "", "\u200b\u200c\u200d\ufeff\u2060")


ErrorReason = Literal[
    "bad_json",
    "too_long_question",
    "too_long_option",
    "too_long_explanation",
    "duplicate_options",
    "correct_not_in_options",
    "weak_distractors",
    "missing_required_field",
    "gpt_request_failed",
    "max_retries_exceeded",
    "needs_visual_review",
]

ALLOWED_ERROR_REASONS = set(ErrorReason.__args__)


class LocalValidationError(ValueError):
    """Validation failure carrying a stable review error reason."""

    def __init__(self, reason: ErrorReason, message: str):
        super().__init__(message)
        self.reason = reason


def clean_text_value(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(INVISIBLE_CHARS)).strip()


class CleanTextMixin(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def clean_string_values(cls, value: Any) -> Any:
        if isinstance(value, str):
            return clean_text_value(value)
        if isinstance(value, list):
            return [clean_text_value(item) if isinstance(item, str) else item for item in value]
        return value


class RawQuestion(CleanTextMixin):
    id: int
    date: str = ""
    section: str = ""
    context_title: str = ""
    context: str = ""
    media: list[str] = Field(default_factory=list)
    question: str
    correct_answer: str = ""
    correct_answers: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    correct: int | list[int] | None = None
    explanation: str = ""
    explanation_full: str = ""
    type: str = ""
    source: str = ""
    distractors_source: str = ""


class GPTQuestion(CleanTextMixin):
    question: str
    correct_answer: str
    correct_answers: list[str] = Field(default_factory=list)
    options: list[str]
    correct: int | list[int]
    explanation: str
    explanation_full: str
    quality_flags: list[str] = Field(default_factory=list)


class CleanQuestion(GPTQuestion):
    source_item_id: int
    date: str = ""
    section: str = ""
    context_title: str = ""
    context: str = ""
    media: list[str] = Field(default_factory=list)
    type: str = ""
    source: str = "gpt_normalized"

    @field_validator("source")
    @classmethod
    def source_is_known_clean_source(cls, value: str) -> str:
        if value not in {"gpt_normalized", "source_document_bold", "source_document_answer_indexes"}:
            raise ValueError("source must be gpt_normalized, source_document_bold, or source_document_answer_indexes")
        return value


class ReviewQuestion(BaseModel):
    source_item_id: int
    error_reason: ErrorReason
    raw_item: dict[str, Any]
    last_gpt_output: dict[str, Any] | str | None
    attempts: int = Field(ge=0)
    notes: str = ""


def normalize_key(text: str) -> str:
    return clean_text_value(text).casefold()


def _raise(reason: ErrorReason, message: str) -> None:
    raise LocalValidationError(reason, message)


def _correct_indexes(correct: int | list[int], option_count: int) -> list[int]:
    indexes = correct if isinstance(correct, list) else [correct]
    if not indexes:
        _raise("correct_not_in_options", "correct indexes are empty")
    if len(set(indexes)) != len(indexes):
        _raise("correct_not_in_options", "correct indexes are not unique")
    for index in indexes:
        if not (1 <= index <= option_count):
            _raise("correct_not_in_options", f"correct index out of range: {index}")
    return indexes


def validate_clean_question(item: CleanQuestion, *, check_distractor_quality: bool = True) -> None:
    if not (1 <= len(item.question) <= 300):
        _raise("too_long_question", f"question length is {len(item.question)}")

    if len(item.options) != 4:
        _raise("missing_required_field", f"expected 4 options, got {len(item.options)}")

    for option in item.options:
        if not (1 <= len(option) <= 100):
            _raise("too_long_option", f"option length is {len(option)}: {option!r}")

    if len(item.explanation) > 200:
        _raise("too_long_explanation", f"explanation length is {len(item.explanation)}")

    correct_indexes = _correct_indexes(item.correct, len(item.options))

    normalized_options = [normalize_key(option) for option in item.options]
    if len(set(normalized_options)) != len(normalized_options):
        _raise("duplicate_options", "options are not unique after normalization")

    expected_correct_answers = [item.options[index - 1] for index in correct_indexes]
    if len(expected_correct_answers) == 1:
        if item.correct_answer != expected_correct_answers[0]:
            _raise("correct_not_in_options", "correct_answer does not match options[correct - 1]")
        if item.correct_answers and item.correct_answers != expected_correct_answers:
            _raise("correct_not_in_options", "correct_answers does not match correct indexes")
    else:
        if item.correct_answers != expected_correct_answers:
            _raise("correct_not_in_options", "correct_answers does not match correct indexes")
        if item.correct_answer != "; ".join(expected_correct_answers):
            _raise("correct_not_in_options", "correct_answer summary does not match correct_answers")

    correct_keys = {normalize_key(answer) for answer in expected_correct_answers}
    if not check_distractor_quality:
        return

    technical_fallbacks = {
        "вариант 1",
        "вариант 2",
        "вариант 3",
        "вариант 4",
        "другое",
        "нет правильного варианта",
        "option 1",
        "option 2",
        "option 3",
        "option 4",
        "other",
        "none of the above",
    }
    for option in item.options:
        if "..." in option or "…" in option:
            _raise("weak_distractors", f"option contains ellipsis: {option!r}")
        option_key = normalize_key(option)
        if option_key in correct_keys:
            continue
        if option_key in technical_fallbacks:
            _raise("weak_distractors", f"technical fallback option: {option!r}")
        for correct_key in correct_keys:
            if correct_key in option_key or option_key in correct_key:
                _raise("weak_distractors", f"option overlaps with correct answer: {option!r}")


def build_clean_question(raw: RawQuestion, gpt: GPTQuestion) -> CleanQuestion:
    return CleanQuestion(
        source_item_id=raw.id,
        date=raw.date,
        section=raw.section,
        context_title=raw.context_title,
        context=raw.context,
        media=list(raw.media),
        question=gpt.question,
        correct_answer=gpt.correct_answer,
        correct_answers=list(gpt.correct_answers),
        options=list(gpt.options),
        correct=gpt.correct,
        explanation=gpt.explanation,
        explanation_full=gpt.explanation_full,
        type=raw.type,
        source="gpt_normalized",
        quality_flags=list(gpt.quality_flags),
    )
