import json
from pathlib import Path
from types import SimpleNamespace

from backend import validate_quiz_json


def valid_payload() -> dict[str, object]:
    return {
        "questions": [
            {
                "question": "В марте 1917 года Временное правительство объявило:",
                "options": [
                    "Амнистия участников восстания 1917 г",
                    "Амнистие участников восстания 1916 г",
                    "Амнистия участников восстания 1916 г",
                    "Амнистия участников восстания 1918 г",
                ],
                "correct": 2,
                "explanation": "Амнистие участников восстания 1916 г.",
                "context": "abc",
            }
        ]
    }


def test_build_quality_report_flags_similar_options_and_short_context(tmp_path: Path):
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(valid_payload(), ensure_ascii=False), encoding="utf-8")

    questions, raw_items = validate_quiz_json.load_questions_with_raw(path)
    report = validate_quiz_json.build_quality_report(questions, raw_items)

    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert report["questions_total"] == 1
    assert "similar_options" in warning_codes
    assert "short_context" in warning_codes
    similar_warning = next(warning for warning in report["warnings"] if warning["code"] == "similar_options")
    assert similar_warning["message"] == "Варианты #1 и #2 слишком похожи."
    assert similar_warning["left_option"]["index"] == 1
    assert similar_warning["right_option"]["index"] == 2


def test_build_quality_report_flags_short_context_from_raw_clean_payload(tmp_path: Path):
    payload = valid_payload()
    payload["questions"][0]["context"] = "abc"
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    questions, raw_items = validate_quiz_json.load_questions_with_raw(path)
    report = validate_quiz_json.build_quality_report(questions, raw_items)

    assert any(warning["code"] == "short_context" for warning in report["warnings"])


def test_build_quality_report_flags_context_fragment(tmp_path: Path):
    payload = valid_payload()
    payload["questions"][0]["context"] = "При каком хане действовал свод"
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    questions, raw_items = validate_quiz_json.load_questions_with_raw(path)
    report = validate_quiz_json.build_quality_report(questions, raw_items)

    warning = next(warning for warning in report["warnings"] if warning["code"] == "context_fragment")
    assert warning["message"] == "Контекст похож на обрывок вопроса, а не на полноценный контекст."
    assert warning["context"] == "При каком хане действовал свод"


def test_validate_file_returns_zero_for_schema_valid_file(tmp_path: Path):
    path = tmp_path / "quiz.json"
    payload = valid_payload()
    payload["questions"][0]["context"] = "Достаточно длинный контекст для проверки."
    payload["questions"][0]["options"] = ["1916 год", "1917 год", "1918 год", "1919 год"]
    payload["questions"][0]["correct"] = 1
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert validate_quiz_json.validate_file(path, strict=False) == 0


def test_validate_file_allows_duplicate_questions_when_quiz_flag_enabled(tmp_path: Path):
    question = {
        "question": "Одинаковый текст?",
        "options": ["Первый", "Второй", "Третий", "Четвертый"],
        "correct": 1,
        "context": "Достаточно длинный контекст для проверки.",
    }
    payload = {
        "allow_duplicate_questions": True,
        "questions": [dict(question), dict(question)],
    }
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert validate_quiz_json.validate_file(path, strict=False) == 0


def test_validate_file_blocks_duplicate_questions_without_quiz_flag(tmp_path: Path):
    question = {
        "question": "Одинаковый текст?",
        "options": ["Первый", "Второй", "Третий", "Четвертый"],
        "correct": 1,
        "context": "Достаточно длинный контекст для проверки.",
    }
    payload = {"questions": [dict(question), dict(question)]}
    path = tmp_path / "quiz.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert validate_quiz_json.validate_file(path, strict=False) == 1


def test_configure_stdout_reconfigures_to_utf8(monkeypatch):
    calls = []

    fake_stdout = SimpleNamespace(
        reconfigure=lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(validate_quiz_json.sys, "stdout", fake_stdout)

    validate_quiz_json.configure_stdout()

    assert calls == [{"encoding": "utf-8", "errors": "replace"}]
