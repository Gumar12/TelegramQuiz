import asyncio
import json
from pathlib import Path

from backend import flow
from backend.flow import (
    BOT_PROMPTS,
    BTN_CREATE_NEW_QUIZ,
    BTN_CREATE_QUESTION,
    create_quiz,
    upload_question,
    upload_questions,
)
from backend.models import Question
from backend.parser import load_json


def test_load_json_accepts_clean_payload_and_preserves_context_media(tmp_path: Path):
    path = tmp_path / "clean_questions.json"
    path.write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "format_version": "2.1-clean",
                "questions": [
                    {
                        "question": "Who is shown?",
                        "options": ["A", "B", "C", "D"],
                        "correct": 2,
                        "explanation": "Because B.",
                        "context_title": "Context 1",
                        "context": "Look at the portrait.",
                        "media": ["media/image.jpg"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    questions = load_json(path)

    assert len(questions) == 1
    assert questions[0].context_title == "Context 1"
    assert questions[0].context == "Look at the portrait."
    assert questions[0].media == ["media/image.jpg"]


def test_upload_question_clicks_create_then_sends_context_and_media_before_poll(monkeypatch):
    class FakeMessage:
        def __init__(self, text, buttons=None):
            self.text = text
            self.buttons = buttons

    class FakeClient:
        def __init__(self):
            create_question_button = type("Button", (), {"text": BTN_CREATE_QUESTION})()
            self.calls = []
            self.last_reply = FakeMessage(
                BOT_PROMPTS["ask_next_question"],
                buttons=[[create_question_button]],
            )
            self.replies = [
                FakeMessage(
                    BOT_PROMPTS["prelude_create_question"],
                    buttons=[[create_question_button]],
                ),
                FakeMessage(BOT_PROMPTS["ask_next_question"]),
            ]

        async def send_text(self, text):
            self.calls.append(("text", text))
            return object()

        async def send_media(self, path, caption=""):
            self.calls.append(("media", path, caption))
            return object()

        async def send_quiz_poll(self, question, options, correct_indexes, solution):
            self.calls.append(("poll", question, options, correct_indexes, solution))
            return object()

        async def wait_reply(self):
            self.calls.append(("wait",))
            self.last_reply = self.replies.pop(0)
            return self.last_reply

        async def click(self, msg, *, text=None, index=None):
            self.calls.append(("click", text, index))

    question = load_json(Path("tests/fixtures/extended_clean_question.json"))[0]
    client = FakeClient()

    monkeypatch.setattr(flow.config, "rand_delay", lambda rng: 0)
    asyncio.run(upload_question(client, question, index_in_quiz=1))

    assert client.calls[0] == ("click", BTN_CREATE_QUESTION, None)
    assert client.calls[1] == ("media", "media/image.jpg", "Context 1\n\nLook at the portrait.")
    assert client.calls[3] == ("click", BTN_CREATE_QUESTION, None)
    assert client.calls[4][0] == "poll"


def test_upload_question_continues_when_prelude_already_exists(monkeypatch):
    class FakeMessage:
        def __init__(self, text, buttons=None):
            self.text = text
            self.buttons = buttons

    class FakeClient:
        def __init__(self):
            create_question_button = type("Button", (), {"text": BTN_CREATE_QUESTION})()
            self.calls = []
            self.last_reply = FakeMessage(
                BOT_PROMPTS["ask_next_question"],
                buttons=[[create_question_button]],
            )
            self.replies = [
                FakeMessage(
                    BOT_PROMPTS["prelude_already_set"],
                    buttons=[[create_question_button]],
                ),
                FakeMessage(BOT_PROMPTS["ask_next_question"]),
            ]

        async def send_text(self, text):
            self.calls.append(("text", text))
            return object()

        async def send_media(self, path, caption=""):
            self.calls.append(("media", path, caption))
            return object()

        async def send_quiz_poll(self, question, options, correct_indexes, solution):
            self.calls.append(("poll", question, options, correct_indexes, solution))
            return object()

        async def wait_reply(self):
            self.calls.append(("wait",))
            self.last_reply = self.replies.pop(0)
            return self.last_reply

        async def click(self, msg, *, text=None, index=None):
            self.calls.append(("click", text, index))

    question = load_json(Path("tests/fixtures/extended_clean_question.json"))[0]
    client = FakeClient()

    monkeypatch.setattr(flow.config, "rand_delay", lambda rng: 0)
    asyncio.run(upload_question(client, question, index_in_quiz=1))

    assert client.calls[0] == ("click", BTN_CREATE_QUESTION, None)
    assert client.calls[1][0] == "media"
    assert client.calls[3] == ("click", BTN_CREATE_QUESTION, None)
    assert client.calls[4][0] == "poll"


def test_upload_question_can_shuffle_options_and_preserve_correct_answer(monkeypatch):
    class FakeMessage:
        def __init__(self, text, buttons=None):
            self.text = text
            self.buttons = buttons

    class FakeClient:
        def __init__(self):
            self.calls = []
            self.replies = [FakeMessage(BOT_PROMPTS["ask_next_question"])]

        async def send_quiz_poll(self, question, options, correct_indexes, solution):
            self.calls.append(("poll", question, options, correct_indexes, solution))
            return object()

        async def wait_reply(self):
            self.calls.append(("wait",))
            return self.replies.pop(0)

    question = Question(
        question="На портрете изображен",
        options=["Эмир Тимур", "Чингисхан", "Абылай хан", "Тауке хан"],
        correct=1,
        explanation="Эмир Тимур",
    )
    client = FakeClient()

    monkeypatch.setattr(flow.config, "rand_delay", lambda rng: 0)
    asyncio.run(
        upload_question(
            client,
            question,
            index_in_quiz=1,
            send_prelude=False,
            shuffle_options=True,
            shuffle_seed=7,
        )
    )

    _, _, options, correct_indexes, _ = client.calls[0]
    assert set(options) == set(question.options)
    assert options != question.options
    assert [options[index] for index in correct_indexes] == ["Эмир Тимур"]


def test_poll_options_shuffle_keeps_correct_with_duplicate_option_texts():
    from types import SimpleNamespace

    # Two options share the exact same text but only the second one is correct.
    # A text-based .index() mapping after shuffle would lock onto the first
    # match and corrupt which option is correct; the flag-carrying shuffle must
    # not.
    question = SimpleNamespace(
        question="Который из них верный дубликат?",
        options=["Тимур", "Дубликат", "Дубликат", "Абылай"],
        correct=3,
    )

    for seed in range(20):
        options, correct_indexes = flow._poll_options(
            question,
            index_in_quiz=1,
            shuffle_options=True,
            shuffle_seed=seed,
        )
        assert sorted(options) == sorted(question.options)
        assert len(correct_indexes) == 1
        # The originally-correct option is the SECOND "Дубликат"; exactly one
        # option must be flagged correct and it must be a "Дубликат".
        assert options[correct_indexes[0]] == "Дубликат"


def test_poll_options_without_shuffle_returns_zero_based_correct():
    from types import SimpleNamespace

    question = SimpleNamespace(
        question="Без перемешивания",
        options=["A", "B", "C", "D"],
        correct=[2, 4],
    )

    options, correct_indexes = flow._poll_options(
        question,
        index_in_quiz=1,
        shuffle_options=False,
        shuffle_seed=7,
    )

    assert options == ["A", "B", "C", "D"]
    assert correct_indexes == [1, 3]


def test_upload_question_can_shuffle_options_and_preserve_multiple_correct_answers(monkeypatch):
    class FakeMessage:
        def __init__(self, text, buttons=None):
            self.text = text
            self.buttons = buttons

    class FakeClient:
        def __init__(self):
            self.calls = []
            self.replies = [FakeMessage(BOT_PROMPTS["ask_next_question"])]

        async def send_quiz_poll(self, question, options, correct_indexes, solution):
            self.calls.append(("poll", question, options, correct_indexes, solution))
            return object()

        async def wait_reply(self):
            self.calls.append(("wait",))
            return self.replies.pop(0)

    question = Question(
        question="Выберите верные утверждения",
        options=["Верно A", "Неверно B", "Верно C", "Неверно D"],
        correct=[1, 3],
        explanation="A и C верные.",
    )
    client = FakeClient()

    monkeypatch.setattr(flow.config, "rand_delay", lambda rng: 0)
    asyncio.run(
        upload_question(
            client,
            question,
            index_in_quiz=1,
            send_prelude=False,
            shuffle_options=True,
            shuffle_seed=7,
        )
    )

    _, _, options, correct_indexes, _ = client.calls[0]
    assert set(options) == set(question.options)
    assert options != question.options
    assert {options[index] for index in correct_indexes} == {"Верно A", "Верно C"}


def test_upload_questions_defaults_to_sending_same_context_only_once(monkeypatch):
    class FakeMessage:
        def __init__(self, text, buttons=None):
            self.text = text
            self.buttons = buttons

    class FakeClient:
        def __init__(self):
            create_question_button = type("Button", (), {"text": BTN_CREATE_QUESTION})()
            self.calls = []
            self.last_reply = FakeMessage(
                BOT_PROMPTS["ask_next_question"],
                buttons=[[create_question_button]],
            )
            self.replies = [
                FakeMessage(
                    BOT_PROMPTS["prelude_create_question"],
                    buttons=[[create_question_button]],
                ),
                FakeMessage(
                    BOT_PROMPTS["ask_next_question"],
                    buttons=[[create_question_button]],
                ),
                FakeMessage(
                    BOT_PROMPTS["ask_next_question"],
                    buttons=[[create_question_button]],
                ),
                FakeMessage(
                    BOT_PROMPTS["prelude_create_question"],
                    buttons=[[create_question_button]],
                ),
                FakeMessage(BOT_PROMPTS["ask_next_question"]),
            ]

        async def send_text(self, text):
            self.calls.append(("text", text))
            return object()

        async def send_media(self, path, caption=""):
            self.calls.append(("media", path, caption))
            return object()

        async def send_quiz_poll(self, question, options, correct_indexes, solution):
            self.calls.append(("poll", question, options, correct_indexes, solution))
            return object()

        async def wait_reply(self):
            self.calls.append(("wait",))
            self.last_reply = self.replies.pop(0)
            return self.last_reply

        async def click(self, msg, *, text=None, index=None):
            self.calls.append(("click", text, index))

    same_context = {
        "context_title": "Context 1",
        "context": "Read the source.",
        "media": ["media/context.jpg"],
    }
    questions = [
        Question(
            question="Who is shown?",
            options=["A", "B", "C", "D"],
            correct=1,
            explanation="A.",
            **same_context,
        ),
        Question(
            question="Which year is mentioned?",
            options=["1370", "1465", "1731", "1991"],
            correct=1,
            explanation="1370.",
            **same_context,
        ),
        Question(
            question="What is the next source about?",
            options=["Map", "Portrait", "Law", "Song"],
            correct=1,
            explanation="Map.",
            context_title="Context 2",
            context="Look at the map.",
            media=[],
        ),
    ]

    monkeypatch.setattr(flow.config, "rand_delay", lambda rng: 0)
    client = FakeClient()
    asyncio.run(upload_questions(client, questions, shuffle_options=False))

    assert client.calls == [
        ("click", BTN_CREATE_QUESTION, None),
        ("media", "media/context.jpg", "Context 1\n\nRead the source."),
        ("wait",),
        ("click", BTN_CREATE_QUESTION, None),
        ("poll", "Who is shown?", ["A", "B", "C", "D"], [0], "A."),
        ("wait",),
        ("poll", "Which year is mentioned?", ["1370", "1465", "1731", "1991"], [0], "1370."),
        ("wait",),
        ("click", BTN_CREATE_QUESTION, None),
        ("text", "Context 2\n\nLook at the map."),
        ("wait",),
        ("click", BTN_CREATE_QUESTION, None),
        ("poll", "What is the next source about?", ["Map", "Portrait", "Law", "Song"], [0], "Map."),
        ("wait",),
    ]


def test_create_quiz_cancels_existing_draft_before_starting_new_quiz(monkeypatch):
    class FakeMessage:
        def __init__(self, text, buttons=None):
            self.text = text
            self.buttons = buttons

    class FakeClient:
        def __init__(self):
            button = type("Button", (), {"text": BTN_CREATE_NEW_QUIZ})()
            self.calls = []
            self.replies = [
                FakeMessage(BOT_PROMPTS["busy_draft"]),
                FakeMessage("Тест удален. Чтобы создать новый, отправьте /newquiz."),
                FakeMessage(BOT_PROMPTS["start_menu"], buttons=[[button]]),
                FakeMessage(BOT_PROMPTS["ask_quiz_name"]),
                FakeMessage(BOT_PROMPTS["ask_description"]),
                FakeMessage(BOT_PROMPTS["ask_first_question"]),
            ]

        async def send_text(self, text):
            self.calls.append(("text", text))
            return object()

        async def wait_reply(self):
            self.calls.append(("wait",))
            return self.replies.pop(0)

        async def click(self, msg, *, text=None, index=None):
            self.calls.append(("click", text, index))

    monkeypatch.setattr(flow.config, "rand_delay", lambda rng: 0)
    client = FakeClient()

    asyncio.run(create_quiz(client, "Retry quiz"))

    assert client.calls[0] == ("text", "/start")
    assert client.calls[2] == ("text", "/cancel")
    assert client.calls[4] == ("text", "/start")
    assert client.calls[6] == ("click", BTN_CREATE_NEW_QUIZ, None)
