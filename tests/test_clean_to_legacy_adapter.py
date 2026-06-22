import json

from backend.models import Question
from backend.pipeline.upload_adapter import (
    clean_quiz_to_legacy_questions,
    load_clean_quiz,
)


def clean_quiz(items, *, title="История Казахстана", settings=None):
    return {
        "title": title,
        "settings": settings
        or {
            "time_limit": "30 sec",
            "shuffle_options": True,
            "context_send_mode": "per-question",
        },
        "items": items,
    }


def question(text="Вопрос?", *, answers=None, options=None, mode="single", **extra):
    item = {
        "type": "question",
        "question": text,
        "options": options
        or [
            {"text": "Первый"},
            {"text": "Второй"},
            {"text": "Третий"},
            {"text": "Четвертый"},
        ],
        "answers": answers or [2],
        "mode": mode,
    }
    item.update(extra)
    return item


def test_load_clean_quiz_reads_top_level_object(tmp_path):
    path = tmp_path / "quiz.clean.json"
    path.write_text(
        json.dumps(clean_quiz([question()]), ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_clean_quiz(path)

    assert loaded["title"] == "История Казахстана"
    assert loaded["items"][0]["question"] == "Вопрос?"


def test_title_context_question_becomes_legacy_quiz_with_inherited_context():
    legacy = clean_quiz_to_legacy_questions(
        clean_quiz(
            [
                {"type": "title", "text": "Тимур"},
                {"type": "context", "text": "Текст контекста", "media": ["media/timur.png"]},
                question("На портрете изображен:"),
            ],
            title="Большой квиз",
        )
    )

    assert legacy.title == "Большой квиз"
    assert len(legacy.questions) == 1
    assert legacy.questions[0].question == "На портрете изображен:"
    assert legacy.questions[0].context == "Текст контекста"
    assert legacy.questions[0].media == ["media/timur.png"]
    assert legacy.raw_questions[0]["source_question_index"] == 1
    assert legacy.raw_questions[0]["clean_item_index"] == 3
    assert "Тимур" not in legacy.questions[0].question


def test_title_and_reset_context_clear_context_and_are_not_upload_questions():
    legacy = clean_quiz_to_legacy_questions(
        clean_quiz(
            [
                {"type": "context", "text": "Старый контекст"},
                question("Первый вопрос?"),
                {"type": "title", "text": "Новая тема"},
                question("Второй вопрос?"),
                {"type": "context", "text": "Новый контекст"},
                {"type": "reset_context"},
                question("Третий вопрос?"),
            ]
        )
    )

    assert [item.question for item in legacy.questions] == [
        "Первый вопрос?",
        "Второй вопрос?",
        "Третий вопрос?",
    ]
    assert [item.context for item in legacy.questions] == ["Старый контекст", "", ""]
    assert [item["source_question_index"] for item in legacy.raw_questions] == [1, 2, 3]


def test_multiple_answers_preserve_list_correct_indexes():
    legacy = clean_quiz_to_legacy_questions(
        clean_quiz(
            [
                question(
                    "Выберите верные:",
                    answers=[1, 3],
                    mode="multiple",
                )
            ]
        )
    )

    assert legacy.questions[0].correct == [1, 3]
    assert legacy.raw_questions[0]["correct"] == [1, 3]


def test_start_from_39_returns_source_question_39_first_and_skips_1_to_38():
    items = [question(f"Вопрос {index}?") for index in range(1, 41)]

    legacy = clean_quiz_to_legacy_questions(clean_quiz(items), start_from=39)

    assert legacy.questions[0].question == "Вопрос 39?"
    assert legacy.raw_questions[0]["source_question_index"] == 39
    assert legacy.skipped_source_question_indexes == list(range(1, 39))
    assert legacy.to_legacy_json()["skipped_source_question_indexes"] == list(range(1, 39))
    assert legacy.to_legacy_json()["source_question_count"] == 40


def test_five_plus_options_preserve_order():
    options = [{"text": f"Вариант {index}"} for index in range(1, 7)]

    legacy = clean_quiz_to_legacy_questions(
        clean_quiz([question("Шесть вариантов?", answers=[5], options=options)])
    )

    assert legacy.questions[0].options == [
        "Вариант 1",
        "Вариант 2",
        "Вариант 3",
        "Вариант 4",
        "Вариант 5",
        "Вариант 6",
    ]
    assert legacy.questions[0].correct == 5


def test_forbidden_internal_custom_fields_do_not_execute_or_leak_into_upload_text(tmp_path):
    marker = tmp_path / "should_not_exist"
    payload = f"__import__('pathlib').Path({str(marker)!r}).touch()"
    legacy = clean_quiz_to_legacy_questions(
        clean_quiz(
            [
                {
                    "type": "title",
                    "text": "Служебный заголовок",
                    "parse_meta": {"template": payload},
                },
                {
                    "type": "context",
                    "text": "Безопасный контекст",
                    "custom_fields": {"prompt": payload},
                },
                question(
                    "Безопасный вопрос?",
                    custom_fields={"internal": payload},
                    source_ref={"line": payload},
                    parse_meta={"regex": payload},
                ),
            ],
            settings={"template": payload, "context_send_mode": "per-question"},
        )
    )

    upload_text = "\n".join(
        [
            legacy.questions[0].question,
            legacy.questions[0].context,
            *legacy.questions[0].options,
            legacy.questions[0].explanation,
        ]
    )
    assert payload not in upload_text
    assert "source_ref" not in legacy.raw_questions[0]
    assert "parse_meta" not in legacy.raw_questions[0]
    assert not marker.exists()


def test_output_raw_question_can_instantiate_backend_question():
    legacy = clean_quiz_to_legacy_questions(clean_quiz([question("Можно создать модель?")]))

    model = Question(**legacy.raw_questions[0])

    assert model == legacy.questions[0]
