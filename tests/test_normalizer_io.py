import json

from backend.normalizer_io import (
    build_report,
    load_existing_results,
    load_v2_dataset,
    merge_clean,
    merge_review,
    resume_state,
    write_json_atomic,
)
from backend.normalizer_models import CleanQuestion, ReviewQuestion


def _clean(source_item_id: int) -> CleanQuestion:
    return CleanQuestion(
        source_item_id=source_item_id,
        question=f"Вопрос {source_item_id}?",
        correct_answer="Сырым Датов",
        options=["Сырым Датов", "Абылай хан", "Касым хан", "Тауке хан"],
        correct=1,
        explanation="Пояснение.",
        explanation_full="Полное пояснение.",
    )


def _review(source_item_id: int, error_reason: str) -> ReviewQuestion:
    return ReviewQuestion(
        source_item_id=source_item_id,
        error_reason=error_reason,
        raw_item={"id": source_item_id},
        last_gpt_output=None,
        attempts=1,
    )


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


def test_resume_state_marks_clean_and_terminal_review_done_but_retries_outage():
    existing_clean = [_clean(1)]
    existing_review = [
        _review(2, "gpt_request_failed"),
        _review(3, "needs_visual_review"),
    ]

    done_ids, carry_review = resume_state(existing_clean, existing_review)

    assert done_ids == {1, 3}
    assert [item.source_item_id for item in carry_review] == [3]


def test_merge_clean_dedupes_by_source_id_newest_wins_and_sorts():
    existing = [_clean(3), _clean(1)]
    new = [_clean(1), _clean(2)]
    new[0] = new[0].model_copy(update={"question": "Обновлённый вопрос?"})

    merged = merge_clean(existing, new)

    assert [item.source_item_id for item in merged] == [1, 2, 3]
    assert merged[0].question == "Обновлённый вопрос?"


def test_merge_review_dedupes_by_source_id_and_sorts():
    existing = [_review(3, "needs_visual_review")]
    new = [_review(2, "max_retries_exceeded")]

    merged = merge_review(existing, new)

    assert [item.source_item_id for item in merged] == [2, 3]


def test_load_existing_results_returns_empty_when_files_absent(tmp_path):
    existing_clean, existing_review = load_existing_results(
        tmp_path / "missing_clean.json",
        tmp_path / "missing_review.json",
    )

    assert existing_clean == []
    assert existing_review == []


def test_load_existing_results_roundtrips_written_questions(tmp_path):
    output = tmp_path / "clean.json"
    review = tmp_path / "review.json"
    write_json_atomic(output, {"questions": [_clean(1).model_dump()]})
    write_json_atomic(review, {"questions": [_review(2, "gpt_request_failed").model_dump()]})

    existing_clean, existing_review = load_existing_results(output, review)

    assert [item.source_item_id for item in existing_clean] == [1]
    assert [item.source_item_id for item in existing_review] == [2]
