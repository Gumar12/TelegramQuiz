"""File IO helpers for the GPT normalizer."""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.normalizer_models import CleanQuestion, ReviewQuestion

# Review items with these reasons stopped mid-run because the API was down.
# On resume we retry them instead of treating them as finished work.
RETRYABLE_REVIEW_REASONS = {"gpt_request_failed"}


def load_v2_dataset(path: str | Path) -> dict[str, Any]:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input JSON file not found: {input_path}")

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {input_path}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected top-level JSON object in {input_path}")
    if not isinstance(data.get("questions"), list):
        raise ValueError(f"Expected top-level 'questions' list in {input_path}")
    return data


def write_json_atomic(path: str | Path, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")

    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink()


def clean_payload(source_data: dict[str, Any], clean: list[CleanQuestion]) -> dict[str, Any]:
    return {
        "quiz_title": source_data.get("quiz_title", ""),
        "quiz_description": source_data.get("quiz_description", ""),
        "format_version": "2.1-clean",
        "questions": [item.model_dump() for item in clean],
    }


def review_payload(source_data: dict[str, Any], review: list[ReviewQuestion]) -> dict[str, Any]:
    return {
        "quiz_title": source_data.get("quiz_title", ""),
        "quiz_description": source_data.get("quiz_description", ""),
        "format_version": "2.1-review",
        "questions": [item.model_dump() for item in review],
    }


def _load_question_models(path: str | Path, model: type) -> list:
    """Load previously written questions back into models, skipping unusable rows.

    Missing or malformed files yield an empty list so a resume run simply starts
    fresh for that file instead of crashing. Individual rows that fail validation
    are dropped, which lets the next run re-process them.
    """
    file = Path(path)
    if not file.exists():
        return []
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("questions", []) if isinstance(data, dict) else []
    loaded = []
    for item in items:
        try:
            loaded.append(model(**item))
        except (TypeError, ValidationError):
            continue
    return loaded


def load_existing_results(
    output_path: str | Path,
    review_path: str | Path,
) -> tuple[list[CleanQuestion], list[ReviewQuestion]]:
    """Read clean and review questions written by an earlier (possibly stopped) run."""
    existing_clean = _load_question_models(output_path, CleanQuestion)
    existing_review = _load_question_models(review_path, ReviewQuestion)
    return existing_clean, existing_review


def resume_state(
    existing_clean: list[CleanQuestion],
    existing_review: list[ReviewQuestion],
) -> tuple[set[int], list[ReviewQuestion]]:
    """Compute which source ids are already done and which reviews to keep.

    Returns ``(done_ids, carry_review)`` where ``done_ids`` are source item ids
    that should be skipped on resume, and ``carry_review`` are the terminal review
    entries to preserve. Outage failures (``gpt_request_failed``) are intentionally
    excluded from both so they get retried.
    """
    done_ids = {item.source_item_id for item in existing_clean}
    carry_review: list[ReviewQuestion] = []
    for item in existing_review:
        if item.error_reason in RETRYABLE_REVIEW_REASONS:
            continue
        done_ids.add(item.source_item_id)
        carry_review.append(item)
    return done_ids, carry_review


def _merge_by_source_id(existing: list, new: list) -> list:
    by_id = {item.source_item_id: item for item in existing}
    for item in new:
        by_id[item.source_item_id] = item
    return [by_id[key] for key in sorted(by_id)]


def merge_clean(existing: list[CleanQuestion], new: list[CleanQuestion]) -> list[CleanQuestion]:
    """Merge prior and freshly normalized questions, newest winning, sorted by id."""
    return _merge_by_source_id(existing, new)


def merge_review(existing: list[ReviewQuestion], new: list[ReviewQuestion]) -> list[ReviewQuestion]:
    """Merge carried-over and fresh review entries, newest winning, sorted by id."""
    return _merge_by_source_id(existing, new)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_report(
    *,
    input_path: str,
    output_path: str,
    review_path: str,
    model: str,
    max_retries: int,
    total: int,
    clean: list[CleanQuestion],
    review: list[ReviewQuestion],
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    reason_counts = Counter(item.error_reason for item in review)
    return {
        "input": input_path,
        "output": output_path,
        "review": review_path,
        "model": model,
        "started_at": started_at or utc_now_iso(),
        "finished_at": finished_at or utc_now_iso(),
        "items_total": total,
        "items_clean": len(clean),
        "items_review": len(review),
        "max_retries": max_retries,
        "error_reason_counts": dict(sorted(reason_counts.items())),
    }
