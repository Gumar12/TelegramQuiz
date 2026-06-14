import json
from argparse import Namespace
from pathlib import Path

from backend import generate_editable_quiz


def test_generate_writes_group_source_and_calls_normalizer(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "full_source.json"
    output_path = tmp_path / "19_morning.json"
    source_path.write_text(
        json.dumps(
            {
                "quiz_title": "Full",
                "quiz_description": "Full source",
                "questions": [
                    {
                        "id": 1,
                        "date": "19 мая",
                        "section": "УТРО",
                        "question": "Question A",
                        "correct_answer": "Answer A",
                    },
                    {
                        "id": 2,
                        "date": "19 мая",
                        "section": "ОБЕД",
                        "question": "Question B",
                        "correct_answer": "Answer B",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    captured: dict[str, Namespace] = {}

    def fake_run(args: Namespace) -> int:
        captured["args"] = args
        return 0

    monkeypatch.setattr(generate_editable_quiz.gpt_normalizer, "run", fake_run)

    exit_code = generate_editable_quiz.generate(
        Namespace(
            source=str(source_path),
            docx=None,
            group="19 мая УТРО",
            output=str(output_path),
            review=None,
            report=None,
            workdir=str(tmp_path / "work"),
            model="gpt-test",
            max_retries=2,
            seed=123,
            media_root=".",
            style_source=None,
            style_examples=5,
            image_detail="high",
            dry_run=False,
        )
    )

    assert exit_code == 0
    group_source = tmp_path / "work" / "19_morning_source.json"
    payload = json.loads(group_source.read_text(encoding="utf-8"))
    assert payload["quiz_title"] == "19 мая УТРО"
    assert [item["id"] for item in payload["questions"]] == [1]

    normalizer_args = captured["args"]
    assert normalizer_args.input == str(group_source)
    assert normalizer_args.output == str(output_path)
    assert normalizer_args.review == str(tmp_path / "19_morning_review.json")
    assert normalizer_args.report == str(tmp_path / "19_morning_report.json")
    assert normalizer_args.style_source == str(source_path)
    assert normalizer_args.style_examples == 5


def test_generate_fails_when_group_missing(tmp_path: Path):
    source_path = tmp_path / "full_source.json"
    source_path.write_text(
        json.dumps({"questions": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = generate_editable_quiz.generate(
        Namespace(
            source=str(source_path),
            docx=None,
            group="19 мая УТРО",
            output=str(tmp_path / "out.json"),
            review=None,
            report=None,
            workdir=str(tmp_path / "work"),
            model="gpt-test",
            max_retries=2,
            seed=123,
            media_root=".",
            style_source=None,
            style_examples=5,
            image_detail="high",
            dry_run=False,
        )
    )

    assert exit_code == 1


def test_generate_all_groups_writes_each_group_and_calls_normalizer(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "full_source.json"
    output_dir = tmp_path / "quizzes"
    source_path.write_text(
        json.dumps(
            {
                "quiz_title": "Full",
                "quiz_description": "Full source",
                "questions": [
                    {
                        "id": 1,
                        "date": "10 мая",
                        "section": "",
                        "question": "Question A",
                        "correct_answer": "Answer A",
                    },
                    {
                        "id": 2,
                        "date": "11 мая",
                        "section": "УТРО",
                        "question": "Question B",
                        "correct_answer": "Answer B",
                    },
                    {
                        "id": 3,
                        "date": "11 мая",
                        "section": "УТРО",
                        "question": "Question C",
                        "correct_answer": "Answer C",
                    },
                    {
                        "id": 4,
                        "date": "11 мая",
                        "section": "ОБЕД",
                        "question": "Question D",
                        "correct_answer": "Answer D",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    captured: list[Namespace] = []

    def fake_run(args: Namespace) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(generate_editable_quiz.gpt_normalizer, "run", fake_run)

    exit_code = generate_editable_quiz.generate(
        Namespace(
            source=str(source_path),
            docx=None,
            all_groups=True,
            output_dir=str(output_dir),
            group=None,
            output=None,
            review=None,
            report=None,
            workdir=str(tmp_path / "work"),
            model="gpt-test",
            max_retries=2,
            seed=123,
            media_root=".",
            style_source=None,
            style_examples=5,
            image_detail="high",
            dry_run=False,
        )
    )

    assert exit_code == 0
    assert [Path(args.output).name for args in captured] == [
        "10_мая.json",
        "11_мая_УТРО.json",
        "11_мая_ОБЕД.json",
    ]

    group_source = tmp_path / "work" / "groups" / "11_мая_УТРО_source.json"
    payload = json.loads(group_source.read_text(encoding="utf-8"))
    assert payload["quiz_title"] == "11 мая УТРО"
    assert [item["id"] for item in payload["questions"]] == [2, 3]

    assert captured[1].input == str(group_source)
    assert captured[1].review == str(output_dir / "11_мая_УТРО_review.json")
    assert captured[1].report == str(output_dir / "11_мая_УТРО_report.json")
    assert captured[1].style_source == str(source_path)
