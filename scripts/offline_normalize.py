# -*- coding: utf-8 -*-
"""Offline quiz normalization — runs the GPT normalizer's deterministic path only.

For source_document_bold / source_document_answer_indexes items the normalizer
builds a clean question WITHOUT any OpenAI call (see
backend.gpt_normalizer.normalize_one_with_retries lines 575-583). This driver
runs exactly that path and routes every GPT-dependent item to review with a
clear reason, so no API key and no paid calls are needed.

Output is byte-compatible with the real normalizer (same clean/review/report
payloads), so the GPT-dependent remainder can be filled in later with a key.

Usage:
    python -m scripts.offline_normalize \
        --input quizzes/mne_nado_2_questions_v2.json \
        --output quizzes/mne_nado_2_clean.json \
        --review quizzes/mne_nado_2_clean_review.json \
        --report quizzes/mne_nado_2_clean_report.json \
        --seed 42
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.gpt_normalizer import (
    _build_source_document_question,
    _review_question,
    iter_selected_raw_questions,
    shuffle_options,
)
from backend.normalizer_io import (
    build_report,
    clean_payload,
    load_v2_dataset,
    review_payload,
    write_json_atomic,
)
from backend.normalizer_models import LocalValidationError, validate_clean_question


# error_reason is a fixed Literal in the model; "max_retries_exceeded" is the
# generic "could not normalize" bucket. The real cause (needs GPT) goes in notes.
OFFLINE_REVIEW_REASON = "max_retries_exceeded"


def normalize_offline(data, seed):
    clean, review = [], []
    for raw in iter_selected_raw_questions(data, None, None):
        item = _build_source_document_question(raw)
        if item is not None:
            try:
                validate_clean_question(item, check_distractor_quality=False)
                item = shuffle_options(item, seed)
                validate_clean_question(item, check_distractor_quality=False)
                clean.append(item)
                continue
            except LocalValidationError:
                pass  # trusted source failed local checks -> needs GPT
        note = (
            "Offline run, no API key: requires OpenAI normalization. "
            f"distractors_source={raw.distractors_source!r}"
        )
        review.append(_review_question(raw, OFFLINE_REVIEW_REASON, None, 0, note))
    return clean, review


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Offline (no-GPT) quiz normalization.")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--review", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    data = load_v2_dataset(args.input)
    total = len(iter_selected_raw_questions(data, None, None))
    clean, review = normalize_offline(data, args.seed)
    report = build_report(
        input_path=args.input,
        output_path=args.output,
        review_path=args.review,
        model="offline-no-gpt",
        max_retries=0,
        total=total,
        clean=clean,
        review=review,
    )
    write_json_atomic(args.output, clean_payload(data, clean))
    write_json_atomic(args.review, review_payload(data, review))
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
