"""Build human-editable clean quiz JSON and parser audit artifacts."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping

from backend.parsers.docx_strict import StrictParseResult
from backend.pipeline.encoding import normalize_text, write_json_utf8
from backend.pipeline.reports import ReportIssue

DEFAULT_SETTINGS: dict[str, Any] = {
    "time_limit": "30 sec",
    "shuffle_options": True,
    "context_send_mode": "per-question",
}
_ALLOWED_SETTINGS = frozenset(DEFAULT_SETTINGS)
_CONTEXT_SEND_MODES = frozenset({"per-question", "once"})


@dataclass(slots=True)
class CleanQuizArtifacts:
    clean_json: dict[str, Any]
    audit_json: dict[str, Any]
    issues: list[ReportIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    def write(self, clean_path: str | Path, audit_path: str | Path) -> tuple[Path, Path]:
        return (
            write_json_utf8(clean_path, self.clean_json),
            write_json_utf8(audit_path, self.audit_json),
        )


def build_clean_quiz(
    parse_result: StrictParseResult,
    *,
    title: str | None = None,
    settings: Mapping[str, Any] | None = None,
) -> CleanQuizArtifacts:
    issues = list(parse_result.issues)
    clean_settings, setting_issues = _clean_settings(settings)
    issues.extend(setting_issues)

    clean_items: list[dict[str, Any]] = []
    question_refs: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    context_scopes: list[dict[str, Any]] = []
    source_question_index = 0

    for source_index, item in enumerate(parse_result.items, start=1):
        if item.type == "title":
            clean_items.append({"type": "title", "text": normalize_text(item.text)})
            sections.append(
                {
                    "source_item_index": source_index,
                    "title": normalize_text(item.text),
                    "source_ref": item.source_ref,
                }
            )
            continue
        if item.type == "context":
            clean_item: dict[str, Any] = {"type": "context"}
            if item.text:
                clean_item["text"] = normalize_text(item.text)
            if item.media:
                clean_item["media"] = list(item.media)
            clean_items.append(clean_item)
            context_scopes.append(
                {
                    "source_item_index": source_index,
                    "context_id": item.context_id,
                    "text_preview": normalize_text(item.text)[:160],
                    "media": list(item.media),
                    "section_title": item.section_title,
                    "source_ref": item.source_ref,
                }
            )
            continue
        if item.type == "reset_context":
            clean_items.append({"type": "reset_context"})
            continue
        if item.type == "question":
            source_question_index += 1
            clean_question: dict[str, Any] = {
                "type": "question",
                "question": normalize_text(item.question),
                "options": [{"text": normalize_text(option.text)} for option in item.options],
                "answers": list(item.answers),
                "mode": item.mode,
            }
            if item.explanation:
                clean_question["explanation"] = normalize_text(item.explanation)
            clean_items.append(clean_question)
            question_refs.append(
                {
                    "source_question_index": source_question_index,
                    "clean_item_index": len(clean_items),
                    "question": normalize_text(item.question),
                    "answers": list(item.answers),
                    "mode": item.mode,
                    "answer_source": "strict_marker",
                    "section_title": item.section_title,
                    "context_id": item.context_id,
                    "source_ref": item.source_ref,
                    "option_refs": [
                        {
                            "position": position,
                            "correct": option.correct,
                            "source_ref": option.source_ref,
                        }
                        for position, option in enumerate(item.options, start=1)
                    ],
                }
            )
            continue
        issues.append(
            _issue(
                "clean_unknown_item_type",
                "error",
                "Clean adapter получил неизвестный тип item.",
                "Исправь strict parser или источник prepared.md.",
                source_ref=item.source_ref,
                metadata={"type": item.type},
            )
        )

    clean_json = {
        "title": normalize_text(title or _default_title(parse_result.source_id)),
        "settings": clean_settings,
        "items": clean_items,
    }
    audit_json = {
        "source_id": parse_result.source_id,
        "parser_strategy": "docx-strict-template",
        "item_count": len(clean_items),
        "question_count": source_question_index,
        "sections": sections,
        "context_scopes": context_scopes,
        "question_refs": question_refs,
        "parse_report": {
            "error_count": sum(1 for issue in issues if issue.severity == "error"),
            "warning_count": sum(1 for issue in issues if issue.severity == "warning"),
            "issues": [issue.to_dict() for issue in issues],
        },
    }
    return CleanQuizArtifacts(clean_json=clean_json, audit_json=audit_json, issues=issues)


def _default_title(source_id: str) -> str:
    stem = Path(source_id).stem.strip()
    return stem or "Новый квиз"


def _clean_settings(settings: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[ReportIssue]]:
    clean = dict(DEFAULT_SETTINGS)
    issues: list[ReportIssue] = []
    if settings is None:
        return clean, issues

    for key, value in settings.items():
        if key not in _ALLOWED_SETTINGS:
            issues.append(
                _issue(
                    "settings_unknown_key",
                    "warning",
                    f"Настройка {key} не поддерживается clean JSON adapter.",
                    "Убери поле или добавь backend feature через allowlist.",
                    metadata={"key": key},
                )
            )
            continue
        clean[key] = value

    if clean["context_send_mode"] not in _CONTEXT_SEND_MODES:
        issues.append(
            _issue(
                "settings_context_send_mode_invalid",
                "error",
                "context_send_mode должен быть per-question или once.",
                "Исправь settings.context_send_mode в JSON.",
                metadata={"value": clean["context_send_mode"]},
            )
        )
    if not isinstance(clean["shuffle_options"], bool):
        issues.append(
            _issue(
                "settings_shuffle_options_invalid",
                "error",
                "shuffle_options должен быть boolean.",
                "Исправь settings.shuffle_options на true или false.",
                metadata={"value": clean["shuffle_options"]},
            )
        )
    return clean, issues


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