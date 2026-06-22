import json
from pathlib import Path

from backend import studio_storage


def test_list_groups_reads_quiz_json_files(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "19_мая_УТРО.json").write_text(
        json.dumps(
            {
                "quiz_title": "19 мая УТРО",
                "quiz_description": "Morning quiz",
                "questions": [
                    {
                        "question": "Who?",
                        "options": ["A", "B", "C", "D"],
                        "correct": 2,
                        "explanation": "Because B.",
                        "needs_distractor_review": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (quizzes_dir / "19_мая_УТРО_review.json").write_text(
        json.dumps({"questions": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    groups = studio_storage.list_groups(quizzes_dir)

    assert len(groups) == 1
    assert groups[0]["id"] == "19_мая_УТРО"
    assert groups[0]["name"] == "19 мая УТРО"
    assert groups[0]["description"] == "Morning quiz"
    assert groups[0]["questions_count"] == 1


def test_load_group_converts_correct_index_to_zero_based(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "allow_duplicate_questions": True,
                "questions": [
                    {
                        "source_item_id": 10,
                        "context_title": "Context",
                        "context": "Read this.",
                        "media": ["media/image.jpg"],
                        "question": "Who?",
                        "options": ["A", "B", "C", "D"],
                        "correct": 2,
                        "explanation": "Because B.",
                        "needs_distractor_review": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    group = studio_storage.load_group("sample", quizzes_dir)

    assert group["questions"][0]["correct"] == 1
    assert group["questions"][0]["backend_correct"] == 2
    assert group["questions"][0]["media"] == ["media/image.jpg"]
    assert group["questions"][0]["needs_distractor_review"] is True
    assert group["allow_duplicate_questions"] is True


def test_load_group_marks_long_options_as_review(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "questions": [
                    {
                        "question": "Who?",
                        "options": ["A", "B", "C", "D" * 101],
                        "correct": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    group = studio_storage.load_group("sample", quizzes_dir)

    assert group["status"] == "review"


def test_save_group_converts_correct_index_to_one_based_and_preserves_metadata(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()

    studio_storage.save_group(
        "sample",
        {
            "id": "sample",
            "name": "Sample",
            "description": "Edited",
            "allow_duplicate_questions": True,
            "questions": [
                {
                    "id": "10",
                    "source_item_id": 10,
                    "date": "19 мая",
                    "section": "УТРО",
                    "context_title": "Context",
                    "context": "Read this.",
                    "media": ["media/image.jpg"],
                    "question": "Who?",
                    "options": ["A", "B", "C", "D"],
                    "correct": 1,
                    "explanation": "Because B.",
                    "type": "simple_quiz",
                    "source": "gpt_normalized",
                    "needs_distractor_review": True,
                    "warnings": ["Проверьте контекст"],
                }
            ],
        },
        quizzes_dir,
    )

    payload = json.loads((quizzes_dir / "sample.json").read_text(encoding="utf-8"))
    assert payload["quiz_title"] == "Sample"
    assert payload["quiz_description"] == "Edited"
    assert payload["allow_duplicate_questions"] is True
    assert payload["questions"][0]["correct"] == 2
    assert payload["questions"][0]["source_item_id"] == 10
    assert payload["questions"][0]["media"] == ["media/image.jpg"]
    assert payload["questions"][0]["needs_distractor_review"] is True
    assert payload["questions"][0]["warnings"] == ["Проверьте контекст"]


def test_delete_group_removes_quiz_file(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps({"quiz_title": "Sample", "questions": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = studio_storage.delete_group("sample", quizzes_dir)

    assert result == {"id": "sample", "deleted": True}
    assert not (quizzes_dir / "sample.json").exists()


def test_archive_group_moves_quiz_out_of_active_list(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps({"quiz_title": "Sample", "questions": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = studio_storage.archive_group("sample", quizzes_dir)

    archived_path = Path(result["path"])
    assert result["id"] == "sample"
    assert result["archived"] is True
    assert not (quizzes_dir / "sample.json").exists()
    assert archived_path == quizzes_dir / "_archive" / "sample.json"
    assert archived_path.exists()
    assert studio_storage.list_groups(quizzes_dir) == []


def test_import_group_payload_saves_ready_quiz_json(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()

    group = studio_storage.import_group_payload(
        "imported",
        {
            "quiz_title": "Imported quiz",
            "questions": [
                {
                    "question": "Capital?",
                    "options": ["Astana", "Almaty", "Shymkent"],
                    "correct": 1,
                }
            ],
        },
        quizzes_dir,
    )

    assert group["id"] == "imported"
    assert group["name"] == "Imported quiz"
    assert group["questions"][0]["question"] == "Capital?"
    assert group["questions"][0]["correct"] == 0


def test_import_group_payload_converts_clean_items_json(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()

    group = studio_storage.import_group_payload(
        "clean_import",
        {
            "title": "Clean import",
            "items": [
                {"type": "context", "text": "Read this context.", "media": ["media/context.jpg"]},
                {
                    "type": "question",
                    "question": "Who?",
                    "options": [{"text": "A"}, {"text": "B"}, {"text": "C"}],
                    "answers": [2],
                    "explanation": "Because B.",
                },
            ],
        },
        quizzes_dir,
    )

    question = group["questions"][0]
    assert group["name"] == "Clean import"
    assert question["context"] == "Read this context."
    assert question["media"] == ["media/context.jpg"]
    assert question["options"] == ["A", "B", "C"]
    assert question["correct"] == 1


def test_import_group_payload_rejects_block_markup_without_text(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()

    try:
        studio_storage.import_group_payload(
            "markup",
            {
                "document_id": "doc",
                "questions": [
                    {
                        "id": "q001",
                        "question_block_ids": ["b0001"],
                        "option_block_ids": ["b0002", "b0003"],
                        "correct_option_block_ids": ["b0002"],
                    }
                ],
            },
            quizzes_dir,
        )
    except ValueError as exc:
        assert "block references" in str(exc)
    else:
        raise AssertionError("block markup without text must be rejected")


def test_import_group_payload_converts_block_markup_with_text(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()

    group = studio_storage.import_group_payload(
        "markup",
        {
            "document_id": "Marked document",
            "blocks": [
                {"id": "b001", "text": "Read context."},
                {"id": "b002", "text": "Question?"},
                {"id": "b003", "text": "A"},
                {"id": "b004", "text": "B"},
                {"id": "b005", "text": "C"},
            ],
            "context_regions": [
                {
                    "id": "ctx001",
                    "block_ids": ["b001"],
                    "applies_to_question_ids": ["q001"],
                }
            ],
            "questions": [
                {
                    "id": "q001",
                    "question_block_ids": ["b002"],
                    "option_block_ids": ["b003", "b004", "b005"],
                    "correct_option_block_ids": ["b004"],
                    "warnings": ["check manually"],
                }
            ],
        },
        quizzes_dir,
    )

    question = group["questions"][0]
    assert group["name"] == "Marked document"
    assert question["context"] == "Read context."
    assert question["question"] == "Question?"
    assert question["options"] == ["A", "B", "C"]
    assert question["correct"] == 1
    assert question["quality_flags"] == ["check manually"]
