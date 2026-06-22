import asyncio

from backend import quizbot_client
from backend.quizbot_client import QuizBotClient, _correct_answers, _poll_answer


class _DirectClientMustNotSendFiles:
    async def send_file(self, *args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("file messages must be sent through Conversation")


class _FakeConversation:
    def __init__(self):
        self.sent_files = []

    async def send_file(self, *args, **kwargs):
        self.sent_files.append({"args": args, "kwargs": kwargs})
        return object()


def _client_with_conversation(conversation: _FakeConversation) -> QuizBotClient:
    client = QuizBotClient.__new__(QuizBotClient)
    client._conv = conversation
    client.client = _DirectClientMustNotSendFiles()
    return client


def test_correct_answers_encodes_multiple_int_indexes(monkeypatch):
    monkeypatch.setattr(quizbot_client, "_CORRECT_ANSWERS_ARE_INT", True)

    assert _correct_answers([0, 2]) == [0, 2]


def test_correct_answers_encodes_multiple_byte_indexes(monkeypatch):
    monkeypatch.setattr(quizbot_client, "_CORRECT_ANSWERS_ARE_INT", False)

    assert _correct_answers([0, 2]) == [b"\x00", b"\x02"]


def test_poll_answer_uses_poll_answer_with_stable_option_bytes(monkeypatch):
    monkeypatch.setattr(quizbot_client, "_CORRECT_ANSWERS_ARE_INT", False)

    answer = _poll_answer("A", 2)

    assert answer.__class__.__name__ == "PollAnswer"
    assert answer.option == b"\x02"


def test_poll_answer_uses_input_poll_answer_for_int_correct_answers(monkeypatch):
    monkeypatch.setattr(quizbot_client, "_CORRECT_ANSWERS_ARE_INT", True)

    answer = _poll_answer("A", 2)

    assert answer.__class__.__name__ == "InputPollAnswer"


def test_send_media_uses_conversation_send_file(monkeypatch):
    monkeypatch.setattr(quizbot_client.config, "rand_delay", lambda _: 0)
    conversation = _FakeConversation()
    client = _client_with_conversation(conversation)

    asyncio.run(client.send_media("image.jpg", caption="context"))

    assert conversation.sent_files == [
        {"args": (), "kwargs": {"file": "image.jpg", "caption": "context"}}
    ]


def test_send_quiz_poll_uses_conversation_send_file(monkeypatch):
    monkeypatch.setattr(quizbot_client.config, "rand_delay", lambda _: 0)
    conversation = _FakeConversation()
    client = _client_with_conversation(conversation)

    asyncio.run(
        client.send_quiz_poll(
            "Question?",
            ["A", "B", "C"],
            correct_indexes=1,
            solution="B",
        )
    )

    assert len(conversation.sent_files) == 1
    sent = conversation.sent_files[0]
    assert sent["args"] == ()
    assert sent["kwargs"]["file"].__class__.__name__ == "InputMediaPoll"
    media = sent["kwargs"]["file"]
    assert media.correct_answers == [1]
    assert media.solution == "B"
    assert media.solution_entities == []
    assert [answer.__class__.__name__ for answer in media.poll.answers] == [
        "InputPollAnswer",
        "InputPollAnswer",
        "InputPollAnswer",
    ]
