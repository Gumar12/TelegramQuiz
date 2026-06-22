import json

from backend.pipeline.validation import validate_clean_quiz, validate_clean_quiz_file


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
        "answers": [2] if answers is None else answers,
        "mode": mode,
    }
    item.update(extra)
    return item


def codes(report):
    return [issue.code for issue in report.issues]


def test_valid_clean_quiz_produces_no_hard_errors():
    report = validate_clean_quiz(
        clean_quiz(
            [
                {"type": "title", "text": "Тема"},
                {"type": "context", "text": "Контекст", "media": ["missing.png"]},
                question("Столица Казахстана?"),
                {"type": "reset_context"},
            ]
        )
    )

    assert report.question_count == 1
    assert report.hard_errors == []
    assert report.warnings == []
    assert report.quiz_file_hash.startswith("sha256:")


def test_missing_answer_and_out_of_range_answer_block_affected_questions():
    report = validate_clean_quiz(
        clean_quiz(
            [
                question("Нет ответа?", answers=[]),
                question("Ответ вне диапазона?", answers=[5]),
            ]
        )
    )

    assert "answer_missing" in codes(report)
    assert "answer_index_out_of_range" in codes(report)
    affected = {(issue.code, issue.source_question_index) for issue in report.hard_errors}
    assert ("answer_missing", 1) in affected
    assert ("answer_index_out_of_range", 2) in affected


def test_schema_content_errors_cover_empty_option_duplicates_and_mode_conflict():
    report = validate_clean_quiz(
        clean_quiz(
            [
                question(
                    "Сломанный вопрос?",
                    options=[{"text": ""}],
                    answers=[1, 1],
                    mode="single",
                )
            ]
        )
    )

    assert {"option_text_empty", "too_few_options", "answer_index_duplicate"}.issubset(
        set(codes(report))
    )


def test_duplicate_question_text_creates_warning_with_send_both_action():
    report = validate_clean_quiz(
        clean_quiz(
            [
                question("Причина декабрьских событий?"),
                question("  причина декабрьских событий?  "),
            ]
        )
    )

    assert report.hard_errors == []
    assert [issue.code for issue in report.warnings] == ["possible_duplicate_question"]
    warning = report.warnings[0]
    assert warning.source_question_index == 2
    assert "send_both" in warning.actions
    assert warning.evidence["matched_question_indexes"] == [1]


def test_duplicate_question_warning_can_be_disabled_per_quiz():
    quiz = clean_quiz(
        [
            question("Одинаковый вопрос?"),
            question("Одинаковый вопрос?"),
        ]
    )
    quiz["allow_duplicate_questions"] = True

    report = validate_clean_quiz(quiz)

    assert report.hard_errors == []
    assert report.warnings == []


def test_media_path_existence_is_checked_only_when_base_dir_is_supplied(tmp_path):
    quiz = clean_quiz(
        [
            {"type": "context", "text": "Контекст", "media": ["media/existing.png"]},
            question("Вопрос с media?", media=["media/missing.png"]),
        ]
    )
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "existing.png").write_bytes(b"fake")

    report_without_base = validate_clean_quiz(quiz)
    report_with_base = validate_clean_quiz(quiz, media_base_dir=tmp_path)

    assert "media_missing" not in codes(report_without_base)
    missing = [issue for issue in report_with_base.hard_errors if issue.code == "media_missing"]
    assert len(missing) == 1
    assert missing[0].source_question_index == 1


def test_media_base_dir_can_point_to_media_folder_with_prefixed_paths(tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "existing.png").write_bytes(b"fake")
    quiz = clean_quiz(
        [
            {"type": "context", "text": "Контекст", "media": ["media/existing.png"]},
            question("Вопрос с media?", media=["existing.png"]),
        ]
    )

    report = validate_clean_quiz(quiz, media_base_dir=media_dir)

    assert "media_missing" not in codes(report)


def test_media_validation_requires_image_file_under_base_dir(tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "folder.png").mkdir()
    (media_dir / "secret.txt").write_text("not an image", encoding="utf-8")
    quiz = clean_quiz(
        [
            {"type": "context", "text": "Контекст", "media": ["media/folder.png"]},
            question("Вопрос с media?", media=["media/secret.txt"]),
        ]
    )

    report = validate_clean_quiz(quiz, media_base_dir=media_dir)

    missing = [issue for issue in report.hard_errors if issue.code == "media_missing"]
    assert len(missing) == 2
    assert {issue.evidence["media"] for issue in missing} == {"media/folder.png", "media/secret.txt"}


def test_quiz_file_hash_is_stable_for_json_formatting(tmp_path):
    quiz = clean_quiz([question("Форматирование не важно?")])
    compact = tmp_path / "compact.json"
    pretty = tmp_path / "pretty.json"
    compact.write_text(json.dumps(quiz, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    pretty.write_text(json.dumps(quiz, ensure_ascii=False, indent=2), encoding="utf-8")

    assert validate_clean_quiz_file(compact).quiz_file_hash == validate_clean_quiz_file(
        pretty
    ).quiz_file_hash
