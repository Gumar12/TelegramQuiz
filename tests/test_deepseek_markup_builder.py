import json
from pathlib import Path

from backend.deepseek_markup_builder import (
    CONTEXT_OVERLAP_AUTOFIX_WARNING,
    SourceBlock,
    SourceBlocks,
    build_quiz_from_files,
    build_quiz_from_markup,
)


def test_build_quiz_from_deepseek_markup_and_blocks_md(tmp_path: Path):
    media_source = tmp_path / "source_media"
    media_source.mkdir()
    (media_source / "image1.png").write_bytes(b"fake")
    blocks = tmp_path / "source.blocks.md"
    blocks.write_text(
        "\n".join(
            [
                "# DOCX_BLOCK_STREAM",
                "document_id: source",
                "",
                "[BLOCK b0001 | paragraph | bold=false]",
                "Контекст источника",
                "",
                "[IMAGE img0001 | after=b0001 | filename=image1.png]",
                "",
                "[BLOCK b0002 | paragraph | bold=false]",
                "Какой город является столицей?",
                "",
                "[BLOCK b0003 | option | label=A | bold=true]",
                "A) Астана",
                "",
                "[BLOCK b0004 | option | label=B | bold=false]",
                "B) Алматы",
                "",
                "[BLOCK b0005 | option | label=C | bold=false]",
                "C) Шымкент",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # The builder auto-detects the media folder next to source.blocks.md.
    (tmp_path / "source_media").mkdir(exist_ok=True)
    (tmp_path / "source_media" / "image1.png").write_bytes(b"fake")

    markup = tmp_path / "markup.json"
    markup.write_text(
        json.dumps(
            {
                "document_id": "source",
                "questions": [
                    {
                        "id": "q001",
                        "question_block_ids": ["b0002"],
                        "option_block_ids": ["b0003", "b0004", "b0005"],
                        "correct_option_block_ids": ["b0003"],
                        "context_block_ids": [],
                        "media_ids": ["img0001"],
                        "confidence": 0.9,
                        "warnings": [],
                    }
                ],
                "context_regions": [
                    {
                        "id": "ctx001",
                        "block_ids": ["b0001"],
                        "applies_to_question_ids": ["q001"],
                        "media_ids": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    quiz = build_quiz_from_files(
        markup_path=markup,
        blocks_path=blocks,
        media_output_dir=tmp_path / "media",
    )

    question = quiz["questions"][0]
    assert quiz["quiz_title"] == "source"
    assert question["question"] == "Какой город является столицей?"
    assert question["context"] == "Контекст источника"
    assert question["options"] == ["Астана", "Алматы", "Шымкент"]
    assert question["correct"] == 1
    assert question["media"] == ["media/image1.png"]
    assert (tmp_path / "media" / "image1.png").exists()


def test_builder_infers_question_between_context_and_options_when_markup_overlaps(tmp_path: Path):
    blocks = tmp_path / "source.blocks.md"
    blocks.write_text(
        "\n".join(
            [
                "# DOCX_BLOCK_STREAM",
                "document_id: source",
                "",
                "[BLOCK b0001 | paragraph | bold=false]",
                "Очень длинный контекст источника",
                "",
                "[BLOCK b0002 | paragraph | bold=false]",
                "Настоящий вопрос?",
                "",
                "[BLOCK b0003 | option | label=A | bold=true]",
                "A) Первый",
                "",
                "[BLOCK b0004 | option | label=B | bold=false]",
                "B) Второй",
                "",
                "[BLOCK b0005 | option | label=C | bold=false]",
                "C) Третий",
                "",
            ]
        ),
        encoding="utf-8",
    )
    markup = tmp_path / "markup.json"
    markup.write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "id": "q001",
                        "question_block_ids": ["b0001"],
                        "context_block_ids": ["b0001"],
                        "option_block_ids": ["b0003", "b0004", "b0005"],
                        "correct_option_block_ids": ["b0003"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    quiz = build_quiz_from_files(markup_path=markup, blocks_path=blocks)

    question = quiz["questions"][0]
    assert question["question"] == "Настоящий вопрос?"
    assert question["context"] == "Очень длинный контекст источника"
    assert CONTEXT_OVERLAP_AUTOFIX_WARNING in question["quality_flags"]


def test_builder_resolves_existing_media_output_from_source_image_ref(tmp_path: Path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "image4.jpg").write_bytes(b"fake-image")
    source = SourceBlocks(
        document_id="source",
        blocks={
            "b0001": SourceBlock("b0001", "paragraph", "Вопрос?"),
            "b0002": SourceBlock("b0002", "option", "A) Верно"),
            "b0003": SourceBlock("b0003", "option", "B) Неверно"),
            "b0004": SourceBlock("b0004", "option", "C) Тоже неверно"),
        },
        images={
            "img0001": SourceBlock("img0001", "image", media_refs=["media/image4.jpg"]),
        },
        order=["b0001", "img0001", "b0002", "b0003", "b0004"],
    )
    markup = {
        "questions": [
            {
                "id": "q001",
                "question_block_ids": ["b0001"],
                "option_block_ids": ["b0002", "b0003", "b0004"],
                "correct_option_block_ids": ["b0002"],
                "media_ids": ["img0001"],
            }
        ],
    }

    quiz = build_quiz_from_markup(markup, source, media_output_dir=media_dir)

    question = quiz["questions"][0]
    assert question["media"] == ["media/image4.jpg"]
    assert not any("missing_source_blocks" in flag for flag in question["quality_flags"])


def test_builder_drops_missing_media_ref_and_flags_it(tmp_path: Path):
    source = SourceBlocks(
        document_id="source",
        blocks={
            "b0001": SourceBlock("b0001", "paragraph", "Вопрос?"),
            "b0002": SourceBlock("b0002", "option", "A) Верно"),
            "b0003": SourceBlock("b0003", "option", "B) Неверно"),
            "b0004": SourceBlock("b0004", "option", "C) Тоже неверно"),
        },
        images={
            "img0001": SourceBlock("img0001", "image", media_refs=["media/missing.jpg"]),
        },
        order=["b0001", "img0001", "b0002", "b0003", "b0004"],
    )
    markup = {
        "questions": [
            {
                "id": "q001",
                "question_block_ids": ["b0001"],
                "option_block_ids": ["b0002", "b0003", "b0004"],
                "correct_option_block_ids": ["b0002"],
                "media_ids": ["img0001"],
            }
        ],
    }

    quiz = build_quiz_from_markup(markup, source, media_output_dir=tmp_path / "media")

    question = quiz["questions"][0]
    assert question["media"] == []
    assert any("missing_source_blocks" in flag and "img0001:media/missing.jpg" in flag for flag in question["quality_flags"])
