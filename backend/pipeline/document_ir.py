"""Intermediate document representation used before quiz parsing."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import unicodedata
from typing import Any, Literal

BlockKind = Literal["paragraph", "heading", "list_item", "table_cell", "image", "break"]

_SPACE_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2007": " ",
        "\u202f": " ",
    }
)


def _normalize_for_hash(text: str) -> str:
    return unicodedata.normalize("NFC", str(text)).translate(_SPACE_TRANSLATION)


def stable_text_hash(text: str) -> str:
    normalized = _normalize_for_hash(text)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class BoldSpan:
    start: int
    end: int
    text: str
    source_ref: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.text = unicodedata.normalize("NFC", self.text).translate(_SPACE_TRANSLATION)
        if self.end < self.start:
            raise ValueError("bold span end must be >= start")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DocumentBlock:
    block_id: str
    kind: BlockKind
    text: str = ""
    text_hash: str = ""
    style: str = ""
    bold_spans: list[BoldSpan] = field(default_factory=list)
    blank_before: int = 0
    page_break_before: bool = False
    section_break_before: bool = False
    list_level: int | None = None
    media_refs: list[str] = field(default_factory=list)
    source_ref: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.text = _normalize_for_hash(self.text)
        if not self.text_hash:
            self.text_hash = stable_text_hash(self.text)
        if self.blank_before < 0:
            raise ValueError("blank_before must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bold_spans"] = [span.to_dict() for span in self.bold_spans]
        return data


@dataclass(slots=True)
class DocumentIR:
    source_id: str
    blocks: list[DocumentBlock] = field(default_factory=list)
    warnings: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "blocks": [block.to_dict() for block in self.blocks],
            "warnings": [
                warning.to_dict() if hasattr(warning, "to_dict") else warning
                for warning in self.warnings
            ],
        }