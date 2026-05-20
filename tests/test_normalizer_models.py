import pytest

from normalizer_models import (
    ALLOWED_ERROR_REASONS,
    CleanQuestion,
    LocalValidationError,
    ReviewQuestion,
    validate_clean_question,
)


def valid_clean_payload():
    return {
        "source_item_id": 17,
        "date": "11 мая",
        "section": "УТРО",
        "context_title": "Контекст N2",
        "context": "Текст контекста",
        "media": ["media/image_003.png"],
        "question": "На портрете изображен:",
        "correct_answer": "Эмир Тимур",
        "options": ["Эмир Тимур", "Абылай хан", "Касым хан", "Тауке хан"],
        "correct": 1,
        "explanation": "На портрете изображен Эмир Тимур.",
        "explanation_full": "На портрете изображен Эмир Тимур, правитель XIV века.",
        "type": "media_context_quiz",
        "source": "gpt_normalized",
        "quality_flags": [],
    }


def test_clean_question_accepts_valid_payload():
    item = CleanQuestion(**valid_clean_payload())

    validate_clean_question(item)

    assert item.source_item_id == 17


def test_rejects_too_long_question():
    payload = valid_clean_payload()
    payload["question"] = "А" * 301
    item = CleanQuestion(**payload)

    with pytest.raises(LocalValidationError) as exc:
        validate_clean_question(item)

    assert exc.value.reason == "too_long_question"


def test_rejects_duplicate_options_after_normalization():
    payload = valid_clean_payload()
    payload["options"] = ["Эмир Тимур", " эмир   тимур ", "Касым хан", "Тауке хан"]
    item = CleanQuestion(**payload)

    with pytest.raises(LocalValidationError) as exc:
        validate_clean_question(item)

    assert exc.value.reason == "duplicate_options"


def test_rejects_correct_answer_mismatch():
    payload = valid_clean_payload()
    payload["correct_answer"] = "Тамерлан"
    item = CleanQuestion(**payload)

    with pytest.raises(LocalValidationError) as exc:
        validate_clean_question(item)

    assert exc.value.reason == "correct_not_in_options"


def test_rejects_weak_distractor_substring():
    payload = valid_clean_payload()
    payload["options"] = ["Эмир Тимур", "Тимур", "Касым хан", "Тауке хан"]
    item = CleanQuestion(**payload)

    with pytest.raises(LocalValidationError) as exc:
        validate_clean_question(item)

    assert exc.value.reason == "weak_distractors"


def test_review_question_requires_allowed_reason():
    assert "bad_json" in ALLOWED_ERROR_REASONS
    ReviewQuestion(
        source_item_id=1,
        error_reason="bad_json",
        raw_item={"id": 1},
        last_gpt_output={},
        attempts=1,
        notes="JSON parsing failed",
    )

    with pytest.raises(ValueError):
        ReviewQuestion(
            source_item_id=1,
            error_reason="unknown_reason",
            raw_item={"id": 1},
            last_gpt_output={},
            attempts=1,
            notes="bad reason",
        )
