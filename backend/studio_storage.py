"""Storage helpers for the local QuizBot Studio API."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend import config

DEFAULT_QUIZZES_DIR = config.DATA_DIR / "quizzes"


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def group_id_from_path(path: str | Path) -> str:
    return Path(path).stem


def _group_path(group_id: str, quizzes_dir: str | Path = DEFAULT_QUIZZES_DIR) -> Path:
    safe_id = Path(group_id).name
    return Path(quizzes_dir) / f"{safe_id}.json"


def _display_name(group_id: str, payload: dict[str, Any]) -> str:
    title = payload.get("quiz_title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return group_id.replace("_", " ")


def _is_primary_quiz_file(path: Path) -> bool:
    if path.suffix.lower() != ".json":
        return False
    return not path.stem.endswith(("_review", "_report", "_source"))


def list_groups(quizzes_dir: str | Path = DEFAULT_QUIZZES_DIR) -> list[dict[str, Any]]:
    root = Path(quizzes_dir)
    if not root.exists():
        return []

    groups: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        if not _is_primary_quiz_file(path):
            continue
        payload = _read_json(path)
        group_id = group_id_from_path(path)
        questions = payload.get("questions", [])
        groups.append(
            {
                "id": group_id,
                "name": _display_name(group_id, payload),
                "description": str(payload.get("quiz_description", "")),
                "questions_count": len(questions) if isinstance(questions, list) else 0,
                "path": str(path),
            }
        )
    return groups


def _ui_question_id(item: dict[str, Any], index: int) -> str:
    source_id = item.get("source_item_id") or item.get("id")
    if source_id is not None:
        return str(source_id)
    return f"q_{index + 1}"


def _to_zero_based_correct(correct: Any) -> int:
    if isinstance(correct, list):
        correct = correct[0] if correct else 1
    if isinstance(correct, int):
        return max(0, correct - 1)
    return 0


def _to_one_based_correct(correct: Any) -> int:
    if isinstance(correct, int):
        return correct + 1
    return 1


def _status_for_payload(payload: dict[str, Any]) -> str:
    questions = payload.get("questions", [])
    if not questions:
        return "draft"
    for item in questions:
        flags = item.get("quality_flags", [])
        if flags or item.get("needs_distractor_review"):
            return "review"
    return "ready"


def load_group(group_id: str, quizzes_dir: str | Path = DEFAULT_QUIZZES_DIR) -> dict[str, Any]:
    path = _group_path(group_id, quizzes_dir)
    if not path.exists():
        raise FileNotFoundError(f"Quiz group not found: {group_id}")
    payload = _read_json(path)
    raw_questions = payload.get("questions", [])
    if not isinstance(raw_questions, list):
        raw_questions = []

    questions: list[dict[str, Any]] = []
    for index, item in enumerate(raw_questions):
        if not isinstance(item, dict):
            continue
        correct = item.get("correct", 1)
        questions.append(
            {
                "id": _ui_question_id(item, index),
                "source_item_id": item.get("source_item_id"),
                "date": item.get("date", ""),
                "section": item.get("section", ""),
                "context_title": item.get("context_title", ""),
                "context": item.get("context", ""),
                "media": item.get("media", []),
                "question": item.get("question", ""),
                "options": item.get("options", []),
                "correct": _to_zero_based_correct(correct),
                "backend_correct": correct,
                "explanation": item.get("explanation", ""),
                "explanation_full": item.get("explanation_full", ""),
                "type": item.get("type", ""),
                "source": item.get("source", ""),
                "quality_flags": item.get("quality_flags", []),
            }
        )

    return {
        "id": group_id,
        "name": _display_name(group_id, payload),
        "date": _date_from_name(_display_name(group_id, payload)),
        "description": str(payload.get("quiz_description", "")),
        "status": _status_for_payload(payload),
        "questions": questions,
        "path": str(path),
    }


def _date_from_name(name: str) -> str:
    match = re.search(r"\b\d{1,2}\s+мая\b", name, flags=re.I)
    return match.group(0) if match else ""


def _backend_question(item: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "question": item.get("question", ""),
        "options": list(item.get("options", [])),
        "correct": _to_one_based_correct(item.get("correct", 0)),
        "explanation": item.get("explanation", ""),
        "context_title": item.get("context_title", ""),
        "context": item.get("context", ""),
        "media": list(item.get("media", [])),
    }
    for key in [
        "source_item_id",
        "date",
        "section",
        "explanation_full",
        "type",
        "source",
        "quality_flags",
    ]:
        if key in item and item[key] not in (None, "", []):
            output[key] = item[key]
    return output


def save_group(
    group_id: str,
    group: dict[str, Any],
    quizzes_dir: str | Path = DEFAULT_QUIZZES_DIR,
) -> dict[str, Any]:
    questions = group.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("questions must be a list")

    payload = {
        "quiz_title": group.get("name", group_id.replace("_", " ")),
        "quiz_description": group.get("description", ""),
        "format_version": "2.1-clean",
        "questions": [
            _backend_question(item)
            for item in questions
            if isinstance(item, dict)
        ],
    }
    _write_json(_group_path(group_id, quizzes_dir), payload)
    return load_group(group_id, quizzes_dir)
