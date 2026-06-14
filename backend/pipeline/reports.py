"""Report contracts for parser, encoding, and validation issues."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["info", "warning", "error"]


@dataclass(slots=True)
class ReportIssue:
    """User-facing issue with stable machine code and Russian action text."""

    code: str
    severity: Severity
    message_ru: str
    action_ru: str
    source_ref: dict[str, Any] = field(default_factory=dict)
    question_id: str | None = None
    context_scope_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EncodingReport:
    """Summary of text integrity issues detected while reading sources."""

    encoding_policy: str = "utf-8-no-bom/unicode-nfc"
    source_encoding: str = "docx-unicode"
    has_suspect_text: bool = False
    suspect_blocks: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    issues: list[ReportIssue] = field(default_factory=list)

    @classmethod
    def from_issues(
        cls,
        issues: list[ReportIssue],
        *,
        source_encoding: str = "docx-unicode",
    ) -> "EncodingReport":
        suspect_blocks: list[dict[str, Any]] = []
        for issue in issues:
            block_id = issue.source_ref.get("block_id")
            if block_id:
                suspect_blocks.append(
                    {
                        "block_id": block_id,
                        "code": issue.code,
                        "severity": issue.severity,
                    }
                )
        return cls(
            source_encoding=source_encoding,
            has_suspect_text=bool(issues),
            suspect_blocks=suspect_blocks,
            blocked=any(issue.severity == "error" for issue in issues),
            issues=issues,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [issue.to_dict() for issue in self.issues]
        return data