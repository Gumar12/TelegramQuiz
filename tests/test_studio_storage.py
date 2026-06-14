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


def test_save_group_converts_correct_index_to_one_based_and_preserves_metadata(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()

    studio_storage.save_group(
        "sample",
        {
            "id": "sample",
            "name": "Sample",
            "description": "Edited",
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
                }
            ],
        },
        quizzes_dir,
    )

    payload = json.loads((quizzes_dir / "sample.json").read_text(encoding="utf-8"))
    assert payload["quiz_title"] == "Sample"
    assert payload["quiz_description"] == "Edited"
    assert payload["questions"][0]["correct"] == 2
    assert payload["questions"][0]["source_item_id"] == 10
    assert payload["questions"][0]["media"] == ["media/image.jpg"]

