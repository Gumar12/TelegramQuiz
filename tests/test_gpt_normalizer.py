import json

from gpt_normalizer import build_messages, build_response_schema, extract_json_object
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
