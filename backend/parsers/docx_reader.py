"""Read DOCX files into the neutral DocumentIR contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn

from backend.pipeline.document_ir import BoldSpan, DocumentBlock, DocumentIR


@dataclass(slots=True)
class _PendingBoldSpan:
    start: int
    end: int
    text: str
    source_ref: dict[str, Any]


@dataclass(slots=True)
class _TextAccumulator:
    parts: list[str] = field(default_factory=list)
    bold_spans: list[_PendingBoldSpan] = field(default_factory=list)
    run_indexes: list[int] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def add_text(
        self,
        text: str,
        *,
        is_bold: bool,
        source_ref: dict[str, Any],
        run_index: int,
    ) -> None:
        if not text:
            return
        start = len(self.text)
        self.parts.append(text)
        self.run_indexes.append(run_index)
        end = len(self.text)
        if is_bold:
            self.bold_spans.append(
                _PendingBoldSpan(
                    start=start,
                    end=end,
                    text=text,
                    source_ref=dict(source_ref),
                )
            )

    def clear(self) -> None:
        self.parts.clear()
        self.bold_spans.clear()
        self.run_indexes.clear()


def read_docx_to_ir(path: str | Path, media_dir: str | Path | None = None) -> DocumentIR:
    """Return a DocumentIR preserving DOCX reading-order details.

    The reader is intentionally structural only: it does not identify questions,
    answers, options, or context scopes. Embedded images are written only when a
    caller supplies ``media_dir``.
    """

    source_path = Path(path)
    document = Document(source_path)
    media_root = Path(media_dir) if media_dir is not None else None
    if media_root is not None:
        media_root.mkdir(parents=True, exist_ok=True)

    blocks: list[DocumentBlock] = []
    counters = {"p": 0, "img": 0, "br": 0}
    image_counter = 0
    blank_before = 0
    pending_page_break = False
    pending_page_break_ref: dict[str, Any] | None = None
    pending_section_break = False
    pending_section_break_ref: dict[str, Any] | None = None

    def next_id(prefix: str) -> str:
        counters[prefix] += 1
        return f"{prefix}-{counters[prefix]:04d}"

    def base_ref(block_id: str, paragraph_index: int) -> dict[str, Any]:
        return {
            "source_file": source_path.as_posix(),
            "paragraph_index": paragraph_index,
            "block_id": block_id,
        }

    def add_pending_break_refs(source_ref: dict[str, Any]) -> None:
        if pending_page_break_ref is not None:
            source_ref["page_break_before_source"] = pending_page_break_ref
        if pending_section_break_ref is not None:
            source_ref["section_break_before_source"] = pending_section_break_ref

    def consume_pending_boundaries() -> tuple[int, bool, bool]:
        nonlocal blank_before, pending_page_break, pending_page_break_ref
        nonlocal pending_section_break, pending_section_break_ref
        current_blank_before = blank_before
        current_page_break = pending_page_break
        current_section_break = pending_section_break
        blank_before = 0
        pending_page_break = False
        pending_page_break_ref = None
        pending_section_break = False
        pending_section_break_ref = None
        return current_blank_before, current_page_break, current_section_break

    def flush_text_block(
        accumulator: _TextAccumulator,
        *,
        paragraph_index: int,
        style_name: str,
        is_heading: bool,
    ) -> bool:
        if not accumulator.text.strip():
            accumulator.clear()
            return False

        block_id = next_id("p")
        source_ref = base_ref(block_id, paragraph_index)
        if accumulator.run_indexes:
            source_ref["run_start_index"] = min(accumulator.run_indexes)
            source_ref["run_end_index"] = max(accumulator.run_indexes)
        add_pending_break_refs(source_ref)
        current_blank_before, current_page_break, current_section_break = consume_pending_boundaries()
        bold_spans = [
            BoldSpan(
                start=span.start,
                end=span.end,
                text=span.text,
                source_ref={**span.source_ref, "block_id": block_id},
            )
            for span in accumulator.bold_spans
        ]
        blocks.append(
            DocumentBlock(
                block_id=block_id,
                kind="heading" if is_heading else "paragraph",
                text=accumulator.text,
                style=style_name,
                bold_spans=bold_spans,
                blank_before=current_blank_before,
                page_break_before=current_page_break,
                section_break_before=current_section_break,
                source_ref=source_ref,
            )
        )
        accumulator.clear()
        return True

    def append_image_block(
        *,
        paragraph_index: int,
        run_index: int,
        content_index: int,
        relationship_id: str | None,
        media_ref: str | None,
        content_type: str | None,
    ) -> None:
        block_id = next_id("img")
        source_ref = base_ref(block_id, paragraph_index)
        source_ref.update(
            {
                "run_index": run_index,
                "content_index": content_index,
                "relationship_id": relationship_id,
            }
        )
        if content_type:
            source_ref["content_type"] = content_type
        add_pending_break_refs(source_ref)
        current_blank_before, current_page_break, current_section_break = consume_pending_boundaries()
        blocks.append(
            DocumentBlock(
                block_id=block_id,
                kind="image",
                media_refs=[media_ref] if media_ref else [],
                blank_before=current_blank_before,
                page_break_before=current_page_break,
                section_break_before=current_section_break,
                source_ref=source_ref,
            )
        )

    def append_trailing_break_block() -> None:
        if not (pending_page_break or pending_section_break):
            return
        block_id = next_id("br")
        source_ref = {
            "source_file": source_path.as_posix(),
            "block_id": block_id,
            "break_types": [],
        }
        if pending_page_break_ref is not None:
            source_ref["break_types"].append("page")
            source_ref["page_break_source"] = pending_page_break_ref
        if pending_section_break_ref is not None:
            source_ref["break_types"].append("section")
            source_ref["section_break_source"] = pending_section_break_ref
        current_blank_before, current_page_break, current_section_break = consume_pending_boundaries()
        blocks.append(
            DocumentBlock(
                block_id=block_id,
                kind="break",
                text="+".join(f"{kind}_break" for kind in source_ref["break_types"]),
                blank_before=current_blank_before,
                page_break_before=current_page_break,
                section_break_before=current_section_break,
                source_ref=source_ref,
            )
        )

    def extract_image_ref(r_id: str | None) -> tuple[str | None, str | None]:
        nonlocal image_counter
        if not r_id:
            return None, None
        image_part = document.part.related_parts.get(r_id)
        if image_part is None:
            return None, None
        content_type = getattr(image_part, "content_type", None)
        if media_root is None:
            return None, content_type

        image_counter += 1
        extension = _image_extension(image_part)
        output_path = media_root / f"image_{image_counter:03d}.{extension}"
        output_path.write_bytes(image_part.blob)
        return output_path.as_posix(), content_type

    for paragraph_index, paragraph in enumerate(document.paragraphs):
        style_name = (paragraph.style.name if paragraph.style is not None else "") or ""
        is_heading = _is_heading_style(style_name)
        accumulator = _TextAccumulator()
        paragraph_had_content = False
        paragraph_had_structural_break = False

        for run_index, run in enumerate(paragraph.runs):
            is_bold = _run_is_bold(run)
            for content_index, child in enumerate(run._element.iterchildren()):
                child_tag = child.tag
                child_ref = {
                    "source_file": source_path.as_posix(),
                    "paragraph_index": paragraph_index,
                    "run_index": run_index,
                    "content_index": content_index,
                }
                if child_tag == qn("w:t"):
                    accumulator.add_text(
                        child.text or "",
                        is_bold=is_bold,
                        source_ref=child_ref,
                        run_index=run_index,
                    )
                elif child_tag == qn("w:tab"):
                    accumulator.add_text(
                        "\t",
                        is_bold=is_bold,
                        source_ref=child_ref,
                        run_index=run_index,
                    )
                elif child_tag in {qn("w:cr"), qn("w:br")}:
                    if child_tag == qn("w:br") and child.get(qn("w:type")) == "page":
                        paragraph_had_content = (
                            flush_text_block(
                                accumulator,
                                paragraph_index=paragraph_index,
                                style_name=style_name,
                                is_heading=is_heading,
                            )
                            or paragraph_had_content
                        )
                        pending_page_break = True
                        pending_page_break_ref = {**child_ref, "break_kind": "page"}
                        paragraph_had_structural_break = True
                    else:
                        accumulator.add_text(
                            "\n",
                            is_bold=is_bold,
                            source_ref=child_ref,
                            run_index=run_index,
                        )
                elif child_tag == qn("w:lastRenderedPageBreak"):
                    # Word may persist automatic layout page breaks after editing.
                    # They are not author-controlled boundaries and must not split quiz blocks.
                    continue
                elif child_tag == qn("w:drawing"):
                    paragraph_had_content = (
                        flush_text_block(
                            accumulator,
                            paragraph_index=paragraph_index,
                            style_name=style_name,
                            is_heading=is_heading,
                        )
                        or paragraph_had_content
                    )
                    for r_id in _drawing_relationship_ids(child):
                        media_ref, content_type = extract_image_ref(r_id)
                        append_image_block(
                            paragraph_index=paragraph_index,
                            run_index=run_index,
                            content_index=content_index,
                            relationship_id=r_id,
                            media_ref=media_ref,
                            content_type=content_type,
                        )
                        paragraph_had_content = True

        paragraph_had_content = (
            flush_text_block(
                accumulator,
                paragraph_index=paragraph_index,
                style_name=style_name,
                is_heading=is_heading,
            )
            or paragraph_had_content
        )

        section_ref = _paragraph_section_break_ref(paragraph)
        if section_ref is not None:
            pending_section_break = True
            pending_section_break_ref = {
                "source_file": source_path.as_posix(),
                "paragraph_index": paragraph_index,
                **section_ref,
            }
            paragraph_had_structural_break = True

        if not paragraph_had_content and not paragraph_had_structural_break:
            blank_before += 1

    append_trailing_break_block()
    return DocumentIR(source_id=source_path.name, blocks=blocks)


def _run_is_bold(run: Any) -> bool:
    if run.bold is not None:
        return bool(run.bold)
    style = getattr(run, "style", None)
    font = getattr(style, "font", None)
    return bool(getattr(font, "bold", False))


def _is_heading_style(style_name: str) -> bool:
    normalized = style_name.strip().casefold()
    return normalized.startswith("heading") or normalized.startswith("заголовок")


def _drawing_relationship_ids(drawing: Any) -> list[str]:
    relationship_ids: list[str] = []
    for blip in drawing.xpath(".//a:blip"):
        r_id = blip.get(qn("r:embed"))
        if r_id and r_id not in relationship_ids:
            relationship_ids.append(r_id)
    return relationship_ids


def _image_extension(image_part: Any) -> str:
    partname = getattr(image_part, "partname", None)
    suffix = Path(str(partname)).suffix.lower().lstrip(".") if partname is not None else ""
    if suffix:
        return "jpg" if suffix == "jpeg" else suffix
    content_type = str(getattr(image_part, "content_type", "image/bin"))
    extension = content_type.rsplit("/", 1)[-1].lower()
    return "jpg" if extension == "jpeg" else extension


def _paragraph_section_break_ref(paragraph: Any) -> dict[str, Any] | None:
    p_pr = paragraph._p.pPr
    if p_pr is None or p_pr.sectPr is None:
        return None
    section_type = None
    section_type_elements = p_pr.sectPr.xpath("./w:type")
    if section_type_elements:
        section_type = section_type_elements[0].get(qn("w:val"))
    return {
        "break_kind": "section",
        "section_start_type": section_type,
    }
