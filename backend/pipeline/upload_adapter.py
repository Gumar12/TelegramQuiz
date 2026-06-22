"""Adapt human-editable clean quiz JSON to legacy upload questions."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.models import Question
from backend.pipeline.encoding import normalize_text


@dataclass(slots=True)
class LegacyQuiz:
    title: str
    questions: list[Question]
    raw_questions: list[dict[str, Any]]
    skipped_source_question_indexes: list[int] = field(default_factory=list)
    source_question_count: int = 0
    settings: dict[str, Any] = field(default_factory=dict)

    def to_legacy_json(self) -> dict[str, Any]:
        return {
            "quiz_title": self.title,
            "format_version": "2.1-clean-adapter",
            "settings": dict(self.settings),
            "source_question_count": self.source_question_count,
            "skipped_source_question_indexes": list(self.skipped_source_question_indexes),
            "questions": [dict(item) for item in self.raw_questions],
        }


def load_clean_quiz(path: str | Path) -> dict[str, Any]:
    clean_path = Path(path)
    try:
        data = json.loads(clean_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid clean quiz JSON in {clean_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Clean quiz JSON must be a top-level object")
    return data


def clean_quiz_to_legacy_questions(
    clean_json: Mapping[str, Any],
    *,
    start_from: int = 1,
    selected_indexes: Iterable[int] | None = None,
) -> LegacyQuiz:
    if start_from < 1:
        raise ValueError("start_from must be >= 1")

    title = _string(clean_json.get("title"), default="Новый квиз")
    settings = clean_json.get("settings")
    clean_items = clean_json.get("items")
    if not isinstance(clean_items, list):
        raise ValueError("Clean quiz JSON must contain items list")

    selected = set(selected_indexes) if selected_indexes is not None else None
    if selected is not None and any(index < 1 for index in selected):
        raise ValueError("selected_indexes must contain 1-based question indexes")

    active_context_text = ""
    active_context_media: list[str] = []
    questions: list[Question] = []
    raw_questions: list[dict[str, Any]] = []
    source_question_index = 0

    for clean_item_index, item in enumerate(clean_items, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"Clean item #{clean_item_index} must be an object")

        item_type = item.get("type")
        if item_type == "title":
            active_context_text = ""
            active_context_media = []
            continue
        if item_type == "reset_context":
            active_context_text = ""
            active_context_media = []
            continue
        if item_type == "context":
            active_context_text = _string(item.get("text"), default="")
            active_context_media = _media_list(item.get("media"))
            continue
        if item_type != "question":
            raise ValueError(f"Unsupported clean item type at #{clean_item_index}: {item_type!r}")

        source_question_index += 1
        if source_question_index < start_from:
            continue
        if selected is not None and source_question_index not in selected:
            continue

        raw_question = _question_to_raw(
            item,
            source_question_index=source_question_index,
            clean_item_index=clean_item_index,
            context=active_context_text,
            media=active_context_media,
        )
        raw_questions.append(raw_question)
        questions.append(
            Question(
                question=raw_question["question"],
                options=raw_question["options"],
                correct=raw_question["correct"],
                explanation=raw_question.get("explanation", ""),
                context=raw_question.get("context", ""),
                media=raw_question.get("media", []),
            )
        )

    if start_from > source_question_index + 1:
        raise ValueError(
            f"start_from={start_from} is out of range for {source_question_index} questions"
        )

    return LegacyQuiz(
        title=title,
        questions=questions,
        raw_questions=raw_questions,
        skipped_source_question_indexes=list(range(1, min(start_from, source_question_index + 1))),
        source_question_count=source_question_index,
        settings=dict(settings) if isinstance(settings, Mapping) else {},
    )


def _question_to_raw(
    item: Mapping[str, Any],
    *,
    source_question_index: int,
    clean_item_index: int,
    context: str,
    media: list[str],
) -> dict[str, Any]:
    options = item.get("options")
    if not isinstance(options, list):
        raise ValueError(f"Question #{source_question_index} must contain options list")

    answers = item.get("answers")
    if not isinstance(answers, list):
        raise ValueError(f"Question #{source_question_index} must contain answers list")

    raw: dict[str, Any] = {
        "source_question_index": source_question_index,
        "clean_item_index": clean_item_index,
        "question": _string(item.get("question"), default=""),
        "options": [_option_text(option, source_question_index) for option in options],
        "correct": [int(answer) for answer in answers],
    }
    if len(raw["correct"]) == 1 and item.get("mode") != "multiple":
        raw["correct"] = raw["correct"][0]

    explanation = _string(item.get("explanation"), default="")
    if explanation:
        raw["explanation"] = explanation
    if context:
        raw["context"] = context
    if media:
        raw["media"] = list(media)
    return raw


def _option_text(option: Any, source_question_index: int) -> str:
    if not isinstance(option, Mapping):
        raise ValueError(f"Question #{source_question_index} option must be an object")
    return _string(option.get("text"), default="")


def _media_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("context.media must be a list when present")
    return [_string(item, default="") for item in value if _string(item, default="")]


def _string(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        return default
    return normalize_text(value)
