import sys

from backend import main


def test_parse_args_defaults_to_sending_context_once(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--file", "quiz.json", "--name", "Quiz"],
    )

    args = main.parse_args()

    assert args.context_send_mode == "once"

