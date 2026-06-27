"""Build final quiz JSON from DeepSeek block markup and source blocks."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Suffix allowlist mirrors backend.studio_api.MEDIA_SUFFIXES — media is only
# ever copied/served when its extension is one of these image types.
MEDIA_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}

BLOCK_HEADER_RE = re.compile(r"^\[BLOCK\s+(?P<id>[^\s|]+)\s*\|(?P<meta>.*)\]\s*$")
IMAGE_HEADER_RE = re.compile(r"^\[IMAGE\s+(?P<id>[^\s|]+)\s*\|(?P<meta>.*)\]\s*$")
OPTION_PREFIX_RE = re.compile(r"^\s*([A-ZА-Я])[\).]\s*(.+)$", re.I)
CONTEXT_OVERLAP_AUTOFIX_WARNING = (
    "Автоисправление: DeepSeek пометил контекст как вопрос. "
    "Проверьте, нужен ли контекст или фото."
)

MISSING_SOURCE_BLOCKS_WARNING = (
    "Возможно, ИИ что-то придумал — ссылка на отсутствующий блок источника"
)


@dataclass(slots=True)
class SourceBlock:
    block_id: str
    kind: str
    text: str = ""
    media_refs: list[str] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SourceBlocks:
    document_id: str = ""
    blocks: dict[str, SourceBlock] = field(default_factory=dict)
    images: dict[str, SourceBlock] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", str(text).replace("\xa0", " ")).strip()


def _parse_meta(raw: str) -> tuple[str, dict[str, str]]:
    parts = [part.strip() for part in raw.split("|")]
    kind = parts[0] if parts and parts[0] else "paragraph"
    meta: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        meta[key.strip()] = value.strip()
    return kind, meta


def _finalize_text_block(
    source: SourceBlocks,
    current_id: str | None,
    current_kind: str,
    current_meta: dict[str, str],
    current_lines: list[str],
) -> None:
    if current_id is None:
        return
    text = "\n".join(line.rstrip() for line in current_lines).strip()
    source.blocks[current_id] = SourceBlock(
        block_id=current_id,
        kind=current_kind,
        text=text,
        meta=dict(current_meta),
    )
    if current_id not in source.order:
        source.order.append(current_id)


def parse_blocks_markdown(text: str, *, media_base_dir: str | Path | None = None) -> SourceBlocks:
    """Parse the DOCX_BLOCK_STREAM markdown sent to DeepSeek."""
    source = SourceBlocks()
    base_dir = Path(media_base_dir) if media_base_dir is not None else None
    current_id: str | None = None
    current_kind = "paragraph"
    current_meta: dict[str, str] = {}
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("document_id:"):
            source.document_id = line.split(":", 1)[1].strip()
            continue

        block_match = BLOCK_HEADER_RE.match(line)
        if block_match:
            _finalize_text_block(source, current_id, current_kind, current_meta, current_lines)
            current_id = block_match.group("id")
            current_kind, current_meta = _parse_meta(block_match.group("meta"))
            current_lines = []
            continue

        image_match = IMAGE_HEADER_RE.match(line)
        if image_match:
            _finalize_text_block(source, current_id, current_kind, current_meta, current_lines)
            current_id = None
            current_lines = []
            image_id = image_match.group("id")
            image_kind, image_meta = _parse_meta(image_match.group("meta"))
            filename = image_meta.get("filename", "")
            media_ref = str((base_dir / filename).as_posix()) if base_dir is not None and filename else filename
            source.images[image_id] = SourceBlock(
                block_id=image_id,
                kind=image_kind or "image",
                media_refs=[media_ref] if media_ref else [],
                meta=image_meta,
            )
            if image_id not in source.order:
                source.order.append(image_id)
            continue

        if current_id is not None:
            current_lines.append(line)

    _finalize_text_block(source, current_id, current_kind, current_meta, current_lines)
    return source


def source_blocks_from_payload(payload: dict[str, Any]) -> SourceBlocks:
    source = SourceBlocks(document_id=str(payload.get("document_id") or payload.get("source_id") or ""))
    raw_blocks = payload.get("blocks") or payload.get("source_blocks") or []
    if isinstance(raw_blocks, dict):
        for block_id, value in raw_blocks.items():
            source.blocks[str(block_id)] = SourceBlock(
                block_id=str(block_id),
                kind="paragraph",
                text=str(value),
            )
            source.order.append(str(block_id))
        return source
    if not isinstance(raw_blocks, list):
        return source

    for index, block in enumerate(raw_blocks, start=1):
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("id") or block.get("block_id") or f"b{index:04d}")
        kind = str(block.get("kind") or block.get("type") or "paragraph")
        media_refs = block.get("media_refs") or block.get("media") or []
        media = [str(value) for value in media_refs] if isinstance(media_refs, list) else []
        source_block = SourceBlock(
            block_id=block_id,
            kind=kind,
            text=str(block.get("text") or block.get("text_md") or block.get("content") or ""),
            media_refs=media,
            meta={key: str(value) for key, value in block.items() if isinstance(key, str)},
        )
        if kind == "image" or block_id.startswith("img"):
            source.images[block_id] = source_block
        else:
            source.blocks[block_id] = source_block
        source.order.append(block_id)
    return source


def _candidate_ids(block_id: str) -> list[str]:
    raw = str(block_id)
    candidates = [raw]
    match = re.match(r"^b0*(\d+)$", raw)
    if match:
        number = int(match.group(1))
        candidates.extend([f"p-{number:04d}", f"p{number:04d}", str(number)])
    match = re.match(r"^p-?0*(\d+)$", raw)
    if match:
        number = int(match.group(1))
        candidates.extend([f"b{number:04d}", f"p-{number:04d}"])
    match = re.match(r"^img-?0*(\d+)$", raw)
    if match:
        number = int(match.group(1))
        candidates.extend([f"img{number:04d}", f"img-{number:04d}"])
    return list(dict.fromkeys(candidates))


def _get_block(source: SourceBlocks, block_id: str) -> SourceBlock | None:
    for candidate in _candidate_ids(block_id):
        if candidate in source.blocks:
            return source.blocks[candidate]
        if candidate in source.images:
            return source.images[candidate]
    return None


def _resolve_existing_id(source: SourceBlocks, block_id: str) -> str | None:
    for candidate in _candidate_ids(block_id):
        if candidate in source.blocks or candidate in source.images:
            return candidate
    return None


def _validate_known_ids(source: SourceBlocks, raw_ids: Any) -> tuple[list[str], list[str]]:
    """Split LLM-supplied ids into ones present in the known extracted set and unknowns.

    The known ids are exactly the block/image ids parsed from the DOCX stream
    (``source.blocks`` / ``source.images``). LLM-named ids are advisory: an id is
    accepted only if it resolves to a real extracted id (allowlist by id), never
    because the model named it. Malformed (non-list) input yields no known ids.
    """

    if not isinstance(raw_ids, list):
        return [], []
    known: list[str] = []
    unknown: list[str] = []
    for raw_id in raw_ids:
        block_id = str(raw_id)
        if _resolve_existing_id(source, block_id) is not None:
            known.append(block_id)
        else:
            unknown.append(block_id)
    return known, unknown


def _block_position(source: SourceBlocks, block_id: str) -> int | None:
    resolved = _resolve_existing_id(source, block_id)
    if resolved is None:
        return None
    try:
        return source.order.index(resolved)
    except ValueError:
        return None


def _texts_for_ids(source: SourceBlocks, block_ids: Any) -> tuple[list[str], list[str]]:
    if not isinstance(block_ids, list):
        return [], []
    texts: list[str] = []
    missing: list[str] = []
    for block_id in block_ids:
        source_block = _get_block(source, str(block_id))
        if source_block is None:
            missing.append(str(block_id))
            continue
        if source_block.text:
            texts.append(source_block.text)
    return texts, missing


def _infer_question_blocks_before_options(
    source: SourceBlocks,
    *,
    question_ids: Any,
    context_ids: Any,
    option_ids: Any,
) -> list[str]:
    if not isinstance(question_ids, list) or not isinstance(context_ids, list) or not isinstance(option_ids, list):
        return []
    if not question_ids or not option_ids:
        return []
    question_set = {str(value) for value in question_ids}
    context_set = {str(value) for value in context_ids}
    if not question_set.intersection(context_set):
        return []

    first_option_positions = [_block_position(source, str(value)) for value in option_ids]
    first_option_positions = [value for value in first_option_positions if value is not None]
    context_positions = [_block_position(source, str(value)) for value in context_ids]
    context_positions = [value for value in context_positions if value is not None]
    if not first_option_positions or not context_positions:
        return []

    start = max(context_positions) + 1
    end = min(first_option_positions)
    if start >= end:
        return []

    candidate_ids: list[str] = []
    for block_id in source.order[start:end]:
        block = source.blocks.get(block_id)
        if block is None or not block.text:
            continue
        candidate_ids.append(block_id)
    return candidate_ids[-1:] if candidate_ids else []


def _media_for_ids(
    source: SourceBlocks,
    media_ids: Any,
    *,
    media_output_dir: str | Path | None = None,
    media_prefix: str = "media",
    copy_cache: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    if not isinstance(media_ids, list):
        return [], []
    output_dir = Path(media_output_dir) if media_output_dir is not None else None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    media: list[str] = []
    missing: list[str] = []
    cache = copy_cache if copy_cache is not None else {}
    for media_id in media_ids:
        source_block = _get_block(source, str(media_id))
        if source_block is None or not source_block.media_refs:
            missing.append(str(media_id))
            continue
        for media_ref in source_block.media_refs:
            normalized_ref = _normalize_media_ref(
                media_ref,
                output_dir=output_dir,
                media_prefix=media_prefix,
                copy_cache=cache,
            )
            if normalized_ref:
                media.append(normalized_ref)
            else:
                missing.append(f"{media_id}:{media_ref}")
    return media, missing


def _normalize_media_ref(
    media_ref: str,
    *,
    output_dir: Path | None,
    media_prefix: str,
    copy_cache: dict[str, str],
) -> str | None:
    """Return a usable quiz media ref based on real files, not model output."""

    ref = str(media_ref).strip()
    if not ref:
        return None
    if re.match(r"^[a-z][a-z0-9+.-]*://", ref, re.I):
        return ref

    source_path = Path(ref)
    prefix = media_prefix.strip("/").replace("\\", "/") or "media"
    if output_dir is None:
        return ref if source_path.exists() else None

    existing_output_ref = _existing_output_media_ref(ref, output_dir=output_dir, media_prefix=prefix)
    if existing_output_ref:
        return existing_output_ref

    existing_source = _first_existing_media_source(ref, output_dir=output_dir, media_prefix=prefix)
    if existing_source is None:
        return None

    cache_key = str(existing_source.resolve())
    if cache_key not in copy_cache:
        target = output_dir / existing_source.name
        if existing_source.resolve() != target.resolve() and not target.exists():
            shutil.copyfile(existing_source, target)
        copy_cache[cache_key] = f"{prefix}/{target.name}"
    return copy_cache[cache_key]


def _existing_output_media_ref(media_ref: str, *, output_dir: Path, media_prefix: str) -> str | None:
    normalized = media_ref.replace("\\", "/").lstrip("/")
    candidates: list[tuple[Path, str]] = []
    if normalized == media_prefix:
        return None
    if normalized.startswith(f"{media_prefix}/"):
        rel = Path(normalized.split("/", 1)[1])
        candidates.append((output_dir / rel, f"{media_prefix}/{rel.as_posix()}"))
    filename = Path(normalized).name
    if filename:
        candidates.append((output_dir / filename, f"{media_prefix}/{filename}"))

    for candidate, ref in candidates:
        resolved = candidate.resolve()
        if not _is_relative_to(resolved, output_dir.resolve()):
            continue
        if resolved.suffix.lower() not in MEDIA_SUFFIXES:
            continue
        if resolved.exists() and resolved.is_file():
            return ref
    return None


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _trusted_media_roots(output_dir: Path) -> list[Path]:
    """Server-owned roots a media source is allowed to resolve inside.

    A media ref is only honoured when it lands in the media output dir or its
    parent workspace (where the DOCX media was extracted). Anything else — an
    absolute system path or a ``..`` escape — is rejected.
    """

    roots = [output_dir.resolve()]
    parent = output_dir.parent.resolve()
    if parent not in roots:
        roots.append(parent)
    return roots


def _contained_existing_file(candidate: Path, roots: list[Path]) -> Path | None:
    resolved = candidate.resolve()
    if not any(_is_relative_to(resolved, root) for root in roots):
        return None
    if resolved.suffix.lower() not in MEDIA_SUFFIXES:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _first_existing_media_source(media_ref: str, *, output_dir: Path, media_prefix: str) -> Path | None:
    raw_path = Path(media_ref)
    normalized = str(media_ref).replace("\\", "/").lstrip("/")
    roots = _trusted_media_roots(output_dir)
    candidates: list[Path] = []
    # An absolute media ref is honoured only if it already points inside a
    # trusted root; otherwise it is a path-traversal / arbitrary-read attempt.
    if raw_path.is_absolute():
        candidates.append(raw_path)
    if normalized.startswith(f"{media_prefix}/"):
        candidates.append(output_dir / normalized.split("/", 1)[1])
    if raw_path.name:
        candidates.append(output_dir / raw_path.name)
    if not raw_path.is_absolute():
        candidates.append(output_dir.parent / raw_path)

    for candidate in candidates:
        contained = _contained_existing_file(candidate, roots)
        if contained is not None:
            return contained
    return None


def _strip_option_label(text: str) -> str:
    match = OPTION_PREFIX_RE.match(text)
    if match:
        return _clean(match.group(2))
    return _clean(text)


def _context_regions(payload: dict[str, Any], source: SourceBlocks) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    regions = payload.get("context_regions", [])
    if not isinstance(regions, list):
        return result

    for region in regions:
        if not isinstance(region, dict):
            continue
        texts, missing_blocks = _texts_for_ids(source, region.get("block_ids"))
        applies_to = region.get("applies_to_question_ids", [])
        if not isinstance(applies_to, list):
            continue
        for question_id in applies_to:
            result[str(question_id)] = {
                "text": "\n".join(texts).strip(),
                "media_ids": list(region.get("media_ids", [])) if isinstance(region.get("media_ids"), list) else [],
                "missing_blocks": missing_blocks,
            }
    return result


def build_quiz_from_markup(
    markup: dict[str, Any],
    source: SourceBlocks,
    *,
    title: str = "",
    description: str = "Собрано из DeepSeek-разметки",
    media_output_dir: str | Path | None = None,
    media_prefix: str = "media",
) -> dict[str, Any]:
    questions = markup.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("DeepSeek markup must contain questions list")

    region_by_question = _context_regions(markup, source)
    media_copy_cache: dict[str, str] = {}
    output_questions: list[dict[str, Any]] = []
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("id") or index)
        quality_flags = [str(flag) for flag in item.get("warnings", []) if isinstance(flag, str)]

        question_block_ids = item.get("question_block_ids")
        inferred_question_ids = _infer_question_blocks_before_options(
            source,
            question_ids=question_block_ids,
            context_ids=item.get("context_block_ids"),
            option_ids=item.get("option_block_ids"),
        )
        question_texts, missing_question_blocks = _texts_for_ids(
            source,
            inferred_question_ids or question_block_ids,
        )
        option_texts, missing_option_blocks = _texts_for_ids(source, item.get("option_block_ids"))
        context_texts, missing_context_blocks = _texts_for_ids(source, item.get("context_block_ids"))
        options = [_strip_option_label(text) for text in option_texts]

        option_ids = item.get("option_block_ids", [])
        known_correct_ids, unknown_correct_ids = _validate_known_ids(
            source, item.get("correct_option_block_ids")
        )
        correct_ids = set(known_correct_ids)
        correct_values = [
            option_index
            for option_index, option_id in enumerate(option_ids if isinstance(option_ids, list) else [], start=1)
            if str(option_id) in correct_ids
        ]

        region = region_by_question.get(question_id, {})
        context = "\n".join(context_texts).strip() or str(region.get("text", ""))
        media_ids = list(item.get("media_ids", [])) if isinstance(item.get("media_ids"), list) else []
        for media_id in region.get("media_ids", []):
            if media_id not in media_ids:
                media_ids.append(media_id)
        media, missing_media = _media_for_ids(
            source,
            media_ids,
            media_output_dir=media_output_dir,
            media_prefix=media_prefix,
            copy_cache=media_copy_cache,
        )

        missing = (
            missing_question_blocks
            + missing_option_blocks
            + missing_context_blocks
            + list(region.get("missing_blocks", []))
            + missing_media
            + unknown_correct_ids
        )
        if missing:
            quality_flags.append(MISSING_SOURCE_BLOCKS_WARNING + ": " + ", ".join(dict.fromkeys(missing)))
        if inferred_question_ids:
            quality_flags.append(CONTEXT_OVERLAP_AUTOFIX_WARNING)
        if len("\n".join(question_texts).strip()) > 255:
            quality_flags.append("Вопрос длиннее лимита Telegram 255 символов.")
        if len(options) < 3:
            quality_flags.append("Меньше 3 вариантов ответа.")
        for option_index, option in enumerate(options, start=1):
            if len(option) > 100:
                quality_flags.append(f"Вариант {option_index} длиннее лимита Telegram 100 символов.")
        if not correct_values:
            quality_flags.append("Парсер не нашёл правильный ответ.")
        if context and context.strip() == "\n".join(question_texts).strip():
            context = ""

        output_questions.append(
            {
                "source_item_id": question_id,
                "question": "\n".join(question_texts).strip(),
                "options": options,
                "correct": correct_values[0] if len(correct_values) == 1 else correct_values or 1,
                "explanation": "",
                "context": context,
                "media": media,
                "source": "deepseek_markup",
                "quality_flags": list(dict.fromkeys(quality_flags)),
                "deepseek_confidence": item.get("confidence"),
            }
        )

    if not output_questions:
        raise ValueError("No questions found in DeepSeek markup")

    return {
        "quiz_title": title or str(markup.get("document_id") or source.document_id or "DeepSeek import"),
        "quiz_description": description,
        "allow_duplicate_questions": bool(markup.get("allow_duplicate_questions", False)),
        "format_version": "2.1-deepseek-builder",
        "questions": output_questions,
    }


def build_quiz_from_files(
    *,
    markup_path: str | Path,
    blocks_path: str | Path,
    title: str = "",
    description: str = "Собрано из DeepSeek-разметки",
    media_output_dir: str | Path | None = None,
    media_prefix: str = "media",
) -> dict[str, Any]:
    markup = json.loads(Path(markup_path).read_text(encoding="utf-8"))
    blocks_file = Path(blocks_path)
    if blocks_file.suffix.lower() == ".json":
        source = source_blocks_from_payload(json.loads(blocks_file.read_text(encoding="utf-8")))
    else:
        default_media_dir = blocks_file.with_suffix("").with_name(f"{blocks_file.stem.removesuffix('.blocks')}_media")
        media_base_dir = default_media_dir if default_media_dir.exists() else blocks_file.parent
        source = parse_blocks_markdown(blocks_file.read_text(encoding="utf-8"), media_base_dir=media_base_dir)
    return build_quiz_from_markup(
        markup,
        source,
        title=title,
        description=description,
        media_output_dir=media_output_dir,
        media_prefix=media_prefix,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build final QuizBot JSON from DeepSeek block markup.")
    parser.add_argument("--markup", required=True, type=Path, help="DeepSeek markup JSON")
    parser.add_argument("--blocks", required=True, type=Path, help="DOCX block stream markdown or JSON with blocks")
    parser.add_argument("--output", required=True, type=Path, help="Final quiz JSON output")
    parser.add_argument("--title", default="", help="Override quiz title")
    parser.add_argument("--description", default="Собрано из DeepSeek-разметки")
    parser.add_argument("--media-output-dir", type=Path, default=None, help="Copy referenced media here")
    parser.add_argument("--media-prefix", default="media", help="Path prefix written to quiz JSON for copied media")
    args = parser.parse_args()

    quiz = build_quiz_from_files(
        markup_path=args.markup,
        blocks_path=args.blocks,
        title=args.title,
        description=args.description,
        media_output_dir=args.media_output_dir,
        media_prefix=args.media_prefix,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(quiz, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
