"""Server-owned option label schemes for DOCX quiz parsing."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence
import unicodedata

from backend.pipeline.reports import ReportIssue

LabelScript = Literal["latin", "cyrillic", "unknown"]
LabelScheme = Literal["latin_abcd", "cyrillic_abvg", "mixed", "unknown"]

LATIN_ABCD = ("A", "B", "C", "D")
CYRILLIC_ABVG = ("А", "Б", "В", "Г")
SUPPORTED_LABELS = frozenset(LATIN_ABCD + CYRILLIC_ABVG)


@dataclass(slots=True)
class OptionLabel:
    """A raw option label plus stable metadata for audit/report output."""

    raw_label: str
    position: int
    script: LabelScript
    codepoint: str
    unicode_name: str
    scheme: LabelScheme
    scheme_position: int | None = None
    source_ref: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_position(self) -> int:
        return self.position

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["canonical_position"] = self.canonical_position
        return data


@dataclass(slots=True)
class OptionLine:
    raw_label: str
    text: str
    source_line: str


@dataclass(slots=True)
class OptionLabelResolution:
    labels: list[OptionLabel]
    label_scheme: LabelScheme
    issues: list[ReportIssue] = field(default_factory=list)

    @property
    def scheme(self) -> LabelScheme:
        return self.label_scheme

    def to_dict(self) -> dict[str, Any]:
        return {
            "label_scheme": self.label_scheme,
            "labels": [label.to_dict() for label in self.labels],
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def find_exact(self, raw_label: str) -> OptionLabel | None:
        normalized = normalize_label(raw_label)
        matches = [label for label in self.labels if normalize_label(label.raw_label) == normalized]
        if len(matches) == 1:
            return matches[0]
        return None


def normalize_label(raw_label: str) -> str:
    return unicodedata.normalize("NFC", str(raw_label)).strip().upper()


def label_script(raw_label: str) -> LabelScript:
    label = normalize_label(raw_label)
    if label in LATIN_ABCD:
        return "latin"
    if label in CYRILLIC_ABVG:
        return "cyrillic"
    return "unknown"


def label_codepoint(raw_label: str) -> str:
    label = normalize_label(raw_label)
    if len(label) != 1:
        return ""
    return f"U+{ord(label):04X}"


def label_unicode_name(raw_label: str) -> str:
    label = normalize_label(raw_label)
    if len(label) != 1:
        return ""
    return unicodedata.name(label, "")


def scheme_position(raw_label: str) -> int | None:
    label = normalize_label(raw_label)
    if label in LATIN_ABCD:
        return LATIN_ABCD.index(label) + 1
    if label in CYRILLIC_ABVG:
        return CYRILLIC_ABVG.index(label) + 1
    return None


def _label_scheme_for_scripts(scripts: set[LabelScript]) -> LabelScheme:
    known_scripts = {script for script in scripts if script != "unknown"}
    if known_scripts == {"latin"}:
        return "latin_abcd"
    if known_scripts == {"cyrillic"}:
        return "cyrillic_abvg"
    if len(known_scripts) > 1:
        return "mixed"
    return "unknown"


def _issue(
    code: str,
    severity: Literal["info", "warning", "error"],
    message_ru: str,
    action_ru: str,
    *,
    source_ref: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReportIssue:
    return ReportIssue(
        code=code,
        severity=severity,
        message_ru=message_ru,
        action_ru=action_ru,
        source_ref=source_ref or {},
        metadata=metadata or {},
    )


def mixed_scheme_issue(
    labels: Sequence[OptionLabel],
    *,
    source_ref: dict[str, Any] | None = None,
) -> ReportIssue:
    return _issue(
        "option_label_scheme_mixed",
        "warning",
        "В одном вопросе смешаны русские и английские буквы вариантов.",
        "Проверь варианты ответа и строку ответа для этого вопроса.",
        source_ref=source_ref,
        metadata={
            "labels": [
                {
                    "raw_label": label.raw_label,
                    "position": label.position,
                    "script": label.script,
                    "codepoint": label.codepoint,
                }
                for label in labels
            ]
        },
    )


def ambiguous_alphabet_issue(
    raw_label: str,
    resolution: OptionLabelResolution,
    *,
    source_ref: dict[str, Any] | None = None,
) -> ReportIssue:
    return _issue(
        "answer_label_ambiguous_alphabet",
        "error",
        "Буква ответа неоднозначна из-за смешения русского и английского алфавита.",
        "Исправь строку ответа или метки вариантов так, чтобы все были в одной схеме.",
        source_ref=source_ref,
        metadata={
            "answer_raw_label": raw_label,
            "answer_codepoint": label_codepoint(raw_label),
            "labels": [label.to_dict() for label in resolution.labels],
        },
    )


def resolve_option_labels(
    raw_labels: Sequence[str],
    *,
    source_ref: dict[str, Any] | None = None,
) -> OptionLabelResolution:
    labels: list[OptionLabel] = []
    for index, raw_label in enumerate(raw_labels, start=1):
        normalized = normalize_label(raw_label)
        script = label_script(normalized)
        scheme: LabelScheme
        if script == "latin":
            scheme = "latin_abcd"
        elif script == "cyrillic":
            scheme = "cyrillic_abvg"
        else:
            scheme = "unknown"
        labels.append(
            OptionLabel(
                raw_label=str(raw_label).strip(),
                position=index,
                script=script,
                codepoint=label_codepoint(normalized),
                unicode_name=label_unicode_name(normalized),
                scheme=scheme,
                scheme_position=scheme_position(normalized),
                source_ref={**(source_ref or {}), "option_position": index},
            )
        )

    label_scheme = _label_scheme_for_scripts({label.script for label in labels})
    issues: list[ReportIssue] = []
    if label_scheme == "mixed":
        issues.append(mixed_scheme_issue(labels, source_ref=source_ref))
    return OptionLabelResolution(labels=labels, label_scheme=label_scheme, issues=issues)


def split_option_line(line: str) -> OptionLine | None:
    """Split a fixed server-owned option prefix like ``A) text`` or ``А. text``."""

    source_line = str(line)
    stripped = unicodedata.normalize("NFC", source_line).strip()
    if len(stripped) < 3:
        return None

    raw_label = normalize_label(stripped[0])
    if raw_label not in SUPPORTED_LABELS:
        return None

    delimiter = stripped[1]
    if delimiter not in {")", "."}:
        return None
    if delimiter == "." and len(stripped) > 2 and not stripped[2].isspace():
        return None

    text = stripped[2:].strip()
    if not text:
        return None
    return OptionLine(raw_label=raw_label, text=text, source_line=source_line)


def resolve_option_lines(
    lines: Sequence[str],
    *,
    source_ref: dict[str, Any] | None = None,
) -> tuple[list[OptionLine], OptionLabelResolution]:
    option_lines: list[OptionLine] = []
    for line in lines:
        option_line = split_option_line(line)
        if option_line is not None:
            option_lines.append(option_line)
    return option_lines, resolve_option_labels(
        [option.raw_label for option in option_lines],
        source_ref=source_ref,
    )


resolve_labels = resolve_option_labels
