import pytest

from backend.pipeline.review import (
    ReviewDecisionError,
    build_review_artifact,
    expand_group_decision,
    make_review_decision,
    parse_review_artifact,
    resolve_upload_gate,
)
from backend.pipeline.validation import validate_clean_quiz


def clean_quiz(items, *, title="История Казахстана"):
    return {
        "title": title,
        "settings": {
            "time_limit": "30 sec",
            "shuffle_options": True,
            "context_send_mode": "per-question",
        },
        "items": items,
    }


def question(text="Вопрос?", *, answers=None):
    return {
        "type": "question",
        "question": text,
        "options": [{"text": "Первый"}, {"text": "Второй"}],
        "answers": [1] if answers is None else answers,
        "mode": "single",
    }


def duplicate_warning_report():
    return validate_clean_quiz(
        clean_quiz(
            [
                question("Одинаковый вопрос?"),
                question("Одинаковый вопрос?"),
            ]
        )
    )


def test_warning_is_unresolved_until_confirm_or_send_both():
    report = duplicate_warning_report()

    unresolved = resolve_upload_gate(report)
    confirm = build_review_artifact(
        quiz_file_hash=report.quiz_file_hash,
        decisions=[
            make_review_decision(
                issue_code="possible_duplicate_question",
                source_question_index=2,
                action="confirm",
            )
        ],
    )
    send_both = build_review_artifact(
        quiz_file_hash=report.quiz_file_hash,
        decisions=[
            make_review_decision(
                issue_code="possible_duplicate_question",
                source_question_index=2,
                action="send_both",
            )
        ],
    )

    assert unresolved.status == "review_required"
    assert resolve_upload_gate(report, confirm).status == "allowed"
    assert resolve_upload_gate(report, send_both).status == "allowed"


def test_hard_error_can_be_resolved_only_by_skip_question_or_file_correction():
    report = validate_clean_quiz(clean_quiz([question("Нет ответа?", answers=[])]))
    confirm = build_review_artifact(
        quiz_file_hash=report.quiz_file_hash,
        decisions=[
            make_review_decision(
                issue_code="answer_missing",
                source_question_index=1,
                action="confirm",
            )
        ],
    )
    skip = build_review_artifact(
        quiz_file_hash=report.quiz_file_hash,
        decisions=[
            make_review_decision(
                issue_code="answer_missing",
                source_question_index=1,
                action="skip_question",
            )
        ],
    )

    assert resolve_upload_gate(report, confirm).status == "blocked"
    skipped = resolve_upload_gate(report, skip)
    assert skipped.status == "allowed"
    assert skipped.skipped_question_indexes == [1]


def test_review_decisions_include_hash_and_become_stale_when_quiz_hash_changes():
    original_report = duplicate_warning_report()
    changed_report = validate_clean_quiz(
        clean_quiz(
            [
                question("Одинаковый вопрос?"),
                question("Одинаковый вопрос?"),
                question("Новый вопрос?"),
            ]
        )
    )
    artifact = build_review_artifact(
        quiz_file_hash=original_report.quiz_file_hash,
        decisions=[
            make_review_decision(
                issue_code="possible_duplicate_question",
                source_question_index=2,
                action="send_both",
            )
        ],
    )

    assert artifact.to_dict()["quiz_file_hash"] == original_report.quiz_file_hash
    assert resolve_upload_gate(changed_report, artifact).status == "review_required"
    assert resolve_upload_gate(changed_report, artifact).reason == "review_decisions_stale"


def test_group_decision_expands_to_per_question_decisions():
    group = expand_group_decision(
        group_id="possible_duplicate_question:sha256:test",
        issue_code="possible_duplicate_question",
        action="send_both",
        affected_question_indexes=[2, 4, 8],
        decided_at="2026-06-14T12:00:00Z",
    )
    artifact = build_review_artifact(quiz_file_hash="sha256:test", groups=[group])

    assert [decision.source_question_index for decision in group.expanded_decisions] == [2, 4, 8]
    assert [decision.source_question_index for decision in artifact.decisions] == [2, 4, 8]
    assert artifact.to_dict()["groups"][0]["expanded_decisions"][0]["action"] == "send_both"


def test_unknown_action_is_rejected():
    with pytest.raises(ReviewDecisionError):
        make_review_decision(
            issue_code="possible_duplicate_question",
            source_question_index=1,
            action="send_both_group",
        )

    with pytest.raises(ReviewDecisionError):
        parse_review_artifact(
            {
                "quiz_file_hash": "sha256:test",
                "decisions": [
                    {
                        "issue_code": "possible_duplicate_question",
                        "source_question_index": 1,
                        "action": "__import__('os').system('echo unsafe')",
                        "decided_at": "2026-06-14T12:00:00Z",
                    }
                ],
            }
        )
