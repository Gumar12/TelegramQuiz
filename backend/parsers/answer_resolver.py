"""Resolve correct answer positions from answer lines and bold options."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Sequence
import unicodedata

from backend.parsers.option_labels import (
    SUPPORTED_LABELS,
    OptionLabelResolution,
    ambiguous_alphabet_issue,
    label_codepoint,
    normalize_label,
    resolve_option_labels,
    split_option_line,
)
from backend.pipeline.reports import ReportIssue

AnswerSource = Literal[
    "unknown",
    "answer_line",
    "bold_option",
    "both_match",
    "conflict",
]

_ANSWER_PREFIXES = frozenset({"ответ", "правильный ответ"})
_TOKEN_DELIMITERS = {",", ";", "/", "\\", "\n", "\t", "\r"}


@dataclass(slots=True)
class AnswerSignal:
    positions: list[int]
    source: Literal["answer_line", "bold_option"]
    issues: list[ReportIssue] = field(default_factory=list)
    raw_labels: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def mode(self) -> Literal["single", "multiple", "unknown"]:
        if len(self.positions) == 1:
            return "single"
        if len(self.positions) > 1:
            return "multiple"
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnswerResolution:
    answers: list[int]
    mode: Literal["single", "multiple", "unknown"]
    answer_source: AnswerSource
    issues: list[ReportIssue] = field(default_factory=list)
    answer_line_positions: list[int] = field(default_factory=list)
    bold_positions: list[int] = field(default_factory=list)
    raw_answer_labels: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_resolved(self) -> bool:
        return bool(self.answers) and not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [issue.to_dict() for issue in self.issues]
        return data


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


def answer_line_not_letter_issue(
    answer_line: str,
    *,
    source_ref: dict[str, Any] | None = None,
) -> ReportIssue:
    return _issue(
        "answer_line_not_letter",
        "error",
        "Строка ответа должна содержать только букву варианта.",
        "Замени текст ответа на букву правильного варианта, например Ответ: B.",
        source_ref=source_ref,
        metadata={"answer_line": answer_line},
    )


def answer_label_unknown_issue(
    raw_label: str,
    *,
    source_ref: dict[str, Any] | None = None,
) -> ReportIssue:
    return _issue(
        "answer_label_unknown",
        "error",
        "Буква ответа не совпала ни с одной меткой варианта.",
        "Исправь строку ответа или метки вариантов в документе.",
        source_ref=source_ref,
        metadata={"answer_raw_label": raw_label, "answer_codepoint": label_codepoint(raw_label)},
    )


def answer_missing_issue(
    *,
    source_ref: dict[str, Any] | None = None,
) -> ReportIssue:
    return _issue(
        "answer_missing",
        "error",
        "Не найден правильный ответ для вопроса.",
        "Выдели правильный вариант жирным или добавь строку Ответ: X.",
        source_ref=source_ref,
    )


def answer_conflict_issue(
    line_positions: Sequence[int],
    bold_positions: Sequence[int],
    *,
    source_ref: dict[str, Any] | None = None,
) -> ReportIssue:
    return _issue(
        "answer_bold_and_line_conflict",
        "error",
        "Жирный вариант ответа не совпадает со строкой ответа.",
        "Исправь жирное выделение или строку ответа в документе.",
        source_ref=source_ref,
        metadata={
            "answer_line_positions": list(line_positions),
            "bold_positions": list(bold_positions),
        },
    )


def _as_label_resolution(
    labels_or_resolution: Sequence[str] | OptionLabelResolution,
    *,
    source_ref: dict[str, Any] | None = None,
) -> OptionLabelResolution:
    if isinstance(labels_or_resolution, OptionLabelResolution):
        return labels_or_resolution
    return resolve_option_labels(labels_or_resolution, source_ref=source_ref)


def _extract_answer_payload(answer_line: str) -> str | None:
    line = unicodedata.normalize("NFC", str(answer_line)).strip()
    if not line:
        return None

    for marker in ("✅", "✔️", "✔"):
        line = line.removeprefix(marker).strip()

    separator_positions = [index for index in (line.find(":"), line.find("：")) if index >= 0]
    if not separator_positions:
        return line

    separator_index = min(separator_positions)
    prefix = " ".join(line[:separator_index].strip().casefold().split())
    if prefix not in _ANSWER_PREFIXES:
        return None
    return line[separator_index + 1 :].strip()


def _split_answer_tokens(payload: str) -> list[str] | None:
    normalized = unicodedata.normalize("NFC", payload).strip()
    if not normalized:
        return None
    for delimiter in _TOKEN_DELIMITERS:
        normalized = normalized.replace(delimiter, " ")
    tokens = [token.strip() for token in normalized.split() if token.strip()]
    if not tokens:
        return None

    labels: list[str] = []
    for token in tokens:
        label = normalize_label(token)
        if len(label) != 1 or label not in SUPPORTED_LABELS:
            return None
        labels.append(label)
    return labels


def _dedupe_positions(values: Sequence[int]) -> list[int]:
    out: list[int] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def resolve_answer_line(
    answer_line: str,
    labels_or_resolution: Sequence[str] | OptionLabelResolution,
    *,
    source_ref: dict[str, Any] | None = None,
) -> AnswerSignal:
    label_resolution = _as_label_resolution(labels_or_resolution, source_ref=source_ref)
    issues = list(label_resolution.issues)
    payload = _extract_answer_payload(answer_line)
    if payload is None:
        return AnswerSignal(positions=[], source="answer_line", issues=issues)

    raw_labels = _split_answer_tokens(payload)
    if raw_labels is None:
        issues.append(answer_line_not_letter_issue(answer_line, source_ref=source_ref))
        return AnswerSignal(
            positions=[],
            source="answer_line",
            issues=issues,
            evidence={"answer_line": answer_line, "payload": payload},
        )

    positions: list[int] = []
    for raw_label in raw_labels:
        label = label_resolution.find_exact(raw_label)
        if label is not None:
            positions.append(label.position)
            continue
        if label_resolution.label_scheme == "mixed":
            issues.append(ambiguous_alphabet_issue(raw_label, label_resolution, source_ref=source_ref))
        else:
            issues.append(answer_label_unknown_issue(raw_label, source_ref=source_ref))

    return AnswerSignal(
        positions=_dedupe_positions(positions),
        source="answer_line",
        issues=issues,
        raw_labels=raw_labels,
        evidence={"answer_line": answer_line, "payload": payload},
    )


def _option_is_bold(option: Any) -> bool:
    if isinstance(option, bool):
        return option
    if isinstance(option, Mapping):
        return bool(
            option.get("bold")
            or option.get("is_bold")
            or option.get("has_bold")
            or option.get("bold_spans")
        )
    return bool(
        getattr(option, "bold", False)
        or getattr(option, "is_bold", False)
        or getattr(option, "has_bold", False)
        or getattr(option, "bold_spans", False)
    )


def resolve_bold_options(
    options: Sequence[Any] | None = None,
    *,
    bold_positions: Sequence[int] | None = None,
    source_ref: dict[str, Any] | None = None,
) -> AnswerSignal:
    if bold_positions is not None:
        positions = [int(position) for position in bold_positions if int(position) > 0]
    elif options is not None:
        positions = [
            index
            for index, option in enumerate(options, start=1)
            if _option_is_bold(option)
        ]
    else:
        positions = []

    return AnswerSignal(
        positions=_dedupe_positions(positions),
        source="bold_option",
        evidence={"source_ref": source_ref or {}},
    )


def _labels_from_options(options: Sequence[Any]) -> list[str]:
    labels: list[str] = []
    for option in options:
        if isinstance(option, str):
            option_line = split_option_line(option)
            if option_line is not None:
                labels.append(option_line.raw_label)
            continue
        if isinstance(option, Mapping):
            raw_label = option.get("raw_label") or option.get("label")
        else:
            raw_label = getattr(option, "raw_label", None) or getattr(option, "label", None)
        if raw_label is not None:
            labels.append(str(raw_label))
    return labels


def resolve_answer_sources(
    labels_or_resolution: Sequence[str] | OptionLabelResolution | None = None,
    answer_line: str | None = None,
    *,
    options: Sequence[Any] | None = None,
    bold_positions: Sequence[int] | None = None,
    source_ref: dict[str, Any] | None = None,
    require_answer: bool = True,
) -> AnswerResolution:
    if labels_or_resolution is None:
        if options is None:
            labels_or_resolution = []
        else:
            labels_or_resolution = _labels_from_options(options)

    label_resolution = _as_label_resolution(labels_or_resolution, source_ref=source_ref)
    issues = list(label_resolution.issues)
    line_signal: AnswerSignal | None = None
    bold_signal = resolve_bold_options(
        options,
        bold_positions=bold_positions,
        source_ref=source_ref,
    )

    if answer_line is not None:
        line_signal = resolve_answer_line(answer_line, label_resolution, source_ref=source_ref)
        issues.extend(issue for issue in line_signal.issues if issue not in issues)

    line_positions = line_signal.positions if line_signal is not None else []
    bold_answer_positions = bold_signal.positions

    if line_positions and bold_answer_positions:
        if line_positions == bold_answer_positions:
            return AnswerResolution(
                answers=line_positions,
                mode="multiple" if len(line_positions) > 1 else "single",
                answer_source="both_match",
                issues=issues,
                answer_line_positions=line_positions,
                bold_positions=bold_answer_positions,
                raw_answer_labels=line_signal.raw_labels if line_signal else [],
                metadata={"label_scheme": label_resolution.label_scheme},
            )

        issues.append(answer_conflict_issue(line_positions, bold_answer_positions, source_ref=source_ref))
        return AnswerResolution(
            answers=[],
            mode="unknown",
            answer_source="conflict",
            issues=issues,
            answer_line_positions=line_positions,
            bold_positions=bold_answer_positions,
            raw_answer_labels=line_signal.raw_labels if line_signal else [],
            metadata={"label_scheme": label_resolution.label_scheme},
        )

    if line_positions:
        return AnswerResolution(
            answers=line_positions,
            mode="multiple" if len(line_positions) > 1 else "single",
            answer_source="answer_line",
            issues=issues,
            answer_line_positions=line_positions,
            raw_answer_labels=line_signal.raw_labels if line_signal else [],
            metadata={"label_scheme": label_resolution.label_scheme},
        )

    if bold_answer_positions:
        return AnswerResolution(
            answers=bold_answer_positions,
            mode="multiple" if len(bold_answer_positions) > 1 else "single",
            answer_source="bold_option",
            issues=issues,
            bold_positions=bold_answer_positions,
            metadata={"label_scheme": label_resolution.label_scheme},
        )

    if require_answer and not any(issue.severity == "error" for issue in issues):
        issues.append(answer_missing_issue(source_ref=source_ref))

    return AnswerResolution(
        answers=[],
        mode="unknown",
        answer_source="unknown",
        issues=issues,
        answer_line_positions=line_positions,
        bold_positions=bold_answer_positions,
        raw_answer_labels=line_signal.raw_labels if line_signal else [],
        metadata={"label_scheme": label_resolution.label_scheme},
    )


resolve_answers = resolve_answer_sources
resolve_question_answers = resolve_answer_sources
resolve_answer = resolve_answer_sources
