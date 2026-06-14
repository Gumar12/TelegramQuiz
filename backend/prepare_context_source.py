"""Prepare a focused v2 source file with inherited context media for one group."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def group_label(item: dict[str, Any]) -> str:
    return " ".join(
        part.strip()
        for part in [str(item.get("date", "")), str(item.get("section", ""))]
        if part and part.strip()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--inherit-media-after-id", type=int, default=None)
    parser.add_argument("--inherit-media-until-id", type=int, default=None)
    parser.add_argument("--context", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = json.loads(Path(args.source).read_text(encoding="utf-8"))
    items = [
        dict(item)
        for item in data.get("questions", [])
        if group_label(item) == args.group
    ]
    if not items:
        raise SystemExit(f"No questions found for group: {args.group}")

    inherited_media: list[str] = []
    for item in items:
        if item.get("media"):
            inherited_media = list(item["media"])
        item_id = int(item.get("id", 0))
        in_range = (
            inherited_media
            and args.inherit_media_after_id is not None
            and args.inherit_media_until_id is not None
            and args.inherit_media_after_id <= item_id <= args.inherit_media_until_id
        )
        if in_range and not item.get("media"):
            item["media"] = list(inherited_media)
        if in_range and args.context and not item.get("context"):
            item["context"] = args.context

    output = {
        "quiz_title": args.group,
        "quiz_description": "OpenAI normalized source",
        "questions": items,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(items)} questions to {output_path}")


if __name__ == "__main__":
    main()
