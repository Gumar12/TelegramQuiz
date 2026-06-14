"""Generate an editable QuizBot JSON for one date/section group."""
from __future__ import annotations

import argparse
import json
import re
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

from backend import config, gpt_normalizer
from backend.docx_to_quiz_json_v2 import build_output
from backend.normalizer_io import load_v2_dataset


def group_label(item: dict[str, Any]) -> str:
    return " ".join(
        part.strip()
        for part in [str(item.get("date", "")), str(item.get("section", ""))]
        if part and part.strip()
    )


def safe_filename_stem(value: str, fallback: str = "quiz") -> str:
    safe = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", value, flags=re.U).strip("_")
    return safe or fallback


def safe_stem(path: str | Path) -> str:
    return safe_filename_stem(Path(path).stem)


def default_sidecar_path(output: str | Path, suffix: str) -> str:
    output_path = Path(output)
    return str(output_path.with_name(f"{output_path.stem}_{suffix}.json"))


def load_or_build_source(args: Namespace) -> tuple[dict[str, Any], Path]:
    if args.source:
        source_path = Path(args.source)
        return load_v2_dataset(source_path), source_path

    if not args.docx:
        raise ValueError("Either --source or --docx is required")

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    source_path = workdir / "full_questions_v2.json"
    media_dir = workdir / "media"
    data = build_output(
        args.docx,
        source_path,
        media_dir,
        title="История Казахстана",
        description="Generated source",
    )
    return data, source_path


def write_group_source(source_data: dict[str, Any], group: str, output_path: Path) -> int:
    items = [
        dict(item)
        for item in source_data.get("questions", [])
        if group_label(item) == group
    ]
    if not items:
        return 0

    payload = {
        "quiz_title": group,
        "quiz_description": "OpenAI normalized editable source",
        "questions": items,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(items)


def group_labels(source_data: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    labels: list[str] = []
    for item in source_data.get("questions", []):
        label = group_label(item)
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def output_path_for_group(output_dir: str | Path, group: str) -> Path:
    stem = safe_filename_stem(group, fallback="Без_группы")
    return Path(output_dir) / f"{stem}.json"


def normalizer_args(args: Namespace, group_source: Path, source_path: Path) -> Namespace:
    return Namespace(
        input=str(group_source),
        output=str(Path(args.output)),
        review=str(args.review or default_sidecar_path(args.output, "review")),
        report=str(args.report or default_sidecar_path(args.output, "report")),
        model=args.model,
        limit=None,
        start_id=None,
        max_retries=args.max_retries,
        seed=args.seed,
        image_detail=args.image_detail,
        ffmpeg_path="ffmpeg",
        media_max_side=1024,
        media_jpeg_quality=3,
        media_root=args.media_root,
        style_source=str(Path(args.style_source)) if args.style_source else str(source_path),
        style_examples=args.style_examples,
        dry_run=args.dry_run,
    )


def generate_all_groups(args: Namespace) -> int:
    source_data, source_path = load_or_build_source(args)
    labels = group_labels(source_data)
    if not labels:
        print("ERROR: no groups found", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    group_workdir = Path(args.workdir) / "groups"
    failures: list[tuple[str, int]] = []

    print(f"Groups found: {len(labels)}")
    for label in labels:
        output_path = output_path_for_group(output_dir, label)
        group_source = group_workdir / f"{safe_stem(output_path)}_source.json"
        selected_count = write_group_source(source_data, label, group_source)
        if selected_count == 0:
            failures.append((label, 1))
            print(f"ERROR: no questions found for group: {label}", file=sys.stderr)
            continue

        group_args = Namespace(**vars(args))
        group_args.group = label
        group_args.output = str(output_path)
        group_args.review = default_sidecar_path(output_path, "review")
        group_args.report = default_sidecar_path(output_path, "report")

        print(f"Group source: {group_source} ({selected_count} questions)")
        exit_code = gpt_normalizer.run(normalizer_args(group_args, group_source, source_path))
        if exit_code != 0:
            failures.append((label, exit_code))

    if failures:
        print("Failed groups:", file=sys.stderr)
        for label, exit_code in failures:
            print(f"  {label}: exit code {exit_code}", file=sys.stderr)
        return 1

    print()
    print(f"Editable quiz JSON files: {output_dir}")
    print("Validate one file:")
    print(f"  python -m backend.validate_quiz_json --file {output_dir / '<group>.json'}")
    print("Upload one file:")
    print(
        "  python -m backend.main --speed fast "
        f"--file {output_dir / '<group>.json'} --name \"<group>\""
    )
    return 0


def generate(args: Namespace) -> int:
    try:
        if getattr(args, "all_groups", False):
            return generate_all_groups(args)

        source_data, source_path = load_or_build_source(args)
        workdir = Path(args.workdir)
        group_source = workdir / f"{safe_stem(args.output)}_source.json"
        selected_count = write_group_source(source_data, args.group, group_source)
        if selected_count == 0:
            print(f"ERROR: no questions found for group: {args.group}", file=sys.stderr)
            return 1

        print(f"Group source: {group_source} ({selected_count} questions)")
        exit_code = gpt_normalizer.run(normalizer_args(args, group_source, source_path))
        if exit_code == 0:
            print()
            print(f"Editable JSON: {args.output}")
            print(f"Review JSON: {args.review or default_sidecar_path(args.output, 'review')}")
            print(f"Report JSON: {args.report or default_sidecar_path(args.output, 'report')}")
            print()
            print("After manual edits:")
            print(f"  python -m backend.validate_quiz_json --file {args.output}")
            print(
                "  python -m backend.main --speed fast "
                f"--file {args.output} --name \"{args.group}\""
            )
        return exit_code
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def parse_args(argv: list[str] | None = None) -> Namespace:
    parser = argparse.ArgumentParser(
        description="Generate editable QuizBot JSON files from v2 source or DOCX."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--source", help="Full v2 JSON source parsed from DOCX")
    input_group.add_argument("--docx", help="DOCX file to parse before generation")
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--group", help='Group label, e.g. "19 мая УТРО"')
    mode_group.add_argument("--all-groups", action="store_true", help="Generate one editable JSON per date/section group")
    parser.add_argument("--output", help="Editable clean JSON output for --group mode")
    parser.add_argument("--output-dir", default=str(config.DATA_DIR / "quizzes"), help="Directory for --all-groups output JSON files")
    parser.add_argument("--review", default=None, help="Review JSON output")
    parser.add_argument("--report", default=None, help="Report JSON output")
    parser.add_argument("--workdir", default=str(config.DATA_DIR / ".normalizer_tmp"), help="Working directory")
    parser.add_argument("--model", default="", help="OpenAI model name")
    parser.add_argument("--max-retries", type=gpt_normalizer._positive_int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--media-root", default=str(config.DATA_DIR))
    parser.add_argument("--style-source", default=None, help="Full v2 JSON used for style examples")
    parser.add_argument("--style-examples", type=gpt_normalizer._non_negative_int, default=5)
    parser.add_argument("--image-detail", choices=["low", "auto", "high"], default="high")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.group and not args.output:
        parser.error("--output is required when --group is used")
    return args


def main() -> None:
    raise SystemExit(generate(parse_args()))


if __name__ == "__main__":
    main()
