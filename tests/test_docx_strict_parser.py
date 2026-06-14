from backend.parsers.docx_strict import parse_prepared_markdown
from backend.parsers.google_docx_prepare import prepare_google_docx
from backend.pipeline.document_ir import BoldSpan, DocumentBlock, DocumentIR


def issue_codes(result):
    return [issue.code for issue in result.issues]


def test_parse_prepared_section_context_media_question():
    result = parse_prepared_markdown(
        """#SECTION: Тимур

#CONTEXT
![media](media/timur.png)
Текст о Тимуре.
#END_CONTEXT

#Q
На портрете изображен:
#A
Абулхаир Шайбани
#A*
Эмир Тимур
#END_Q
""",
        source_id="prepared.md",
    )

    assert result.has_errors is False
    assert [item.type for item in result.items] == ["title", "context", "question"]
    assert result.items[0].text == "Тимур"
    assert result.items[1].media == ["media/timur.png"]
    assert result.items[1].text == "Текст о Тимуре."
    question = result.questions[0]
    assert question.question == "На портрете изображен:"
    assert [option.text for option in question.options] == ["Абулхаир Шайбани", "Эмир Тимур"]
    assert question.answers == [2]
    assert question.mode == "single"
    assert question.context_id == result.items[1].context_id


def test_parse_prepared_multiple_correct_answers():
    result = parse_prepared_markdown(
        """#Q
Выберите верные утверждения:
#A*
Первое
#A
Второе
#A*
Третье
#END_Q
"""
    )

    question = result.questions[0]
    assert question.answers == [1, 3]
    assert question.mode == "multiple"


def test_section_and_reset_context_clear_active_context():
    result = parse_prepared_markdown(
        """#CONTEXT
Общий контекст
#END_CONTEXT
#Q
Вопрос 1
#A*
Да
#A
Нет
#END_Q
#RESET_CONTEXT
#Q
Вопрос 2
#A*
Да
#A
Нет
#END_Q
#SECTION: Новая тема
#Q
Вопрос 3
#A*
Да
#A
Нет
#END_Q
"""
    )

    assert [question.context_id for question in result.questions] == ["ctx-0001", None, None]
    assert [item.type for item in result.items].count("reset_context") == 1


def test_question_without_correct_answer_reports_error():
    result = parse_prepared_markdown(
        """#Q
Вопрос
#A
Один
#A
Два
#END_Q
"""
    )

    assert result.has_errors is True
    assert "answer_missing" in issue_codes(result)


def test_too_few_options_and_empty_option_report_errors():
    result = parse_prepared_markdown(
        """#Q
Вопрос
#A*
#END_Q
"""
    )

    assert "too_few_options" in issue_codes(result)
    assert "option_text_empty" in issue_codes(result)


def test_unknown_marker_and_text_outside_block_report_errors():
    result = parse_prepared_markdown(
        """Свободный текст
#GROUP: Старый маркер
"""
    )

    assert "strict_text_outside_block" in issue_codes(result)
    assert "strict_unknown_marker" in issue_codes(result)


def test_unclosed_context_and_question_report_errors():
    context_result = parse_prepared_markdown("""#CONTEXT
Текст
""")
    question_result = parse_prepared_markdown("""#Q
Вопрос
#A*
Один
#A
Два
""")

    assert "strict_context_missing_end" in issue_codes(context_result)
    assert "strict_question_missing_end" in issue_codes(question_result)


def test_parse_google_docx_prepared_markdown_output():
    ir = DocumentIR(
        source_id="source.docx",
        blocks=[
            DocumentBlock(block_id="h1", kind="heading", text="Тимур", source_ref={"block_id": "h1"}),
            DocumentBlock(block_id="q1", kind="paragraph", text="На портрете изображен:", source_ref={"block_id": "q1"}),
            DocumentBlock(block_id="a1", kind="paragraph", text="A) Абылай", source_ref={"block_id": "a1"}),
            DocumentBlock(
                block_id="a2",
                kind="paragraph",
                text="B) Эмир Тимур",
                bold_spans=[BoldSpan(start=0, end=14, text="B) Эмир Тимур")],
                source_ref={"block_id": "a2"},
            ),
        ],
    )
    prepared = prepare_google_docx(ir)
    result = parse_prepared_markdown(prepared.prepared_markdown)

    assert result.has_errors is False
    assert result.items[0].type == "title"
    assert result.questions[0].answers == [2]

def test_strict_parser_reports_mojibake_text():
    result = parse_prepared_markdown(
        """#Q
РџР»РѕС…РѕР№ С‚РµРєСЃС‚
#A*
Один
#A
Два
#END_Q
"""
    )

    assert "text_mojibake_detected" in issue_codes(result)
    assert result.has_errors is True
