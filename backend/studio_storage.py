"""Storage helpers for the local QuizBot Studio API."""
from __future__ import annotations

import json
import re
import shutil
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
        correct = correct[0] if correct else None
    if isinstance(correct, int):
        return max(0, correct - 1)
    return -1


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
        warnings = item.get("warnings", [])
        options = item.get("options", [])
        correct = item.get("correct")
        correct_values = correct if isinstance(correct, list) else [correct] if isinstance(correct, int) else []
        question_text = str(item.get("question", ""))
        explanation_text = str(item.get("explanation", ""))
        if (
            flags
            or warnings
            or item.get("needs_distractor_review")
            or str(item.get("type", "")).startswith("needs_")
            or len(question_text) > 255
            or len(explanation_text) > 200
            or not isinstance(options, list)
            or len(options) < 3
            or any(not isinstance(option, str) or len(option) > 100 for option in options)
            or not correct_values
            or any(index < 1 or index > len(options) for index in correct_values)
        ):
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
                "warnings": item.get("warnings", []),
                "needs_distractor_review": bool(item.get("needs_distractor_review", False)),
            }
        )

    return {
        "id": group_id,
        "name": _display_name(group_id, payload),
        "date": _date_from_name(_display_name(group_id, payload)),
        "description": str(payload.get("quiz_description", "")),
        "allow_duplicate_questions": bool(payload.get("allow_duplicate_questions", False)),
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
        "warnings",
        "needs_distractor_review",
    ]:
        if key in item and item[key] not in (None, "", []):
            output[key] = item[key]
    return output


def _clean_option_text(option: Any) -> str:
    if isinstance(option, dict):
        return str(option.get("text", "")).strip()
    return str(option).strip()


def _clean_answers_to_correct(answers: Any) -> int | list[int]:
    if isinstance(answers, list):
        correct_values = [item for item in answers if isinstance(item, int)]
        if len(correct_values) == 1:
            return correct_values[0]
        return correct_values
    if isinstance(answers, int):
        return answers
    return 1


def _payload_from_clean_quiz(payload: dict[str, Any], title: str, description: str) -> dict[str, Any]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("items must be a list")

    active_context = ""
    active_media: list[str] = []
    questions: list[dict[str, Any]] = []
    source_question_index = 0
    for item_index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "question"))
        if item_type == "context":
            active_context = str(item.get("text", ""))
            media = item.get("media", [])
            active_media = [str(value) for value in media] if isinstance(media, list) else []
            continue
        if item_type == "reset_context":
            active_context = ""
            active_media = []
            continue
        if item_type != "question":
            continue

        source_question_index += 1
        raw_options = item.get("options", [])
        options = [_clean_option_text(option) for option in raw_options] if isinstance(raw_options, list) else []
        item_media = item.get("media", [])
        media = [str(value) for value in item_media] if isinstance(item_media, list) else []
        questions.append(
            {
                "source_item_id": item.get("source_item_id") or source_question_index,
                "clean_item_index": item_index,
                "question": item.get("question", ""),
                "options": options,
                "correct": _clean_answers_to_correct(item.get("answers")),
                "explanation": item.get("explanation", ""),
                "context_title": item.get("context_title", ""),
                "context": item.get("context", active_context),
                "media": media or active_media,
            }
        )

    return {
        "quiz_title": title or str(payload.get("title", "")).strip() or "Импортированный квиз",
        "quiz_description": description or str(payload.get("description", "")),
        "allow_duplicate_questions": bool(payload.get("allow_duplicate_questions", False)),
        "format_version": "2.1-imported-clean",
        "questions": questions,
    }


def _looks_like_ui_group(payload: dict[str, Any]) -> bool:
    if "quiz_title" in payload:
        return False
    questions = payload.get("questions", [])
    if "name" not in payload or not isinstance(questions, list):
        return False
    for item in questions:
        if not isinstance(item, dict):
            continue
        correct = item.get("correct")
        options = item.get("options", [])
        if isinstance(correct, int) and isinstance(options, list) and 0 <= correct < len(options):
            return True
    return False


def _looks_like_block_markup(payload: dict[str, Any]) -> bool:
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        return False
    return any(
        isinstance(item, dict)
        and "question" not in item
        and (
            "question_block_ids" in item
            or "option_block_ids" in item
            or "correct_option_block_ids" in item
        )
        for item in questions
    )


def _block_text_lookup(payload: dict[str, Any]) -> dict[str, str]:
    blocks = payload.get("blocks", payload.get("source_blocks", []))
    if isinstance(blocks, dict):
        return {str(key): str(value) for key, value in blocks.items()}
    if not isinstance(blocks, list):
        return {}

    lookup: dict[str, str] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_id = block.get("id")
        if not block_id:
            continue
        text = block.get("text", block.get("text_md", block.get("content", "")))
        lookup[str(block_id)] = str(text).strip()
    return lookup


def _texts_for_block_ids(block_ids: Any, lookup: dict[str, str]) -> list[str]:
    if not isinstance(block_ids, list):
        return []
    return [lookup[str(block_id)] for block_id in block_ids if str(block_id) in lookup and lookup[str(block_id)]]


def _context_by_question_id(payload: dict[str, Any], lookup: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    regions = payload.get("context_regions", [])
    if not isinstance(regions, list):
        return result
    for region in regions:
        if not isinstance(region, dict):
            continue
        context_text = "\n".join(_texts_for_block_ids(region.get("block_ids"), lookup)).strip()
        if not context_text:
            continue
        applies_to = region.get("applies_to_question_ids", [])
        if not isinstance(applies_to, list):
            continue
        for question_id in applies_to:
            result[str(question_id)] = context_text
    return result


def _payload_from_block_markup(payload: dict[str, Any], title: str, description: str) -> dict[str, Any]:
    lookup = _block_text_lookup(payload)
    if not lookup:
        raise ValueError(
            "JSON contains only block references. Export JSON with question text, options, and answers."
        )

    context_lookup = _context_by_question_id(payload, lookup)
    questions: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("questions", []), start=1):
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("id", index))
        question_text = "\n".join(_texts_for_block_ids(item.get("question_block_ids"), lookup)).strip()
        option_ids = item.get("option_block_ids", [])
        options = _texts_for_block_ids(option_ids, lookup)
        correct_ids = {str(value) for value in item.get("correct_option_block_ids", []) if value}
        correct_values = [
            option_index
            for option_index, option_id in enumerate(option_ids if isinstance(option_ids, list) else [], start=1)
            if str(option_id) in correct_ids
        ]
        context_text = "\n".join(_texts_for_block_ids(item.get("context_block_ids"), lookup)).strip()
        if not context_text:
            context_text = context_lookup.get(question_id, "")
        questions.append(
            {
                "source_item_id": question_id,
                "question": question_text,
                "options": options,
                "correct": correct_values[0] if len(correct_values) == 1 else correct_values or 1,
                "explanation": "",
                "context": context_text,
                "quality_flags": [str(flag) for flag in item.get("warnings", []) if isinstance(flag, str)],
                "source": "block_markup",
            }
        )

    return {
        "quiz_title": title or str(payload.get("document_id", "")).strip() or "Импортированный квиз",
        "quiz_description": description,
        "allow_duplicate_questions": bool(payload.get("allow_duplicate_questions", False)),
        "format_version": "2.1-imported-block-markup",
        "questions": questions,
    }


def import_group_payload(
    group_id: str,
    payload: Any,
    quizzes_dir: str | Path = DEFAULT_QUIZZES_DIR,
    *,
    title: str = "",
    description: str = "",
) -> dict[str, Any]:
    if isinstance(payload, list):
        payload = {"questions": payload}
    if not isinstance(payload, dict):
        raise ValueError("JSON must be an object or a list of questions")

    if "items" in payload:
        imported = _payload_from_clean_quiz(payload, title, description)
    elif _looks_like_ui_group(payload):
        return save_group(
            group_id,
            {
                **payload,
                "name": title or payload.get("name") or group_id.replace("_", " "),
                "description": description or payload.get("description", ""),
            },
            quizzes_dir,
        )
    elif _looks_like_block_markup(payload):
        imported = _payload_from_block_markup(payload, title, description)
    else:
        questions = payload.get("questions")
        if not isinstance(questions, list):
            raise ValueError("JSON must contain questions list")
        imported = dict(payload)
        imported["quiz_title"] = (
            title
            or str(payload.get("quiz_title", "")).strip()
            or str(payload.get("title", "")).strip()
            or str(payload.get("name", "")).strip()
            or group_id.replace("_", " ")
        )
        imported["quiz_description"] = description or str(payload.get("quiz_description", payload.get("description", "")))
        imported["allow_duplicate_questions"] = bool(payload.get("allow_duplicate_questions", False))
        imported["format_version"] = str(payload.get("format_version", "2.1-imported"))
        imported["questions"] = [item for item in questions if isinstance(item, dict)]

    if not imported["questions"]:
        raise ValueError("No questions found in imported JSON")
    _write_json(_group_path(group_id, quizzes_dir), imported)
    return load_group(group_id, quizzes_dir)


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
        "allow_duplicate_questions": bool(group.get("allow_duplicate_questions", False)),
        "format_version": "2.1-clean",
        "questions": [
            _backend_question(item)
            for item in questions
            if isinstance(item, dict)
        ],
    }
    _write_json(_group_path(group_id, quizzes_dir), payload)
    return load_group(group_id, quizzes_dir)


def delete_group(group_id: str, quizzes_dir: str | Path = DEFAULT_QUIZZES_DIR) -> dict[str, Any]:
    path = _group_path(group_id, quizzes_dir)
    if not path.exists():
        raise FileNotFoundError(f"Quiz group not found: {group_id}")
    path.unlink()
    return {"id": group_id, "deleted": True}


def archive_group(group_id: str, quizzes_dir: str | Path = DEFAULT_QUIZZES_DIR) -> dict[str, Any]:
    path = _group_path(group_id, quizzes_dir)
    if not path.exists():
        raise FileNotFoundError(f"Quiz group not found: {group_id}")

    archive_dir = Path(quizzes_dir) / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    if target.exists():
        index = 2
        while True:
            candidate = archive_dir / f"{path.stem}-{index}{path.suffix}"
            if not candidate.exists():
                target = candidate
                break
            index += 1
    shutil.move(str(path), str(target))
    return {"id": group_id, "archived": True, "path": str(target)}
