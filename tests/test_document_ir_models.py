from backend.pipeline.document_ir import BoldSpan, DocumentBlock, DocumentIR
from backend.pipeline.reports import EncodingReport, ReportIssue


def test_report_issue_contract():
    issue = ReportIssue(
        code="context_continued_across_page_break",
        severity="info",
        message_ru="Контекст был разорван разрывом страницы в DOCX и склеен в один блок.",
        action_ru="Проверь, что текст после разрыва страницы относится к тому же контексту.",
        source_ref={"block_id": "p-42"},
        question_id=None,
        context_scope_id="ctx-1",
    )

    data = issue.to_dict()

    assert data["code"] == "context_continued_across_page_break"
    assert data["severity"] == "info"
    assert data["message_ru"].startswith("Контекст")
    assert data["action_ru"].startswith("Проверь")
    assert data["source_ref"]["block_id"] == "p-42"
    assert data["context_scope_id"] == "ctx-1"


def test_document_block_contract():
    block = DocumentBlock(
        block_id="p-1",
        kind="paragraph",
        text="B) Керей и Жанибек",
        style="Normal",
        bold_spans=[BoldSpan(start=3, end=18, text="Керей и Жанибек")],
        blank_before=2,
        page_break_before=True,
        source_ref={"paragraph_index": 0},
    )

    data = block.to_dict()

    assert data["block_id"] == "p-1"
    assert data["kind"] == "paragraph"
    assert data["text_hash"].startswith("sha256:")
    assert data["style"] == "Normal"
    assert data["bold_spans"][0]["text"] == "Керей и Жанибек"
    assert data["blank_before"] == 2
    assert data["page_break_before"] is True
    assert data["source_ref"]["paragraph_index"] == 0


def test_document_ir_preserves_order():
    ir = DocumentIR(
        source_id="source-1",
        blocks=[
            DocumentBlock(block_id="p-1", kind="heading", text="Тимур"),
            DocumentBlock(block_id="img-1", kind="image", media_refs=["media/timur.png"]),
            DocumentBlock(block_id="p-2", kind="paragraph", text="На портрете изображен:"),
        ],
    )

    assert [block["block_id"] for block in ir.to_dict()["blocks"]] == ["p-1", "img-1", "p-2"]


def test_encoding_report_blocks_suspect_text():
    issue = ReportIssue(
        code="text_mojibake_detected",
        severity="error",
        message_ru="Текст выглядит как результат неправильного чтения UTF-8/Windows-1251.",
        action_ru="Открой исходник и повтори импорт через UTF-8, не продолжай upload.",
        source_ref={"block_id": "p-7"},
    )

    report = EncodingReport.from_issues([issue])
    data = report.to_dict()

    assert data["has_suspect_text"] is True
    assert data["blocked"] is True
    assert data["suspect_blocks"] == [
        {"block_id": "p-7", "code": "text_mojibake_detected", "severity": "error"}
    ]
    assert data["issues"][0]["message_ru"].startswith("Текст выглядит")