from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from backend.models import Question
from backend.validate_quiz_json import build_quality_report, load_questions_with_raw
from backend.validator import validate_all


@dataclass
class Block:
    block_id: int
    paragraph_id: int
    text: str
    bold: str
    media: list[str]


class ParsedQuestion(BaseModel):
    source_start_block: int = Field(ge=1)
    option_start_block: int = Field(ge=1)
    source_end_block: int = Field(ge=1)
    context_title: str = ""
    context: str = ""
    media: list[str] = Field(default_factory=list)
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=4, max_length=4)
    correct: int = Field(ge=1, le=4)
    explanation: str = Field(default="", max_length=200)
    issues: list[str] = Field(default_factory=list)


class ChunkOutput(BaseModel):
    questions: list[ParsedQuestion]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def run_is_bold(run: Any) -> bool:
    if run.bold is not None:
        return bool(run.bold)
    style = getattr(run, "style", None)
    font = getattr(style, "font", None)
    return bool(getattr(font, "bold", False))


def extract_blocks(docx_path: Path, media_dir: Path) -> list[Block]:
    doc = Document(docx_path)
    media_dir.mkdir(parents=True, exist_ok=True)
    blocks: list[Block] = []
    image_counter = 1

    for paragraph_id, para in enumerate(doc.paragraphs, start=1):
        text_parts: list[str] = []
        bold_parts: list[str] = []
        media: list[str] = []

        for run in para.runs:
            if run.text:
                text_parts.append(run.text)
                if run_is_bold(run):
                    bold_parts.append(run.text)

            for drawing in run._element.xpath(".//w:drawing"):
                for blip in drawing.xpath(".//a:blip"):
                    r_id = blip.get(qn("r:embed"))
                    if not r_id:
                        continue
                    image_part = doc.part.related_parts.get(r_id)
                    if not image_part:
                        continue
                    ext = image_part.content_type.split("/")[-1]
                    if ext == "jpeg":
                        ext = "jpg"
                    filename = f"image_{image_counter:03d}.{ext}"
                    image_counter += 1
                    out_path = media_dir / filename
                    out_path.write_bytes(image_part.blob)
                    media.append(filename)

        text = clean("".join(text_parts))
        bold = clean("".join(bold_parts))
        if text or media:
            blocks.append(
                Block(
                    block_id=len(blocks) + 1,
                    paragraph_id=paragraph_id,
                    text=text,
                    bold=bold,
                    media=media,
                )
            )
    return blocks


def block_line(block: Block) -> str:
    prefix = f"[B{block.block_id:04d} P{block.paragraph_id:04d}]"
    parts = []
    if block.text:
        parts.append(f"{prefix} {block.text}")
    for media in block.media:
        parts.append(f"{prefix} [IMAGE {media}]")
    if block.bold:
        parts.append(f"{prefix} BOLD: {block.bold}")
    return "\n".join(parts)


def build_schema() -> dict[str, Any]:
    question_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_start_block",
            "option_start_block",
            "source_end_block",
            "context_title",
            "context",
            "media",
            "question",
            "options",
            "correct",
            "explanation",
            "issues",
        ],
        "properties": {
            "source_start_block": {"type": "integer", "minimum": 1},
            "option_start_block": {"type": "integer", "minimum": 1},
            "source_end_block": {"type": "integer", "minimum": 1},
            "context_title": {"type": "string"},
            "context": {"type": "string"},
            "media": {"type": "array", "items": {"type": "string"}},
            "question": {"type": "string", "minLength": 1, "maxLength": 300},
            "options": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {"type": "string", "minLength": 1, "maxLength": 100},
            },
            "correct": {"type": "integer", "minimum": 1, "maximum": 4},
            "explanation": {"type": "string", "maxLength": 200},
            "issues": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "json_schema",
        "name": "docx_quiz_chunk",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["questions"],
            "properties": {
                "questions": {"type": "array", "items": question_schema},
            },
        },
    }


SYSTEM_PROMPT = """You reconstruct Telegram quiz JSON from extracted DOCX blocks.

The source language is Russian/Kazakh history. The extraction preserves paragraph order,
image markers, and BOLD markers. BOLD marks the correct answer option in the source.

Rules:
- Use only text that exists in the input blocks. Do not invent facts.
- Return only questions whose first A) option block is inside the requested CORE block range.
- option_start_block must be the block ID of the real A) answer option, not the prompt
  and not the I/II/III/IV statement list.
- Each quiz item has exactly four options A-D. Remove the A)/B)/C)/D) labels from option text.
- correct is the 1-based index of the option marked by BOLD.
- If the source has a title, long passage, statements I-IV, or an image needed for the question,
  put that material into context_title/context/media. Do not drop it.
- If statements I-IV belong to a question, keep the short prompt in question and put the
  statements into context so Telegram's 300-character question limit is respected.
- If the same passage or image applies to several following questions, copy the same
  context/media into each of those questions.
- A source title/passage remains active for the whole local question group. Do not put
  it only on the first question. Questions containing words like "данного", "этого",
  "источнику", "карте", "портрете", "съезда", "изображен" usually need the active
  source context/media repeated.
- Do not attach unrelated earlier context to a standalone question.
- media must contain only filenames like image_001.jpg that appear in [IMAGE ...] blocks.
- Keep question <= 300 characters, each option <= 100, explanation <= 200.
- If something is ambiguous, still produce the best item and add a short issue string.
"""


def build_user_prompt(blocks: list[Block], core_start: int, core_end: int) -> str:
    lines = "\n".join(block_line(block) for block in blocks)
    return (
        f"CORE block range: B{core_start:04d}..B{core_end:04d}.\n"
        "Return only questions whose first A) option block is inside this CORE range.\n\n"
        "Extracted DOCX blocks:\n"
        f"{lines}"
    )


def parse_response(output_text: str) -> ChunkOutput:
    return ChunkOutput(**json.loads(output_text))


def call_chunk(
    client: OpenAI,
    model: str,
    blocks: list[Block],
    core_start: int,
    core_end: int,
    retries: int,
) -> ChunkOutput:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(blocks, core_start, core_end)},
                ],
                text={"format": build_schema()},
            )
            return parse_response(response.output_text)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"OpenAI chunk failed after {retries} attempts: {last_error}") from last_error


def chunk_ranges(total_blocks: int, core_size: int, context_before: int) -> list[tuple[int, int, int, int]]:
    ranges: list[tuple[int, int, int, int]] = []
    core_start = 1
    while core_start <= total_blocks:
        core_end = min(total_blocks, core_start + core_size - 1)
        include_start = max(1, core_start - context_before)
        include_end = core_end
        ranges.append((include_start, include_end, core_start, core_end))
        core_start = core_end + 1
    return ranges


def is_a_option_block(block: Block | None) -> bool:
    if block is None:
        return False
    return bool(re.search(r"(^|\s)(?:A|\u0410)\)", block.text))


def corrected_option_start(item: ParsedQuestion, block_by_id: dict[int, Block]) -> int | None:
    if is_a_option_block(block_by_id.get(item.option_start_block)):
        return item.option_start_block

    forward_end = item.source_end_block + 8
    for block_id in range(item.option_start_block, forward_end + 1):
        if is_a_option_block(block_by_id.get(block_id)):
            return block_id

    backward_start = max(1, item.option_start_block - 5)
    for block_id in range(item.option_start_block, backward_start - 1, -1):
        if is_a_option_block(block_by_id.get(block_id)):
            return block_id

    return None


def to_quiz_item(item: ParsedQuestion, media_prefix: str, item_id: int) -> dict[str, Any]:
    options = [clean(option) for option in item.options]
    correct_answer = options[item.correct - 1]
    context_parts = [clean(re.sub(r"\[IMAGE\s+[^\]]+\]", "", item.context))]
    context = "\n".join(part for part in context_parts if part)
    return {
        "id": item_id,
        "source_item_id": item.option_start_block,
        "context_title": clean(item.context_title),
        "context": context,
        "media": [f"{media_prefix}/{filename}" for filename in item.media],
        "question": clean(item.question),
        "options": options,
        "correct": item.correct,
        "correct_answer": correct_answer,
        "correct_answers": [correct_answer],
        "explanation": clean(item.explanation),
        "type": "ai_docx_quiz",
        "source": "ai_docx",
        "issues": list(item.issues),
    }


REFERENTIAL_CONTEXT_WORDS = (
    "данн",
    "этого",
    "этому",
    "этой",
    "источник",
    "источнику",
    "карте",
    "карта",
    "портрет",
    "изображ",
    "съезд",
    "обвед",
    "номер",
    "опис",
)


def title_tokens(title: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-zА-Яа-яЁёІіӘәҒғҚқҢңӨөҰұҮүҺһ]+", title)
        if len(token) >= 5
    }


def should_inherit_context(item: ParsedQuestion, active_title: str) -> bool:
    question = item.question.casefold()
    if any(word in question for word in REFERENTIAL_CONTEXT_WORDS):
        return True
    tokens = title_tokens(active_title)
    return bool(tokens and any(token in question for token in tokens))


def propagate_context(items: list[ParsedQuestion]) -> list[ParsedQuestion]:
    active_title = ""
    active_context = ""
    active_media: list[str] = []
    output: list[ParsedQuestion] = []
    for item in items:
        has_context = bool(item.context_title or item.context or item.media)
        if has_context:
            active_title = item.context_title
            active_context = item.context
            active_media = list(item.media)
        elif (active_title or active_context or active_media) and should_inherit_context(item, active_title):
            item = item.model_copy(
                update={
                    "context_title": active_title,
                    "context": active_context,
                    "media": list(active_media),
                    "issues": [*item.issues, "context_inherited_by_postprocess"],
                }
            )
        output.append(item)
    return output


def disambiguate_duplicate_questions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    counts: dict[str, int] = {}
    for item in items:
        base = clean(item["question"])
        key = base.casefold()
        counts[key] = counts.get(key, 0) + 1
        if key in seen:
            suffix = f" (контекст {counts[key]})"
            trimmed = base[: 300 - len(suffix)].rstrip()
            item["question"] = f"{trimmed}{suffix}"
            key = item["question"].casefold()
        seen.add(key)
    return items


def split_three(items: list[dict[str, Any]], max_per_file: int) -> list[list[dict[str, Any]]]:
    if len(items) > max_per_file * 3:
        raise ValueError(f"{len(items)} items do not fit into 3 files of {max_per_file}")
    first = min(max_per_file, (len(items) + 2) // 3)
    second = min(max_per_file, (len(items) - first + 1) // 2)
    return [items[:first], items[first:first + second], items[first + second:]]


def validate_media(items: list[dict[str, Any]], project_root: Path) -> list[str]:
    missing: list[str] = []
    for item in items:
        for media in item.get("media", []):
            if not (project_root / media).exists():
                missing.append(media)
    return missing


def write_outputs(
    items: list[dict[str, Any]],
    review: list[dict[str, Any]],
    output_dir: Path,
    prefix: str,
    max_per_file: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parts = split_three(items, max_per_file)
    written: list[dict[str, Any]] = []
    for index, part in enumerate(parts, start=1):
        disambiguate_duplicate_questions(part)
        payload = {
            "quiz_title": f"{prefix} AI part {index}",
            "quiz_description": "AI reparsed from DOCX, context and media preserved",
            "format_version": "ai-docx-1.0",
            "questions": part,
        }
        path = output_dir / f"{prefix}_ai_part_{index:02d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        questions, raw_items = load_questions_with_raw(path)
        validate_all(questions)
        report = build_quality_report(questions, raw_items)
        written.append(
            {
                "file": str(path.as_posix()),
                "questions": len(part),
                "warnings": len(report["warnings"]),
            }
        )

    review_path = output_dir / f"{prefix}_ai_review.json"
    review_path.write_text(json.dumps({"items": review}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"parts": written, "review_file": str(review_path.as_posix())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", required=True)
    parser.add_argument("--output-dir", default="quizzes")
    parser.add_argument("--media-dir", default="media/mne_nado_2_ai")
    parser.add_argument("--prefix", default="mne_nado_2")
    parser.add_argument("--model", default="")
    parser.add_argument("--core-size", type=int, default=240)
    parser.add_argument("--context-before", type=int, default=100)
    parser.add_argument("--max-chunks", type=int, default=0)
    parser.add_argument("--max-per-file", type=int, default=200)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--reuse-chunk-outputs", default="")
    args = parser.parse_args()

    load_dotenv("backend/.env")
    model = args.model or os.getenv("OPENAI_MODEL")
    if not model:
        print("OPENAI_MODEL is required", file=sys.stderr)
        return 1

    project_root = Path.cwd()
    media_dir = project_root / args.media_dir
    blocks = extract_blocks(Path(args.docx), media_dir)
    block_by_id = {block.block_id: block for block in blocks}
    ranges = chunk_ranges(len(blocks), args.core_size, args.context_before)
    if args.max_chunks:
        ranges = ranges[: args.max_chunks]

    parsed: dict[int, ParsedQuestion] = {}
    if args.reuse_chunk_outputs:
        raw_chunk_outputs = json.loads(Path(args.reuse_chunk_outputs).read_text(encoding="utf-8"))
    else:
        client = OpenAI()
        raw_chunk_outputs: list[dict[str, Any]] = []
        for chunk_index, (include_start, include_end, core_start, core_end) in enumerate(ranges, start=1):
            chunk_blocks = [block for block in blocks if include_start <= block.block_id <= include_end]
            print(
                f"Chunk {chunk_index}/{len(ranges)} include B{include_start:04d}-B{include_end:04d}, "
                f"core B{core_start:04d}-B{core_end:04d}",
                flush=True,
            )
            output = call_chunk(client, model, chunk_blocks, core_start, core_end, args.retries)
            raw_chunk_outputs.append(
                {
                    "chunk": chunk_index,
                    "core_start": core_start,
                    "core_end": core_end,
                    "questions": [item.model_dump() for item in output.questions],
                }
            )

    for chunk_output in raw_chunk_outputs:
        core_start = int(chunk_output["core_start"])
        core_end = int(chunk_output["core_end"])
        for item_data in chunk_output["questions"]:
            item = ParsedQuestion(**item_data)
            fixed_option_start = corrected_option_start(item, block_by_id)
            if (
                fixed_option_start is not None
                and core_start <= fixed_option_start <= core_end
            ):
                if fixed_option_start != item.option_start_block:
                    item = item.model_copy(update={"option_start_block": fixed_option_start})
                parsed[item.option_start_block] = item

    items: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    parsed_items = propagate_context([parsed[key] for key in sorted(parsed)])
    for item_id, parsed_item in enumerate(parsed_items, start=1):
        try:
            quiz_item = to_quiz_item(parsed_item, args.media_dir.replace("\\", "/"), item_id)
            Question(**quiz_item)
            items.append(quiz_item)
        except (ValidationError, ValueError, IndexError) as exc:
            review.append({"parsed": parsed_item.model_dump(), "error": str(exc)})

    missing_media = validate_media(items, project_root)
    if missing_media:
        review.append({"missing_media": missing_media})

    output_dir = project_root / args.output_dir
    result = write_outputs(items, review, output_dir, args.prefix, args.max_per_file)
    chunk_dump = output_dir / f"{args.prefix}_ai_chunk_outputs.json"
    chunk_dump.write_text(json.dumps(raw_chunk_outputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "docx": args.docx,
        "model": model,
        "blocks": len(blocks),
        "chunks": len(ranges),
        "parsed_questions": len(parsed),
        "valid_questions": len(items),
        "review_count": len(review),
        "missing_media_count": len(missing_media),
        "chunk_outputs": str(chunk_dump.as_posix()),
        **result,
    }
    summary_path = output_dir / f"{args.prefix}_ai_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
