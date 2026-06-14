from backend import quizbot_client
from backend.quizbot_client import _correct_answers


def test_correct_answers_encodes_multiple_int_indexes(monkeypatch):
    monkeypatch.setattr(quizbot_client, "_CORRECT_ANSWERS_ARE_INT", True)

    assert _correct_answers([0, 2]) == [0, 2]


def test_correct_answers_encodes_multiple_byte_indexes(monkeypatch):
    monkeypatch.setattr(quizbot_client, "_CORRECT_ANSWERS_ARE_INT", False)

    assert _correct_answers([0, 2]) == [b"\x00", b"\x02"]
