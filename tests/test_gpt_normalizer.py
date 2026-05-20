import json

from gpt_normalizer import build_messages, build_response_schema, extract_json_object, normalize_dataset, parse_args
from normalizer_io import load_v2_dataset
from normalizer_models import RawQuestion


def sample_raw_question() -> RawQuestion:
    return RawQuestion(
        id=42,
        date="20 мая",
        section="История Казахстана",
        context_title="Устав",
        context="Устав о сибирских киргизах был принят в 1822 году.",
        question="Что регулировал Устав о сибирских киргизах?",
        correct_answer="Управление Сибирскими киргизами",
        options=[],
        type="text_quiz",
        source="fixture",
    )


def test_parse_args_defaults():
    args = parse_args(
        [
            "--input",
            "questions_v2.json",
            "--output",
            "clean_questions.json",
            "--review",
            "review_questions.json",
            "--report",
            "normalizer_report.json",
            "--model",
            "gpt-4.1-mini",
        ]
    )

    assert args.seed == 42
    assert args.max_retries == 3
    assert args.limit is None
    assert args.start_id is None


def test_build_messages_includes_json_instruction_and_raw_content_without_source_item_id():
    messages = build_messages(sample_raw_question())
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "JSON" in serialized
    assert "Не добавляй факты" in serialized
    assert "Устав о сибирских киргизах" in serialized
    assert "source_item_id" not in serialized


def test_build_messages_includes_previous_error_when_provided():
    messages = build_messages(sample_raw_question(), previous_error="duplicate options")
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "duplicate options" in serialized


def test_build_response_schema_matches_required_structured_output_contract():
    schema = build_response_schema()

    assert schema["type"] == "json_schema"
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert schema["schema"]["required"] == [
        "question",
        "correct_answer",
        "options",
        "correct",
        "explanation",
        "explanation_full",
        "quality_flags",
    ]


def test_extract_json_object_accepts_dict():
    payload = {"question": "Кто?", "quality_flags": []}

    assert extract_json_object(payload) == payload


def test_extract_json_object_accepts_json_string():
    payload = {"question": "Кто?", "quality_flags": []}

    assert extract_json_object(json.dumps(payload, ensure_ascii=False)) == payload


def valid_gpt_payload(raw: RawQuestion) -> dict[str, object]:
    return {
        "question": f"Question {raw.id}?",
        "correct_answer": f"Answer {raw.id}",
        "options": [f"Answer {raw.id}", f"Choice A {raw.id}", f"Choice B {raw.id}", f"Choice C {raw.id}"],
        "correct": 1,
        "explanation": f"Explanation {raw.id}.",
        "explanation_full": f"Full explanation {raw.id}.",
        "quality_flags": [],
    }


def test_normalize_dataset_accepts_fake_clean_outputs():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        return valid_gpt_payload(raw)

    clean, review = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=2,
        start_id=None,
        max_retries=1,
        seed=42,
    )

    assert len(clean) == 2
    assert len(review) == 0
    assert clean[0].source_item_id == 1


def test_normalize_dataset_sends_bad_outputs_to_review():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        payload = valid_gpt_payload(raw)
        payload["options"] = ["Duplicate", "Duplicate", "Choice B", "Choice C"]
        return payload

    clean, review = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=2,
        seed=42,
    )

    assert clean == []
    assert len(review) == 1
    assert review[0].source_item_id == 1
    assert review[0].error_reason in {"duplicate_options", "max_retries_exceeded"}


def test_normalize_dataset_sends_mismatched_correct_answer_to_review():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        payload = valid_gpt_payload(raw)
        payload["correct_answer"] = "Not in the first option"
        payload["correct"] = 1
        return payload

    clean, review = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=1,
        seed=42,
    )

    assert clean == []
    assert len(review) == 1
    assert review[0].error_reason == "max_retries_exceeded"
    assert "correct_not_in_options" in review[0].notes


def test_normalize_dataset_sends_invalid_correct_indexes_to_review():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    for correct in (0, -1, 5):
        def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
            payload = valid_gpt_payload(raw)
            payload["correct"] = correct
            return payload

        clean, review = normalize_dataset(
            data,
            normalize_one=fake_normalizer,
            limit=1,
            start_id=None,
            max_retries=1,
            seed=42,
        )

        assert clean == []
        assert len(review) == 1
        assert review[0].error_reason == "max_retries_exceeded"
        assert "correct_not_in_options" in review[0].notes


def test_normalize_dataset_retries_with_previous_validation_error():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")
    previous_errors: list[str | None] = []

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        previous_errors.append(previous_error)
        payload = valid_gpt_payload(raw)
        if len(previous_errors) == 1:
            payload["options"] = ["Duplicate", "Duplicate", "Choice B", "Choice C"]
        return payload

    clean, review = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=2,
        seed=42,
    )

    assert len(clean) == 1
    assert review == []
    assert previous_errors == [None, "duplicate_options"]


def test_normalize_dataset_permanent_duplicate_options_reports_retry_exhaustion():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        payload = valid_gpt_payload(raw)
        payload["options"] = ["Duplicate", "Duplicate", "Choice B", "Choice C"]
        return payload

    clean, review = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=2,
        seed=42,
    )

    assert clean == []
    assert len(review) == 1
    assert review[0].error_reason == "max_retries_exceeded"
    assert review[0].attempts == 2
    assert "duplicate_options" in review[0].notes


def test_normalize_dataset_deterministic_shuffle_preserves_correct_answer_position():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        return valid_gpt_payload(raw)

    clean, review = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=1,
        seed=42,
    )

    assert review == []
    assert len(clean) == 1
    assert clean[0].options[clean[0].correct - 1] == clean[0].correct_answer

    clean_again, review_again = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=1,
        seed=42,
    )

    assert review_again == []
    assert clean_again[0].options == clean[0].options
    assert clean_again[0].correct == clean[0].correct
