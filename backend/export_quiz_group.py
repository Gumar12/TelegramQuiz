"""Export one date/section group from extended v2 JSON to upload JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.parser import load_json
from backend.validator import validate_all


def group_label(item: dict[str, Any]) -> str:
    return " ".join(
        part.strip()
        for part in [str(item.get("date", "")), str(item.get("section", ""))]
        if part and part.strip()
    )


def upload_item(item: dict[str, Any]) -> dict[str, Any]:
    out = {
        "question": item["question"],
        "options": item["options"],
        "correct": item["correct"],
        "explanation": item.get("explanation", ""),
    }
    for key in ["context_title", "context", "media"]:
        value = item.get(key)
        if value:
            out[key] = value
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export one quiz group from extended v2 JSON."
    )
    parser.add_argument("--source", required=True, help="Extended v2 JSON file")
    parser.add_argument("--group", required=True, help='Group label, e.g. "19 мая ОБЕД"')
    parser.add_argument("--output", required=True, help="Upload JSON output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_path = Path(args.source)
    data = json.loads(source_path.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("questions", [])
    selected = [upload_item(item) for item in items if group_label(item) == args.group]
    if not selected:
        raise SystemExit(f"No questions found for group: {args.group}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    questions = load_json(str(output_path))
    validate_all(questions)
    print(f"Wrote {len(questions)} questions to {output_path}")


if __name__ == "__main__":
    main()
