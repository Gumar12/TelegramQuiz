from backend.parsers.google_docx_prepare import prepare_google_docx
from backend.pipeline.document_ir import BoldSpan, DocumentBlock, DocumentIR


def p(text, *, block_id=None, bold=False, page_break_before=False, kind="paragraph"):
    block_id = block_id or f"p-{abs(hash((text, page_break_before, kind))) % 100000}"
    spans = [BoldSpan(start=0, end=len(text), text=text)] if bold else []
    return DocumentBlock(
        block_id=block_id,
        kind=kind,
        text=text,
        bold_spans=spans,
        page_break_before=page_break_before,
        source_ref={"block_id": block_id},
    )


def img(path="media/image_001.png", *, block_id="img-1"):
    return DocumentBlock(
        block_id=block_id,
        kind="image",
        media_refs=[path],
        source_ref={"block_id": block_id},
    )


def ir(*blocks):
    return DocumentIR(source_id="source.docx", blocks=list(blocks))


def issue_codes(result):
    return [issue.code for issue in result.issues]


def test_prepare_bold_answer_question():
    result = prepare_google_docx(
        ir(
            p("Кто основал Казахское ханство?"),
            p("A) Абылай хан"),
            p("B) Керей и Жанибек", bold=True),
            p("C) Кенесары хан"),
            p("D) Тауке хан"),
        )
    )

    question = result.questions[0]
    assert result.question_count == 1
    assert question.answers == [2]
    assert question.mode == "single"
    assert question.answer_source == "bold_option"
    assert "#A*\nКерей и Жанибек" in result.prepared_markdown
    assert result.broken_questions == []


def test_prepare_answer_line_question():
    result = prepare_google_docx(
        ir(
            p("Столица Казахстана:"),
            p("A) Алматы"),
            p("B) Астана"),
            p("C) Шымкент"),
            p("D) Актобе"),
            p("Ответ: B"),
        )
    )

    question = result.questions[0]
    assert question.answers == [2]
    assert question.answer_source == "answer_line"
    assert question.options[1].correct is True


def test_prepare_mixed_answer_styles_same_doc():
    result = prepare_google_docx(
        ir(
            p("Первый вопрос:"),
            p("A) Один", bold=True),
            p("B) Два"),
            p("Второй вопрос:"),
            p("A) Алматы"),
            p("B) Астана"),
            p("Ответ: B"),
        )
    )

    assert result.question_count == 2
    assert [question.answers for question in result.questions] == [[1], [2]]


def test_prepare_conflict_blocks_question():
    result = prepare_google_docx(
        ir(
            p("Столица Казахстана:"),
            p("A) Алматы"),
            p("B) Астана", bold=True),
            p("C) Шымкент"),
            p("Ответ: C"),
        )
    )

    assert result.requires_review is True
    assert "answer_bold_and_line_conflict" in issue_codes(result)
    broken = result.broken_questions[0]
    assert broken.question_text == "Столица Казахстана"
    assert broken.issue_code == "answer_bold_and_line_conflict"
    assert broken.options[1]["text"] == "Астана"
    assert broken.answer_evidence["answer_line_raw"] == "Ответ: C"


def test_heading_title_not_question():
    result = prepare_google_docx(
        ir(
            p("Тимур", kind="heading"),
            p("На портрете изображен:"),
            p("A) Абылай"),
            p("B) Эмир Тимур", bold=True),
        )
    )

    assert result.titles == [{"text": "Тимур", "source_ref": {"block_id": result.titles[0]["source_ref"]["block_id"]}}]
    assert result.questions[0].title == "Тимур"
    assert result.questions[0].question == "На портрете изображен"


def test_image_and_text_context_scope():
    result = prepare_google_docx(
        ir(
            p("Текст о Тимуре."),
            img("media/timur.png"),
            p("На портрете изображен:"),
            p("A) Абылай"),
            p("B) Эмир Тимур", bold=True),
        )
    )

    context = result.contexts[0]
    assert context.text == "Текст о Тимуре."
    assert context.media == ["media/timur.png"]
    assert result.questions[0].context_id == context.id


def test_new_standalone_image_closes_old_context():
    result = prepare_google_docx(
        ir(
            p("Контекст 1"),
            p("Вопрос 1:"),
            p("A) Один", bold=True),
            p("B) Два"),
            img("media/new.png", block_id="img-2"),
            p("Вопрос 2:"),
            p("A) Три", bold=True),
            p("B) Четыре"),
        )
    )

    assert len(result.contexts) == 2
    assert result.contexts[0].text == "Контекст 1"
    assert result.contexts[1].media == ["media/new.png"]
    assert result.questions[0].context_id == result.contexts[0].id
    assert result.questions[1].context_id == result.contexts[1].id


def test_page_break_inside_context():
    result = prepare_google_docx(
        ir(
            p("Первая часть контекста."),
            p("Вторая часть контекста.", page_break_before=True),
            p("Вопрос:"),
            p("A) Один", bold=True),
            p("B) Два"),
        )
    )

    assert result.contexts[0].text == "Первая часть контекста.\nВторая часть контекста."
    assert "context_continued_across_page_break" in issue_codes(result)


def test_page_break_between_blocks_blocks_leak():
    result = prepare_google_docx(
        ir(
            p("Контекст"),
            p("Вопрос 1:"),
            p("A) Один", bold=True),
            p("B) Два"),
            p("Вопрос 2:", page_break_before=True),
            p("A) Три", bold=True),
            p("B) Четыре"),
        )
    )

    assert "context_leak_blocked_by_page_break" in issue_codes(result)
    assert result.questions[1].context_id is None


def test_page_break_inside_question_options():
    result = prepare_google_docx(
        ir(
            p("Вопрос:"),
            p("A) Один", page_break_before=True, bold=True),
            p("B) Два"),
        )
    )

    assert "question_split_by_page_break" in issue_codes(result)
    assert result.broken_questions[0].issue_code == "question_split_by_page_break"


def test_answer_line_full_text_report():
    result = prepare_google_docx(
        ir(
            p("Столица Казахстана:"),
            p("A) Алматы"),
            p("B) Астана"),
            p("Ответ: Астана"),
        )
    )

    assert result.broken_questions[0].issue_code == "answer_line_not_letter"


def test_mixed_visual_labels_ambiguous_report():
    result = prepare_google_docx(
        ir(
            p("На какой реке была Орда?"),
            p("A) Урал"),
            p("А) Иртыш"),
            p("B) Ишим"),
            p("В) Тобол"),
            p("Ответ: Б"),
        )
    )

    assert "answer_label_ambiguous_alphabet" in issue_codes(result)
    assert result.broken_questions[0].issue_code == "answer_label_ambiguous_alphabet"


def test_mojibake_blocks_affected_question():
    result = prepare_google_docx(
        ir(
            p("РџСЂРёРІРµС‚:"),
            p("A) Один", bold=True),
            p("B) Два"),
        )
    )

    assert "text_mojibake_detected" in issue_codes(result)
    assert result.broken_questions[0].issue_code == "text_mojibake_detected"

def test_mojibake_context_blocks_affected_question():
    result = prepare_google_docx(
        ir(
            p("РџР»РѕС…РѕР№ РєРѕРЅС‚РµРєСЃС‚"),
            p("Вопрос:"),
            p("A) Один", bold=True),
            p("B) Два"),
        )
    )

    assert "text_mojibake_detected" in issue_codes(result)
    assert result.broken_questions[0].issue_code == "text_mojibake_detected"
    assert result.broken_questions[0].question_text == "Вопрос"

def test_option_prefixed_question_splits_adjacent_question_group():
    result = prepare_google_docx(
        ir(
            p("В период данного события произошло:"),
            p("A) несогласие и нападение на Абулхаира", bold=True),
            p("B) строительство крепостей"),
            p("C) возвращение казахских земель"),
            p("D) свержение хана Нуралы с поста"),
            p("А) Тевкелев был отправлен делегацией в Младший жуз по поручению:"),
            p("A) Екатерины Великой"),
            p("B) Анны Иоанновны", bold=True),
            p("C) Елизаветы II"),
            p("D) Анны Леопольдовны"),
        )
    )

    assert result.question_count == 2
    assert result.questions[0].answers == [1]
    assert len(result.questions[0].options) == 4
    assert result.questions[1].question == "Тевкелев был отправлен делегацией в Младший жуз по поручению"
    assert result.questions[1].answers == [2]
    assert len(result.questions[1].options) == 4


def test_matching_statement_lines_become_question_text_not_answer_options():
    result = prepare_google_docx(
        ir(
            p("1. Оренбургское; 2. Уральское; 3. Семиреченское; 4. Сибирское."),
            p("А) Возникли стихийно в северо-западной части территории Казахстана;"),
            p("Б) Занимались охраной южной и юго-восточной части губернии;"),
            p("В) Занимались охраной границ от набегов джунгар и казахов;"),
            p("Г) Было образовано из 9-го и 10-го полковых округов."),
            p("A) 1-Б, 2-А, 3-Г, 4-В", bold=True),
            p("B) 1-В, 2-Б, 3-А, 4-Г"),
            p("C) 1-А, 2-Г, 3-Б, 4-В"),
            p("D) 1-Г, 2-В, 3-А, 4-Б"),
        )
    )

    question = result.questions[0]
    assert result.question_count == 1
    assert "А) Возникли стихийно" in question.question
    assert [option.text for option in question.options] == [
        "1-Б, 2-А, 3-Г, 4-В",
        "1-В, 2-Б, 3-А, 4-Г",
        "1-А, 2-Г, 3-Б, 4-В",
        "1-Г, 2-В, 3-А, 4-Б",
    ]
    assert question.answers == [1]
    assert "option_label_scheme_mixed" not in issue_codes(result)
