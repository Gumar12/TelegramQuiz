import json
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import gpt_normalizer
from backend.gpt_normalizer import (
    build_messages,
    build_response_schema,
    call_openai_normalizer,
    extract_json_object,
    normalize_dataset,
    parse_args,
    prepare_image_data_url,
    prepare_media_inputs,
    run,
)
from backend.normalizer_io import load_v2_dataset
from backend.normalizer_models import RawQuestion
from backend.normalizer_models import LocalValidationError


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
    assert args.style_examples == 5
    assert args.style_source is None


def test_parse_args_rejects_bad_numeric_args():
    base_args = [
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

    with pytest.raises(SystemExit):
        parse_args([*base_args, "--limit", "-1"])
    with pytest.raises(SystemExit):
        parse_args([*base_args, "--max-retries", "0"])
    with pytest.raises(SystemExit):
        parse_args([*base_args, "--style-examples", "-1"])


def write_source(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "quiz_description": "Sample quiz",
                "questions": [sample_raw_question().model_dump()],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def cli_args(tmp_path: Path, *extra: str):
    input_path = tmp_path / "questions_v2.json"
    write_source(input_path)
    return parse_args(
        [
            "--input",
            str(input_path),
            "--output",
            str(tmp_path / "clean_questions.json"),
            "--review",
            str(tmp_path / "review_questions.json"),
            "--report",
            str(tmp_path / "normalizer_report.json"),
            "--model",
            "gpt-4.1-mini",
            *extra,
        ]
    )


def test_run_missing_api_key_returns_1_before_openai_client_creation(tmp_path, monkeypatch):
    args = cli_args(tmp_path)
    monkeypatch.setattr(gpt_normalizer, "load_dotenv", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(gpt_normalizer, "OpenAI", lambda: pytest.fail("OpenAI client should not be created"))

    assert run(args) == 1


def test_run_path_collision_returns_1_before_openai_client_creation(tmp_path, monkeypatch):
    input_path = tmp_path / "questions_v2.json"
    write_source(input_path)
    args = parse_args(
        [
            "--input",
            str(input_path),
            "--output",
            str(input_path),
            "--review",
            str(tmp_path / "review_questions.json"),
            "--report",
            str(tmp_path / "normalizer_report.json"),
            "--model",
            "gpt-4.1-mini",
        ]
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(gpt_normalizer, "OpenAI", lambda: pytest.fail("OpenAI client should not be created"))

    assert run(args) == 1


def test_run_dry_run_performs_no_writes_and_returns_0(tmp_path, monkeypatch):
    args = cli_args(tmp_path, "--dry-run")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(gpt_normalizer, "OpenAI", lambda: object())
    monkeypatch.setattr(
        gpt_normalizer,
        "call_openai_normalizer",
        lambda client, model, raw, previous_error=None, **kwargs: valid_gpt_payload(raw),
    )
    writes: list[tuple[object, object]] = []
    monkeypatch.setattr(gpt_normalizer, "write_json_atomic", lambda path, data: writes.append((path, data)))

    assert run(args) == 0
    assert writes == []


def write_multi_source(path: Path, ids: list[int]) -> None:
    questions = [
        sample_raw_question().model_copy(update={"id": item_id, "media": []}).model_dump()
        for item_id in ids
    ]
    path.write_text(
        json.dumps(
            {"quiz_title": "Sample", "quiz_description": "Sample quiz", "questions": questions},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def multi_cli_args(tmp_path: Path, ids: list[int], *extra: str):
    input_path = tmp_path / "questions_v2.json"
    write_multi_source(input_path, ids)
    return parse_args(
        [
            "--input",
            str(input_path),
            "--output",
            str(tmp_path / "clean_questions.json"),
            "--review",
            str(tmp_path / "review_questions.json"),
            "--report",
            str(tmp_path / "normalizer_report.json"),
            "--model",
            "gpt-4.1-mini",
            *extra,
        ]
    )


def test_run_resumes_into_existing_output_after_api_outage(tmp_path, monkeypatch):
    args = multi_cli_args(tmp_path, [1, 2, 3], "--max-retries", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(gpt_normalizer, "OpenAI", lambda: object())

    def first_run(client, model, raw, previous_error=None, **kwargs):
        if raw.id == 2:
            raise gpt_normalizer.OpenAIError("request failed")
        return valid_gpt_payload(raw)

    monkeypatch.setattr(gpt_normalizer, "call_openai_normalizer", first_run)

    # First run stops on the outage at id 2 and writes partial progress.
    assert run(args) == 1
    output = json.loads(Path(args.output).read_text(encoding="utf-8"))
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    assert [q["source_item_id"] for q in output["questions"]] == [1]
    assert [q["source_item_id"] for q in review["questions"]] == [2]
    assert review["questions"][0]["error_reason"] == "gpt_request_failed"

    processed: list[int] = []

    def second_run(client, model, raw, previous_error=None, **kwargs):
        processed.append(raw.id)
        return valid_gpt_payload(raw)

    monkeypatch.setattr(gpt_normalizer, "call_openai_normalizer", second_run)

    # Second run skips the finished id 1, retries the outage id 2, finishes id 3.
    assert run(args) == 0
    assert processed == [2, 3]
    output = json.loads(Path(args.output).read_text(encoding="utf-8"))
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    assert [q["source_item_id"] for q in output["questions"]] == [1, 2, 3]
    assert review["questions"] == []


def test_run_resume_keeps_terminal_review_and_skips_clean(tmp_path, monkeypatch):
    args = multi_cli_args(tmp_path, [1, 2], "--max-retries", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(gpt_normalizer, "OpenAI", lambda: object())

    def first_run(client, model, raw, previous_error=None, **kwargs):
        if raw.id == 2:
            payload = valid_gpt_payload(raw)
            payload["options"] = ["Duplicate", "Duplicate", "Choice B", "Choice C"]
            return payload
        return valid_gpt_payload(raw)

    monkeypatch.setattr(gpt_normalizer, "call_openai_normalizer", first_run)

    assert run(args) == 0
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    assert review["questions"][0]["error_reason"] == "max_retries_exceeded"

    processed: list[int] = []

    def second_run(client, model, raw, previous_error=None, **kwargs):
        processed.append(raw.id)
        return valid_gpt_payload(raw)

    monkeypatch.setattr(gpt_normalizer, "call_openai_normalizer", second_run)

    # id 1 is clean, id 2 is a terminal (non-outage) failure: both are done, nothing reruns.
    assert run(args) == 0
    assert processed == []
    output = json.loads(Path(args.output).read_text(encoding="utf-8"))
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    assert [q["source_item_id"] for q in output["questions"]] == [1]
    assert [q["source_item_id"] for q in review["questions"]] == [2]


def test_run_passes_style_examples_from_style_source_to_openai(tmp_path, monkeypatch):
    input_path = tmp_path / "questions_v2.json"
    write_source(input_path)
    trusted = sample_raw_question().model_copy(
        update={
            "id": 101,
            "question": "Founder?",
            "correct_answer": "Kerei and Zhanibek",
            "options": ["Abylai", "Kerei and Zhanibek", "Tauke", "Kenesary"],
            "correct": 2,
            "distractors_source": "source_document_bold",
        }
    )
    style_source = tmp_path / "full_doc_questions_v2.json"
    style_source.write_text(
        json.dumps({"questions": [trusted.model_dump()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    args = parse_args(
        [
            "--input",
            str(input_path),
            "--output",
            str(tmp_path / "clean_questions.json"),
            "--review",
            str(tmp_path / "review_questions.json"),
            "--report",
            str(tmp_path / "normalizer_report.json"),
            "--model",
            "gpt-4.1-mini",
            "--dry-run",
            "--style-source",
            str(style_source),
            "--style-examples",
            "1",
        ]
    )
    captured_examples: list[list[dict[str, object]]] = []
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(gpt_normalizer, "OpenAI", lambda: object())

    def fake_call_openai_normalizer(client, model, raw, previous_error=None, **kwargs):
        captured_examples.append(kwargs["style_examples"])
        return valid_gpt_payload(raw)

    monkeypatch.setattr(gpt_normalizer, "call_openai_normalizer", fake_call_openai_normalizer)

    assert run(args) == 0
    assert captured_examples == [
        [
            {
                "source_item_id": 101,
                "date": trusted.date,
                "section": trusted.section,
                "question": "Founder?",
                "correct_answer": "Kerei and Zhanibek",
                "options": ["Abylai", "Kerei and Zhanibek", "Tauke", "Kenesary"],
                "correct": 2,
            }
        ]
    ]


def test_run_exhausted_api_error_returns_nonzero_and_writes_progress(tmp_path, monkeypatch):
    args = cli_args(tmp_path, "--max-retries", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(gpt_normalizer, "OpenAI", lambda: object())

    def fail_api(client, model, raw, previous_error=None, **kwargs):
        raise gpt_normalizer.OpenAIError("request failed")

    monkeypatch.setattr(gpt_normalizer, "call_openai_normalizer", fail_api)

    assert run(args) == 1

    output = json.loads(Path(args.output).read_text(encoding="utf-8"))
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    assert output["questions"] == []
    assert review["questions"][0]["error_reason"] == "gpt_request_failed"
    assert report["error_reason_counts"] == {"gpt_request_failed": 1}


def test_selection_filters_before_raw_question_construction():
    valid = sample_raw_question().model_dump()
    malformed = {"id": 43}
    data = {"questions": [valid, malformed]}

    clean, review = normalize_dataset(
        data,
        normalize_one=lambda raw, previous_error=None: valid_gpt_payload(raw),
        limit=1,
        start_id=None,
        max_retries=1,
        seed=42,
    )

    assert len(clean) == 1
    assert review == []


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


def test_build_messages_gives_specific_repair_instruction_for_weak_distractors():
    messages = build_messages(sample_raw_question(), previous_error="weak_distractors")
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "не используй исходные варианты ответа" in serialized
    assert "без многоточий" in serialized


def test_build_messages_attaches_media_inputs_after_text():
    media_input = {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64,abcd",
        "detail": "high",
    }

    messages = build_messages(sample_raw_question(), media_inputs=[media_input])

    user_content = messages[1]["content"]
    assert user_content[0]["type"] == "input_text"
    assert user_content[1] == media_input
    assert '"media_attached": true' in user_content[0]["text"]


def test_build_style_examples_uses_only_trusted_document_quizzes():
    trusted = sample_raw_question().model_copy(
        update={
            "id": 101,
            "question": "Founder?",
            "correct_answer": "Kerei and Zhanibek",
            "options": ["Abylai", "Kerei and Zhanibek", "Tauke", "Kenesary"],
            "correct": 2,
            "distractors_source": "source_document_bold",
        }
    )
    heuristic = trusted.model_copy(
        update={
            "id": 102,
            "question": "Heuristic?",
            "distractors_source": "heuristic_same_document",
        }
    )

    examples = gpt_normalizer.build_style_examples(
        {"questions": [trusted.model_dump(), heuristic.model_dump()]},
        limit=5,
    )

    assert examples == [
        {
            "source_item_id": 101,
            "date": trusted.date,
            "section": trusted.section,
            "question": "Founder?",
            "correct_answer": "Kerei and Zhanibek",
            "options": ["Abylai", "Kerei and Zhanibek", "Tauke", "Kenesary"],
            "correct": 2,
        }
    ]


def test_build_style_examples_skips_multi_answer_quizzes():
    multi_answer = sample_raw_question().model_copy(
        update={
            "id": 103,
            "question": "Select correct statements",
            "correct_answer": "A; D",
            "correct_answers": ["A", "D"],
            "options": ["A", "B", "C", "D"],
            "correct": [1, 4],
            "distractors_source": "source_document_answer_indexes",
        }
    )

    examples = gpt_normalizer.build_style_examples(
        {"questions": [multi_answer.model_dump()]},
        limit=5,
    )

    assert examples == []


def test_build_messages_includes_document_style_examples_without_copying_as_facts():
    style_examples = [
        {
            "source_item_id": 101,
            "date": "12 May",
            "section": "Morning",
            "question": "Founder?",
            "correct_answer": "Kerei and Zhanibek",
            "options": ["Abylai", "Kerei and Zhanibek", "Tauke", "Kenesary"],
            "correct": 2,
        }
    ]

    messages = build_messages(sample_raw_question(), style_examples=style_examples)
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "style_examples" in serialized
    assert "Kerei and Zhanibek" in serialized
    assert "style_examples are examples of option style only" in serialized
    assert "same semantic type" in serialized


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


def test_prepare_image_data_url_uses_ffmpeg_for_large_local_images(tmp_path, monkeypatch):
    image_path = tmp_path / "portrait.png"
    image_path.write_bytes(b"source-image")
    calls: list[list[str]] = []

    monkeypatch.setattr(gpt_normalizer, "_probe_image_size", lambda path, ffprobe_path, timeout: (2000, 1200))

    def fake_run(cmd, check, capture_output, timeout):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"jpeg-bytes")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(gpt_normalizer.subprocess, "run", fake_run)

    data_url = prepare_image_data_url(image_path, ffmpeg_path="ffmpeg", max_side=1024, jpeg_quality=3)

    assert data_url == f"data:image/jpeg;base64,{base64.b64encode(b'jpeg-bytes').decode('ascii')}"
    assert calls
    assert "scale=1024:1024:force_original_aspect_ratio=decrease" in calls[0]


def test_prepare_media_inputs_passes_remote_urls_through():
    raw = sample_raw_question().model_copy(update={"media": ["https://example.com/image.jpg"]})

    media_inputs = prepare_media_inputs(raw, image_detail="high")

    assert media_inputs == [
        {
            "type": "input_image",
            "image_url": "https://example.com/image.jpg",
            "detail": "high",
        }
    ]


def test_prepare_media_inputs_resolves_missing_media_against_media_root(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    image_path = media_root / "image_001.png"
    image_path.write_bytes(b"image-bytes")
    raw = sample_raw_question().model_copy(
        update={"media": ["/mnt/data/quizbot_pipeline_v2/media/image_001.png"]}
    )

    media_inputs = prepare_media_inputs(raw, image_detail="high", media_root=media_root)

    assert media_inputs == [
        {
            "type": "input_image",
            "image_url": "data:image/png;base64,aW1hZ2UtYnl0ZXM=",
            "detail": "high",
        }
    ]


def test_resolve_media_path_rejects_absolute_path_outside_trusted_root(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    target = outside / "passwd.png"
    target.write_bytes(b"image-bytes")

    # An absolute path that exists but lives outside the trusted media root must
    # not be honoured, even though resolution by filename could otherwise hit it.
    assert gpt_normalizer.resolve_media_path(str(target), media_root=media_root) is None


def test_resolve_media_path_rejects_parent_traversal_escape(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"image-bytes")

    assert gpt_normalizer.resolve_media_path("../outside.png", media_root=media_root) is None


def test_resolve_media_path_rejects_unknown_media_path(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()

    assert gpt_normalizer.resolve_media_path("media/missing.png", media_root=media_root) is None


def test_resolve_media_path_rejects_disallowed_suffix(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    (media_root / "payload.exe").write_bytes(b"not-an-image")

    assert gpt_normalizer.resolve_media_path("media/payload.exe", media_root=media_root) is None


def test_prepare_image_data_url_blocks_oversize_fallback(tmp_path, monkeypatch):
    image_path = tmp_path / "huge.png"
    image_path.write_bytes(b"x" * 16)

    monkeypatch.setattr(gpt_normalizer, "MAX_IMAGE_PAYLOAD_BYTES", 8)
    monkeypatch.setattr(gpt_normalizer, "_probe_image_size", lambda path, ffprobe_path, timeout: (2000, 1200))

    def fake_run(cmd, check, capture_output, timeout):
        raise OSError("ffmpeg missing")

    monkeypatch.setattr(gpt_normalizer.subprocess, "run", fake_run)

    with pytest.raises(gpt_normalizer.OversizeMediaError):
        prepare_image_data_url(image_path, ffmpeg_path="ffmpeg", max_side=1024, jpeg_quality=3)


def test_prepare_media_inputs_drops_oversize_fallback_instead_of_sending(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    media_root.mkdir()
    image_path = media_root / "huge.png"
    image_path.write_bytes(b"x" * 16)
    raw = sample_raw_question().model_copy(update={"media": ["media/huge.png"]})

    monkeypatch.setattr(gpt_normalizer, "MAX_IMAGE_PAYLOAD_BYTES", 8)
    monkeypatch.setattr(gpt_normalizer, "_probe_image_size", lambda path, ffprobe_path, timeout: (2000, 1200))
    monkeypatch.setattr(
        gpt_normalizer.subprocess,
        "run",
        lambda cmd, check, capture_output, timeout: (_ for _ in ()).throw(OSError("ffmpeg missing")),
    )

    media_inputs = prepare_media_inputs(raw, image_detail="high", media_root=media_root)

    assert media_inputs == []


def test_call_openai_normalizer_passes_prepared_media_to_responses(monkeypatch):
    raw = sample_raw_question().model_copy(update={"media": ["media/image.jpg"]})
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        gpt_normalizer,
        "prepare_media_inputs",
        lambda raw, image_detail, ffmpeg_path, max_side, jpeg_quality, media_root=None: [
            {"type": "input_image", "image_url": "data:image/jpeg;base64,abcd", "detail": image_detail}
        ],
    )

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text=json.dumps(valid_gpt_payload(raw), ensure_ascii=False))

    class FakeClient:
        responses = FakeResponses()

    call_openai_normalizer(FakeClient(), "gpt-test", raw, image_detail="high")

    user_content = captured["input"][1]["content"]
    assert user_content[1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,abcd", "detail": "high"}


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


def test_normalize_dataset_sends_non_object_json_value_errors_to_review():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        raise ValueError("GPT output is not a JSON object")

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
    assert review[0].error_reason == "bad_json"
    assert review[0].attempts == 2
    assert "GPT output is not a JSON object" in review[0].notes


def test_normalize_dataset_stops_after_exhausted_api_error():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")
    attempts: list[tuple[int, str | None]] = []

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        attempts.append((raw.id, previous_error))
        raise gpt_normalizer.OpenAIError("request failed")

    clean, review = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=2,
        start_id=None,
        max_retries=2,
        seed=42,
    )

    assert clean == []
    assert len(review) == 1
    assert review[0].source_item_id == 1
    assert review[0].error_reason == "gpt_request_failed"
    assert review[0].attempts == 2
    assert attempts == [(1, None), (1, "gpt_request_failed")]


def test_normalize_dataset_raises_when_cancel_requested_between_questions():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")
    attempts: list[int] = []

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        attempts.append(raw.id)
        return valid_gpt_payload(raw)

    def cancel_after_first_question() -> None:
        if attempts:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        normalize_dataset(
            data,
            normalize_one=fake_normalizer,
            limit=2,
            start_id=None,
            max_retries=1,
            seed=42,
            cancel_check=cancel_after_first_question,
        )

    assert attempts == [1]


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


def test_normalize_dataset_retries_when_gpt_reuses_heuristic_source_distractors():
    data = {
        "questions": [
            {
                **sample_raw_question().model_dump(),
                "id": 77,
                "question": "Feature of culture?",
                "correct_answer": "burial structures",
                "options": [
                    "burial structures",
                    "colonial administration reduced local authority",
                    "mass famine caused population collapse",
                    "alash government opposed bolsheviks",
                ],
                "correct": 1,
                "distractors_source": "heuristic_same_document",
            }
        ]
    }
    previous_errors: list[str | None] = []

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        previous_errors.append(previous_error)
        if previous_error is None:
            return {
                "question": "Feature of culture?",
                "correct_answer": "burial structures",
                "options": [
                    "burial structures",
                    "animal style",
                    "colonial administration reduced local authority",
                    "stone tools",
                ],
                "correct": 1,
                "explanation": "The feature was burial structures.",
                "explanation_full": "The source answer identifies burial structures as the feature.",
                "quality_flags": [],
            }
        return {
            "question": "Feature of culture?",
            "correct_answer": "burial structures",
            "options": ["burial structures", "animal style", "stone tools", "rock drawings"],
            "correct": 1,
            "explanation": "The feature was burial structures.",
            "explanation_full": "The source answer identifies burial structures as the feature.",
            "quality_flags": [],
        }

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
    assert previous_errors == [None, "weak_distractors"]
    assert "colonial administration reduced local authority" not in clean[0].options


def test_normalize_dataset_passes_trusted_source_quiz_without_calling_gpt():
    raw = sample_raw_question().model_copy(
        update={
            "id": 78,
            "question": "Кто считается основателем Казахского ханства?",
            "correct_answer": "Керей и Жанибек",
            "options": ["Абылай хан", "Керей и Жанибек", "Кенесары хан", "Тауке хан"],
            "correct": 2,
            "type": "multiple_choice",
            "distractors_source": "source_document_bold",
        }
    )
    calls: list[int] = []

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        calls.append(raw.id)
        raise AssertionError("GPT normalizer should not be called for trusted source quizzes")

    clean, review = normalize_dataset(
        {"questions": [raw.model_dump()]},
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=2,
        seed=42,
    )

    assert calls == []
    assert review == []
    assert len(clean) == 1
    assert clean[0].source_item_id == 78
    assert clean[0].correct_answer == clean[0].options[clean[0].correct - 1]
    assert set(clean[0].options) == {"Абылай хан", "Керей и Жанибек", "Кенесары хан", "Тауке хан"}
    assert clean[0].source == "source_document_bold"


def test_normalize_dataset_passes_source_index_multi_answer_without_calling_gpt():
    raw = sample_raw_question().model_copy(
        update={
            "id": 79,
            "question": "Установите верные утверждения",
            "correct_answer": "Верно A; Верно D",
            "correct_answers": ["Верно A", "Верно D"],
            "options": ["Верно A", "Неверно B", "Неверно C", "Верно D"],
            "correct": [1, 4],
            "type": "multiple_answer",
            "distractors_source": "source_document_answer_indexes",
        }
    )
    calls: list[int] = []

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        calls.append(raw.id)
        raise AssertionError("GPT normalizer should not be called for trusted source multi-answer quizzes")

    clean, review = normalize_dataset(
        {"questions": [raw.model_dump()]},
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=2,
        seed=42,
    )

    assert calls == []
    assert review == []
    assert len(clean) == 1
    assert isinstance(clean[0].correct, list)
    assert {clean[0].options[index - 1] for index in clean[0].correct} == {"Верно A", "Верно D"}
    assert clean[0].correct_answers == [clean[0].options[index - 1] for index in clean[0].correct]
    assert clean[0].source == "source_document_answer_indexes"


def test_normalize_dataset_sends_unprepared_media_to_visual_review_without_retry():
    raw = sample_raw_question().model_copy(
        update={"id": 88, "media": ["missing/image_001.png"], "type": "media_context_quiz"}
    )
    attempts: list[tuple[int, str | None]] = []

    def fake_normalizer(raw: RawQuestion, previous_error: str | None = None) -> dict[str, object]:
        attempts.append((raw.id, previous_error))
        raise LocalValidationError("needs_visual_review", "declared media could not be prepared")

    clean, review = normalize_dataset(
        {"questions": [raw.model_dump()]},
        normalize_one=fake_normalizer,
        limit=1,
        start_id=None,
        max_retries=3,
        seed=42,
    )

    assert clean == []
    assert len(review) == 1
    assert review[0].source_item_id == 88
    assert review[0].error_reason == "needs_visual_review"
    assert review[0].attempts == 1
    assert attempts == [(88, None)]


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


def test_shuffle_options_keeps_correct_with_duplicate_option_texts():
    from backend.gpt_normalizer import shuffle_options
    from backend.normalizer_models import CleanQuestion

    # Two options share the exact same text but only the second one (index 2)
    # is correct. A text-based .index() mapping after shuffle would lock onto
    # the first "Дубликат" and corrupt correctness; the flag-carrying shuffle
    # must keep the originally-correct option correct.
    item = CleanQuestion(
        source_item_id=1,
        question="Который дубликат верный?",
        correct_answer="Дубликат",
        options=["Тимур", "Дубликат", "Дубликат", "Абылай"],
        correct=2,
        explanation="",
        explanation_full="",
    )

    for seed in range(20):
        shuffled = shuffle_options(item, seed)
        assert sorted(shuffled.options) == sorted(item.options)
        correct_index = (
            shuffled.correct if isinstance(shuffled.correct, int) else shuffled.correct[0]
        )
        # Exactly one option flagged correct, and it is a "Дубликат".
        assert isinstance(shuffled.correct, int)
        assert shuffled.options[correct_index - 1] == "Дубликат"
        assert shuffled.correct_answer == "Дубликат"
