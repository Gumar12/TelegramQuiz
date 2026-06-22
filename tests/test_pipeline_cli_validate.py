import json

from backend import pipeline_cli


def clean_quiz(items, *, title="История Казахстана"):
    return {
        "title": title,
        "settings": {
            "time_limit": "30 sec",
            "shuffle_options": True,
            "context_send_mode": "per-question",
        },
        "items": items,
    }


def question(text="Вопрос?", *, answers=None):
    return {
        "type": "question",
        "question": text,
        "options": [
            {"text": "Первый"},
            {"text": "Второй"},
            {"text": "Третий"},
        ],
        "answers": [1] if answers is None else answers,
        "mode": "single",
    }


def write_clean_quiz(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_validate_cli_writes_validation_report(tmp_path, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    out_dir = tmp_path / "review"
    write_clean_quiz(quiz_path, clean_quiz([question("Столица Казахстана?")]))

    exit_code = pipeline_cli.run(["validate", "--file", str(quiz_path), "--out", str(out_dir)])

    captured = capsys.readouterr()
    report = read_json(out_dir / "validation-report.json")
    assert exit_code == 0
    assert "Валидация clean JSON завершена" in captured.out
    assert report["question_count"] == 1
    assert report["hard_error_count"] == 0
    assert report["quiz_file_hash"].startswith("sha256:")


def test_validate_cli_exits_nonzero_on_unresolved_hard_errors(tmp_path, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    out_dir = tmp_path / "review"
    write_clean_quiz(quiz_path, clean_quiz([question("Нет ответа?", answers=[])]))

    exit_code = pipeline_cli.run(["validate", "--file", str(quiz_path), "--out", str(out_dir)])

    captured = capsys.readouterr()
    report = read_json(out_dir / "validation-report.json")
    assert exit_code == 1
    assert "Найдены нерешенные блокирующие ошибки" in captured.err
    assert report["hard_error_count"] == 1
    assert report["issues"][0]["message_ru"] == "У вопроса нет правильного ответа."


def test_validate_interactive_can_confirm_warning(tmp_path, monkeypatch, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    out_dir = tmp_path / "review"
    write_clean_quiz(
        quiz_path,
        clean_quiz([question("Одинаковый вопрос?"), question("Одинаковый вопрос?")]),
    )
    answers = iter(["confirm"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    exit_code = pipeline_cli.run(
        ["validate", "--file", str(quiz_path), "--out", str(out_dir), "--interactive"]
    )

    captured = capsys.readouterr()
    decisions = read_json(out_dir / "review-decisions.json")
    assert exit_code == 0
    assert "Вопрос похож на уже встречавшийся вопрос" in captured.out
    assert "Текст вопроса: Одинаковый вопрос?" in captured.out
    assert decisions["quiz_file_hash"] == read_json(out_dir / "validation-report.json")["quiz_file_hash"]
    assert decisions["decisions"][0]["action"] == "confirm"
    assert "python -m backend.pipeline_cli upload --file" in captured.out


def test_validate_interactive_can_send_both_duplicate_warning_group(
    tmp_path, monkeypatch, capsys
):
    quiz_path = tmp_path / "quiz.clean.json"
    out_dir = tmp_path / "review"
    write_clean_quiz(
        quiz_path,
        clean_quiz(
            [
                question("Одинаковый вопрос?"),
                question("Одинаковый вопрос?"),
                question("Одинаковый вопрос?"),
            ]
        ),
    )
    answers = iter(["send_both"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    exit_code = pipeline_cli.run(
        ["validate", "--file", str(quiz_path), "--out", str(out_dir), "--interactive"]
    )

    captured = capsys.readouterr()
    decisions = read_json(out_dir / "review-decisions.json")
    assert exit_code == 0
    assert "Группа предупреждений: possible_duplicate_question" in captured.out
    assert decisions["groups"][0]["action"] == "send_both"
    assert [item["action"] for item in decisions["decisions"]] == ["send_both", "send_both"]


def test_validate_interactive_group_abort_stops_review(tmp_path, monkeypatch, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    out_dir = tmp_path / "review"
    write_clean_quiz(
        quiz_path,
        clean_quiz(
            [
                question("Одинаковый вопрос?"),
                question("Одинаковый вопрос?"),
                question("Одинаковый вопрос?"),
            ]
        ),
    )
    answers = iter(["abort"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    exit_code = pipeline_cli.run(
        ["validate", "--file", str(quiz_path), "--out", str(out_dir), "--interactive"]
    )

    captured = capsys.readouterr()
    decisions = read_json(out_dir / "review-decisions.json")
    assert exit_code == 1
    assert decisions["groups"][0]["action"] == "abort"
    assert "python -m backend.pipeline_cli upload --file" not in captured.out


def test_validate_interactive_can_skip_question_hard_error(tmp_path, monkeypatch, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    out_dir = tmp_path / "review"
    write_clean_quiz(quiz_path, clean_quiz([question("Нет ответа?", answers=[])]))
    original_clean_json = quiz_path.read_text(encoding="utf-8")
    answers = iter(["skip_question"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    exit_code = pipeline_cli.run(
        ["validate", "--file", str(quiz_path), "--out", str(out_dir), "--interactive"]
    )

    captured = capsys.readouterr()
    decisions = read_json(out_dir / "review-decisions.json")
    assert exit_code == 0
    assert "У вопроса нет правильного ответа" in captured.out
    assert decisions["decisions"][0]["action"] == "skip_question"
    assert "Review пройден. Upload разрешен." in captured.out
    assert quiz_path.read_text(encoding="utf-8") == original_clean_json


def test_validate_interactive_treats_changed_quiz_hash_as_stale(
    tmp_path, monkeypatch, capsys
):
    quiz_path = tmp_path / "quiz.clean.json"
    out_dir = tmp_path / "review"
    write_clean_quiz(
        quiz_path,
        clean_quiz([question("Одинаковый вопрос?"), question("Одинаковый вопрос?")]),
    )
    answers = iter(["send_both"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert (
        pipeline_cli.run(
            ["validate", "--file", str(quiz_path), "--out", str(out_dir), "--interactive"]
        )
        == 0
    )
    first_hash = read_json(out_dir / "review-decisions.json")["quiz_file_hash"]

    write_clean_quiz(
        quiz_path,
        clean_quiz(
            [question("Одинаковый вопрос?"), question("Одинаковый вопрос?")],
            title="История Казахстана: исправлено",
        ),
    )
    answers = iter(["send_both"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    exit_code = pipeline_cli.run(
        ["validate", "--file", str(quiz_path), "--out", str(out_dir), "--interactive"]
    )

    captured = capsys.readouterr()
    second_hash = read_json(out_dir / "review-decisions.json")["quiz_file_hash"]
    assert exit_code == 0
    assert "Предыдущие review decisions устарели" in captured.out
    assert second_hash != first_hash


def test_validate_cli_russian_output_and_json_are_readable(tmp_path, monkeypatch, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    out_dir = tmp_path / "review"
    write_clean_quiz(
        quiz_path,
        clean_quiz([question("Одинаковый вопрос?"), question("Одинаковый вопрос?")]),
    )
    answers = iter(["confirm"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    exit_code = pipeline_cli.run(
        ["validate", "--file", str(quiz_path), "--out", str(out_dir), "--interactive"]
    )

    captured = capsys.readouterr()
    report_text = (out_dir / "validation-report.json").read_text(encoding="utf-8")
    assert exit_code == 0
    assert "Валидация clean JSON завершена" in captured.out
    assert "Вопрос похож на уже встречавшийся вопрос." in report_text
    assert "\\u0412" not in report_text
