"""Review decision artifact and upload gate resolver for validation reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from backend.pipeline.validation import ValidationIssue, ValidationReport

ReviewAction = Literal[
    "confirm",
    "send_both",
    "skip_question",
    "edit",
    "abort",
    "review_one_by_one",
]
GateStatus = Literal["allowed", "blocked", "review_required"]

ALLOWED_REVIEW_ACTIONS: frozenset[str] = frozenset(
    {"confirm", "send_both", "skip_question", "edit", "abort", "review_one_by_one"}
)


class ReviewDecisionError(ValueError):
    """Raised when untrusted review decision data does not match the contract."""


@dataclass(slots=True)
class ReviewDecision:
    issue_code: str
    source_question_index: int
    action: ReviewAction
    decided_at: str
    decided_by: str = "user"
    group_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "issue_code": self.issue_code,
            "source_question_index": self.source_question_index,
            "action": self.action,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
        }
        if self.group_id is not None:
            data["group_id"] = self.group_id
        if self.evidence:
            data["evidence"] = dict(self.evidence)
        return data


@dataclass(slots=True)
class GroupReviewDecision:
    group_id: str
    issue_code: str
    action: ReviewAction
    affected_question_indexes: list[int]
    decided_at: str
    decided_by: str = "user"
    expanded_decisions: list[ReviewDecision] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "issue_code": self.issue_code,
            "action": self.action,
            "affected_question_indexes": list(self.affected_question_indexes),
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "expanded_decisions": [decision.to_dict() for decision in self.expanded_decisions],
        }


@dataclass(slots=True)
class ReviewArtifact:
    quiz_file_hash: str
    decisions: list[ReviewDecision] = field(default_factory=list)
    groups: list[GroupReviewDecision] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _utc_now())
    schema_version: str = "review-decisions.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "quiz_file_hash": self.quiz_file_hash,
            "created_at": self.created_at,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "groups": [group.to_dict() for group in self.groups],
        }


@dataclass(slots=True)
class UploadGateResult:
    status: GateStatus
    reason: str
    unresolved_errors: list[ValidationIssue] = field(default_factory=list)
    unresolved_warnings: list[ValidationIssue] = field(default_factory=list)
    skipped_question_indexes: list[int] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "unresolved_errors": [issue.to_dict() for issue in self.unresolved_errors],
            "unresolved_warnings": [issue.to_dict() for issue in self.unresolved_warnings],
            "skipped_question_indexes": list(self.skipped_question_indexes),
        }


def validate_review_action(action: Any) -> ReviewAction:
    if not isinstance(action, str) or action not in ALLOWED_REVIEW_ACTIONS:
        raise ReviewDecisionError(f"Unknown review action: {action!r}")
    return action  # type: ignore[return-value]


def make_review_decision(
    *,
    issue_code: str,
    source_question_index: int,
    action: str,
    decided_at: str | None = None,
    decided_by: str = "user",
    group_id: str | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> ReviewDecision:
    if source_question_index < 1:
        raise ReviewDecisionError("source_question_index must be >= 1")
    return ReviewDecision(
        issue_code=_required_string(issue_code, "issue_code"),
        source_question_index=source_question_index,
        action=validate_review_action(action),
        decided_at=decided_at or _utc_now(),
        decided_by=_required_string(decided_by, "decided_by"),
        group_id=group_id,
        evidence=dict(evidence or {}),
    )


def expand_group_decision(
    *,
    group_id: str,
    issue_code: str,
    action: str,
    affected_question_indexes: list[int],
    decided_at: str | None = None,
    decided_by: str = "user",
) -> GroupReviewDecision:
    clean_action = validate_review_action(action)
    if not affected_question_indexes:
        raise ReviewDecisionError("affected_question_indexes must not be empty")
    if any(not isinstance(index, int) or isinstance(index, bool) or index < 1 for index in affected_question_indexes):
        raise ReviewDecisionError("affected_question_indexes must contain positive integers")
    timestamp = decided_at or _utc_now()
    expanded: list[ReviewDecision] = []
    if clean_action != "review_one_by_one":
        expanded = [
            make_review_decision(
                issue_code=issue_code,
                source_question_index=index,
                action=clean_action,
                decided_at=timestamp,
                decided_by=decided_by,
                group_id=group_id,
            )
            for index in affected_question_indexes
        ]
    return GroupReviewDecision(
        group_id=_required_string(group_id, "group_id"),
        issue_code=_required_string(issue_code, "issue_code"),
        action=clean_action,
        affected_question_indexes=list(affected_question_indexes),
        decided_at=timestamp,
        decided_by=_required_string(decided_by, "decided_by"),
        expanded_decisions=expanded,
    )


def build_review_artifact(
    *,
    quiz_file_hash: str,
    decisions: list[ReviewDecision] | None = None,
    groups: list[GroupReviewDecision] | None = None,
    created_at: str | None = None,
) -> ReviewArtifact:
    artifact_decisions = list(decisions or [])
    artifact_groups = list(groups or [])
    for group in artifact_groups:
        artifact_decisions.extend(group.expanded_decisions)
    return ReviewArtifact(
        quiz_file_hash=_required_string(quiz_file_hash, "quiz_file_hash"),
        decisions=artifact_decisions,
        groups=artifact_groups,
        created_at=created_at or _utc_now(),
    )


def parse_review_artifact(data: Mapping[str, Any]) -> ReviewArtifact:
    if not isinstance(data, Mapping):
        raise ReviewDecisionError("Review artifact must be an object")
    quiz_file_hash = _required_string(data.get("quiz_file_hash"), "quiz_file_hash")
    decisions_value = data.get("decisions", [])
    groups_value = data.get("groups", [])
    if not isinstance(decisions_value, list):
        raise ReviewDecisionError("decisions must be a list")
    if not isinstance(groups_value, list):
        raise ReviewDecisionError("groups must be a list")

    decisions = [_parse_decision(item) for item in decisions_value]
    groups = [_parse_group(item) for item in groups_value]
    return build_review_artifact(
        quiz_file_hash=quiz_file_hash,
        decisions=decisions,
        groups=groups,
        created_at=str(data.get("created_at") or _utc_now()),
    )


def resolve_upload_gate(
    validation_report: ValidationReport,
    review_artifact: ReviewArtifact | Mapping[str, Any] | None = None,
    *,
    quiz_file_hash: str | None = None,
) -> UploadGateResult:
    current_hash = quiz_file_hash or validation_report.quiz_file_hash
    artifact = _coerce_artifact(review_artifact)
    if artifact is not None and artifact.quiz_file_hash != current_hash:
        return UploadGateResult(
            status="review_required",
            reason="review_decisions_stale",
            unresolved_errors=validation_report.hard_errors,
            unresolved_warnings=validation_report.warnings,
        )

    decisions = _decision_index(artifact.decisions if artifact is not None else [])
    unresolved_errors: list[ValidationIssue] = []
    unresolved_warnings: list[ValidationIssue] = []
    skipped_questions: set[int] = set()

    for issue in validation_report.hard_errors:
        decision = _matching_decision(issue, decisions)
        if _resolves_hard_error(issue, decision):
            skipped_questions.add(decision.source_question_index)
            continue
        unresolved_errors.append(issue)

    for issue in validation_report.warnings:
        decision = _matching_decision(issue, decisions)
        if _resolves_warning(issue, decision):
            if decision is not None and decision.action == "skip_question":
                skipped_questions.add(decision.source_question_index)
            continue
        unresolved_warnings.append(issue)

    if unresolved_errors:
        return UploadGateResult(
            status="blocked",
            reason="hard_errors_unresolved",
            unresolved_errors=unresolved_errors,
            unresolved_warnings=unresolved_warnings,
            skipped_question_indexes=sorted(skipped_questions),
        )
    if unresolved_warnings:
        return UploadGateResult(
            status="review_required",
            reason="warnings_unresolved",
            unresolved_warnings=unresolved_warnings,
            skipped_question_indexes=sorted(skipped_questions),
        )
    return UploadGateResult(
        status="allowed",
        reason="validation_resolved",
        skipped_question_indexes=sorted(skipped_questions),
    )


def _parse_decision(data: Any) -> ReviewDecision:
    if not isinstance(data, Mapping):
        raise ReviewDecisionError("Each decision must be an object")
    source_question_index = data.get("source_question_index")
    if not isinstance(source_question_index, int) or isinstance(source_question_index, bool):
        raise ReviewDecisionError("source_question_index must be an integer")
    evidence = data.get("evidence")
    if evidence is not None and not isinstance(evidence, Mapping):
        raise ReviewDecisionError("decision.evidence must be an object when present")
    return make_review_decision(
        issue_code=_required_string(data.get("issue_code"), "issue_code"),
        source_question_index=source_question_index,
        action=validate_review_action(data.get("action")),
        decided_at=_required_string(data.get("decided_at"), "decided_at"),
        decided_by=_required_string(data.get("decided_by", "user"), "decided_by"),
        group_id=data.get("group_id") if isinstance(data.get("group_id"), str) else None,
        evidence=evidence,
    )


def _parse_group(data: Any) -> GroupReviewDecision:
    if not isinstance(data, Mapping):
        raise ReviewDecisionError("Each group must be an object")
    affected = data.get("affected_question_indexes")
    if not isinstance(affected, list):
        raise ReviewDecisionError("affected_question_indexes must be a list")
    return expand_group_decision(
        group_id=_required_string(data.get("group_id"), "group_id"),
        issue_code=_required_string(data.get("issue_code"), "issue_code"),
        action=validate_review_action(data.get("action")),
        affected_question_indexes=affected,
        decided_at=_required_string(data.get("decided_at"), "decided_at"),
        decided_by=_required_string(data.get("decided_by", "user"), "decided_by"),
    )


def _coerce_artifact(
    review_artifact: ReviewArtifact | Mapping[str, Any] | None,
) -> ReviewArtifact | None:
    if review_artifact is None:
        return None
    if isinstance(review_artifact, ReviewArtifact):
        return review_artifact
    return parse_review_artifact(review_artifact)


def _decision_index(
    decisions: list[ReviewDecision],
) -> dict[tuple[str, int], ReviewDecision]:
    index: dict[tuple[str, int], ReviewDecision] = {}
    for decision in decisions:
        validate_review_action(decision.action)
        index[(decision.issue_code, decision.source_question_index)] = decision
    return index


def _matching_decision(
    issue: ValidationIssue,
    decisions: dict[tuple[str, int], ReviewDecision],
) -> ReviewDecision | None:
    if issue.source_question_index is None:
        return None
    return decisions.get((issue.code, issue.source_question_index))


def _resolves_hard_error(issue: ValidationIssue, decision: ReviewDecision | None) -> bool:
    return (
        issue.source_question_index is not None
        and decision is not None
        and decision.action == "skip_question"
    )


def _resolves_warning(issue: ValidationIssue, decision: ReviewDecision | None) -> bool:
    if decision is None:
        return False
    if decision.action == "skip_question":
        return True
    if issue.code == "possible_duplicate_question":
        return decision.action in {"confirm", "send_both"}
    return decision.action == "confirm"


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewDecisionError(f"{field_name} must be a non-empty string")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
