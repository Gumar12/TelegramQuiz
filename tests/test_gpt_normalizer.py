import json

from gpt_normalizer import build_messages, build_response_schema, extract_json_object, normalize_dataset
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
