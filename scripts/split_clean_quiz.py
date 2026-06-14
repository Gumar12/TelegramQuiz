# -*- coding: utf-8 -*-
"""Split a clean quiz JSON (format 2.1-clean) into N balanced parts.

Cuts ONLY at context-block boundaries: consecutive questions that share the
same non-empty `context` string stay together in one part, so no shared context
is ever split across files. Parts are balanced by question count via greedy
packing toward an even target. Order is preserved; the quiz wrapper is kept.

Usage:
    python -m scripts.split_clean_quiz \
        --input quizzes/mne_nado_2_clean.json \
        --out-prefix quizzes/mne_nado_2_clean_part \
        --report quizzes/mne_nado_2_clean_split_report.json \
        --parts 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.normalizer_io import load_v2_dataset, write_json_atomic


def context_blocks(questions):
    """Group consecutive questions sharing the same non-empty context."""
    blocks, cur, cur_ctx = [], [], None
    for q in questions:
        ctx = q.get("context") or ""
        if ctx and ctx == cur_ctx:
            cur.append(q)
        else:
            if cur:
                blocks.append(cur)
            cur, cur_ctx = [q], (ctx or None)
    if cur:
        blocks.append(cur)
    return blocks


def pack_blocks(blocks, parts, total):
    """Greedily pack ordered blocks into `parts` groups balanced by count."""
    target = total / parts
    groups = [[] for _ in range(parts)]
    gi = 0
    placed = 0
    for block in blocks:
        # advance once the cumulative placed count crosses this part's share;
        # the guard on gi keeps the last part as the catch-all.
        if gi < parts - 1 and placed >= target * (gi + 1):
            gi += 1
        groups[gi].extend(block)
        placed += len(block)
    return groups


def media_refs(questions):
    return sum(len(q.get("media") or []) for q in questions)


def context_runs(questions):
    runs, prev = 0, None
    for q in questions:
        ctx = q.get("context") or ""
        if ctx and ctx != prev:
            runs += 1
        prev = ctx if ctx else None
    return runs


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Split clean quiz JSON into N balanced parts.")
    p.add_argument("--input", required=True)
    p.add_argument("--out-prefix", required=True, help="Part files: <prefix>_01.json ...")
    p.add_argument("--report", required=True)
    p.add_argument("--parts", type=int, default=3)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    data = load_v2_dataset(args.input)
    questions = data["questions"]
    blocks = context_blocks(questions)
    groups = pack_blocks(blocks, args.parts, len(questions))

    parts_report = []
    for i, group in enumerate(groups, start=1):
        out_path = f"{args.out_prefix}_{i:02d}.json"
        payload = {
            "quiz_title": data.get("quiz_title", ""),
            "quiz_description": data.get("quiz_description", ""),
            "format_version": data.get("format_version", "2.1-clean"),
            "questions": group,
        }
        write_json_atomic(out_path, payload)
        parts_report.append(
            {
                "file": out_path,
                "questions": len(group),
                "context_runs": context_runs(group),
                "media_refs": media_refs(group),
            }
        )

    report = {
        "input": args.input,
        "parts_count": args.parts,
        "items_total": len(questions),
        "items_written": sum(p["questions"] for p in parts_report),
        "parts": parts_report,
    }
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
