import json

from normalizer_io import build_report, load_v2_dataset, write_json_atomic
from normalizer_models import CleanQuestion, ReviewQuestion


def test_load_v2_dataset_reads_questions_fixture():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    assert data["quiz_title"] == "История Казахстана"
    assert len(data["questions"]) == 3
    assert data["questions"][0]["id"] == 1


def test_write_json_atomic_writes_utf8_json(tmp_path):
    target = tmp_path / "out.json"

    write_json_atomic(target, {"text": "История Казахстана"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"text": "История Казахстана"}
    assert not list(tmp_path.glob("*.tmp"))


def test_build_report_counts_review_reasons():
    clean = [
        CleanQuestion(
            source_item_id=1,
            question="Кто возглавил движение?",
            correct_answer="Сырым Датов",
            options=["Сырым Датов", "Абылай хан", "Касым хан", "Тауке хан"],
            correct=1,
            explanation="Движение возглавил Сырым Датов.",
            explanation_full="Движение против колониальной политики возглавил Сырым Датов.",
        )
    ]
    review = [
        ReviewQuestion(
            source_item_id=2,
            error_reason="needs_visual_review",
            raw_item={"id": 2},
            last_gpt_output={},
            attempts=1,
            notes="media-dependent",
        )
    ]

    report = build_report(
        input_path="questions_v2.json",
        output_path="clean_questions.json",
        review_path="review_questions.json",
        model="gpt-4.1-mini",
        max_retries=3,
        total=2,
        clean=clean,
        review=review,
    )

    assert report["items_total"] == 2
    assert report["items_clean"] == 1
    assert report["items_review"] == 1
    assert report["error_reason_counts"] == {"needs_visual_review": 1}
