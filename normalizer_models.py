"""Models and local validation for GPT-normalized quiz questions."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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


class RawQuestion(BaseModel):
    id: int
    date: str = ""
    section: str = ""
    context_title: str = ""
    context: str = ""
    media: list[str] = Field(default_factory=list)
    question: str
    correct_answer: str = ""
    options: list[str] = Field(default_factory=list)
    correct: int | None = None
    explanation: str = ""
    explanation_full: str = ""
    type: str = ""
    source: str = ""


class GPTQuestion(BaseModel):
    question: str
    correct_answer: str
    options: list[str]
    correct: int
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
    def source_is_gpt_normalized(cls, value: str) -> str:
        if value != "gpt_normalized":
            raise ValueError("source must be gpt_normalized")
        return value


class ReviewQuestion(BaseModel):
    source_item_id: int
    error_reason: ErrorReason
    raw_item: dict[str, Any]
    last_gpt_output: dict[str, Any] | str | None
    attempts: int = Field(ge=0)
    notes: str = ""


def normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _raise(reason: ErrorReason, message: str) -> None:
    raise LocalValidationError(reason, message)


def validate_clean_question(item: CleanQuestion) -> None:
    if not (1 <= len(item.question) <= 300):
        _raise("too_long_question", f"question length is {len(item.question)}")

    if len(item.options) != 4:
        _raise("missing_required_field", f"expected 4 options, got {len(item.options)}")

    for option in item.options:
        if not (1 <= len(option) <= 100):
            _raise("too_long_option", f"option length is {len(option)}: {option!r}")

    if len(item.explanation) > 200:
        _raise("too_long_explanation", f"explanation length is {len(item.explanation)}")

    if not (1 <= item.correct <= 4):
        _raise("correct_not_in_options", f"correct index out of range: {item.correct}")

    normalized_options = [normalize_key(option) for option in item.options]
    if len(set(normalized_options)) != len(normalized_options):
        _raise("duplicate_options", "options are not unique after normalization")

    correct_option = item.options[item.correct - 1]
    if item.correct_answer != correct_option:
        _raise("correct_not_in_options", "correct_answer does not match options[correct - 1]")

    correct_key = normalize_key(correct_option)
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
        option_key = normalize_key(option)
        if option_key == correct_key:
            continue
        if "..." in option or "…" in option:
            _raise("weak_distractors", f"option contains ellipsis: {option!r}")
        if option_key in technical_fallbacks:
            _raise("weak_distractors", f"technical fallback option: {option!r}")
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
        options=list(gpt.options),
        correct=gpt.correct,
        explanation=gpt.explanation,
        explanation_full=gpt.explanation_full,
        type=raw.type,
        source="gpt_normalized",
        quality_flags=list(gpt.quality_flags),
    )
