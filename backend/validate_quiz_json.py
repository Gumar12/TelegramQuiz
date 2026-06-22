"""Validate an editable QuizBot JSON before uploading it."""
from __future__ import annotations

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from backend.models import Question
from backend.parser import load_json, load_json_metadata
from backend.validator import validate_all


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_raw_items(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        data = data["questions"]
    if not isinstance(data, list):
        raise ValueError("Expected top-level JSON array or object with questions")
    return [item if isinstance(item, dict) else {} for item in data]


def load_questions_with_raw(path: str | Path) -> tuple[list[Question], list[dict[str, Any]]]:
    return load_json(path), load_raw_items(path)


def allow_duplicate_questions(path: str | Path) -> bool:
    return bool(load_json_metadata(path).get("allow_duplicate_questions"))


def _correct_indexes(question: Question) -> list[int]:
    return question.correct if isinstance(question.correct, list) else [question.correct]


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio()


def build_quality_report(
    questions: list[Question],
    raw_items: list[dict[str, Any]],
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    correct_position_counts: dict[str, int] = {}
    multi_answer_count = 0
    context_count = 0
    media_count = 0

    for index, question in enumerate(questions, 1):
        raw = raw_items[index - 1] if index - 1 < len(raw_items) else {}
        source_item_id = raw.get("source_item_id")
        raw_context = raw.get("context")
        context_text = raw_context if isinstance(raw_context, str) else question.context
        correct_indexes = _correct_indexes(question)
        if len(correct_indexes) > 1:
            multi_answer_count += 1
        for correct in correct_indexes:
            correct_position_counts[str(correct)] = correct_position_counts.get(str(correct), 0) + 1
        if context_text:
            context_count += 1
            if len(context_text) < 15:
                warnings.append(
                    {
                        "index": index,
                        "source_item_id": source_item_id,
                        "question": question.question,
                        "code": "short_context",
                        "message": "Контекст слишком короткий; проверь, что это не обрывок.",
                        "context": context_text,
                    }
                )
            elif len(context_text) < 45 and not any(mark in context_text for mark in ".!?;:"):
                warnings.append(
                    {
                        "index": index,
                        "source_item_id": source_item_id,
                        "question": question.question,
                        "code": "context_fragment",
                        "message": "Контекст похож на обрывок вопроса, а не на полноценный контекст.",
                        "context": context_text,
                    }
                )
        if question.media:
            media_count += 1

        for left_index, left in enumerate(question.options, 1):
            if "…" in left or "..." in left:
                warnings.append(
                    {
                        "index": index,
                        "source_item_id": source_item_id,
                        "question": question.question,
                        "code": "truncated_option",
                        "message": f"Вариант #{left_index} выглядит обрезанным.",
                        "option": {"index": left_index, "text": left},
                    }
                )
            for right_index in range(left_index + 1, len(question.options) + 1):
                right = question.options[right_index - 1]
                if _similarity(left, right) >= 0.9:
                    warnings.append(
                        {
                            "index": index,
                            "source_item_id": source_item_id,
                            "question": question.question,
                            "code": "similar_options",
                            "message": f"Варианты #{left_index} и #{right_index} слишком похожи.",
                            "left_option": {"index": left_index, "text": left},
                            "right_option": {"index": right_index, "text": right},
                        }
                    )

    return {
        "questions_total": len(questions),
        "multi_answer_count": multi_answer_count,
        "context_count": context_count,
        "media_count": media_count,
        "correct_position_counts": dict(sorted(correct_position_counts.items())),
        "warnings": warnings,
    }


def validate_file(path: str | Path, *, strict: bool = False) -> int:
    configure_stdout()
    try:
        questions, raw_items = load_questions_with_raw(path)
        validate_all(questions, allow_duplicate_questions=allow_duplicate_questions(path))
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = build_quality_report(questions, raw_items)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if strict and report["warnings"]:
        return 2
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate editable QuizBot JSON.")
    parser.add_argument("--file", required=True, help="JSON file to validate")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 when quality warnings are present",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    raise SystemExit(validate_file(args.file, strict=args.strict))


if __name__ == "__main__":
    main()
