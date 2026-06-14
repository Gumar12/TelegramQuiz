import json

from backend.parsers.docx_strict import parse_prepared_markdown
from backend.pipeline.clean_quiz import build_clean_quiz


FORBIDDEN_CLEAN_KEYS = {
    "language",
    "source_ref",
    "parse_meta",
    "raw_label",
    "answer_source",
    "label_scheme",
    "raw_option_labels",
    "id",
    "context_id",
    "section_id",
}


def parse_artifacts(text, **kwargs):
    return build_clean_quiz(parse_prepared_markdown(text, source_id="prepared.md"), **kwargs)


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def test_builds_minimal_clean_quiz_title_settings_items():
    artifacts = parse_artifacts(
        """#SECTION: Тимур
#Q
На портрете изображен:
#A
Абулхаир
#A*
Эмир Тимур
#END_Q
""",
        title="История Казахстана",
    )

    clean = artifacts.clean_json
    assert clean["title"] == "История Казахстана"
    assert clean["settings"] == {
        "time_limit": "30 sec",
        "shuffle_options": True,
        "context_send_mode": "per-question",
    }
    assert [item["type"] for item in clean["items"]] == ["title", "question"]


def test_single_answer_maps_to_answers_array_and_single_mode():
    artifacts = parse_artifacts(
        """#Q
Столица Казахстана:
#A
Алматы
#A*
Астана
#END_Q
"""
    )

    question = artifacts.clean_json["items"][0]
    assert question["answers"] == [2]
    assert question["mode"] == "single"
    assert question["options"] == [{"text": "Алматы"}, {"text": "Астана"}]


def test_multiple_answers_preserve_1_based_positions_and_multiple_mode():
    artifacts = parse_artifacts(
        """#Q
Выберите верные:
#A*
Первое
#A
Второе
#A*
Третье
#END_Q
"""
    )

    question = artifacts.clean_json["items"][0]
    assert question["answers"] == [1, 3]
    assert question["mode"] == "multiple"


def test_context_item_holds_text_and_media_without_audit_fields():
    artifacts = parse_artifacts(
        """#CONTEXT
![media](media/timur.png)
Текст контекста
#END_CONTEXT
#Q
Вопрос
#A*
Да
#A
Нет
#END_Q
"""
    )

    context = artifacts.clean_json["items"][0]
    assert context == {"type": "context", "text": "Текст контекста", "media": ["media/timur.png"]}
    for node in walk_dicts(artifacts.clean_json):
        assert not (FORBIDDEN_CLEAN_KEYS & set(node))


def test_title_and_reset_context_do_not_generate_upload_questions():
    artifacts = parse_artifacts(
        """#SECTION: Тимур
#RESET_CONTEXT
#Q
Вопрос
#A*
Да
#A
Нет
#END_Q
"""
    )

    clean = artifacts.clean_json
    assert [item["type"] for item in clean["items"]] == ["title", "reset_context", "question"]
    assert artifacts.audit_json["question_count"] == 1
    assert len(artifacts.audit_json["question_refs"]) == 1


def test_audit_contains_source_refs_and_parser_decisions_not_clean():
    artifacts = parse_artifacts(
        """#SECTION: Тема
#CONTEXT
Контекст
#END_CONTEXT
#Q
Вопрос
#A*
Один
#A
Два
#END_Q
"""
    )

    audit = artifacts.audit_json
    assert audit["parser_strategy"] == "docx-strict-template"
    assert audit["sections"][0]["source_ref"]["line"] == 1
    assert audit["context_scopes"][0]["source_ref"]["line"] == 2
    question_ref = audit["question_refs"][0]
    assert question_ref["answer_source"] == "strict_marker"
    assert question_ref["source_ref"]["line"] == 5
    assert question_ref["option_refs"][0]["correct"] is True
    for node in walk_dicts(artifacts.clean_json):
        assert "source_ref" not in node
        assert "answer_source" not in node


def test_invalid_settings_go_to_report_not_executable_logic():
    artifacts = parse_artifacts(
        """#Q
Вопрос
#A*
Да
#A
Нет
#END_Q
""",
        settings={
            "context_send_mode": "eval('x')",
            "shuffle_options": "yes",
            "regex_rule": ".*",
        },
    )

    assert artifacts.has_errors is True
    codes = [issue.code for issue in artifacts.issues]
    assert "settings_context_send_mode_invalid" in codes
    assert "settings_shuffle_options_invalid" in codes
    assert "settings_unknown_key" in codes
    assert "regex_rule" not in artifacts.clean_json["settings"]


def test_write_outputs_utf8_readable_json(tmp_path):
    artifacts = parse_artifacts(
        """#Q
Кто изображен?
#A
Абылай
#A*
Эмир Тимур
#END_Q
""",
        title="Қазақ тарихы",
    )

    clean_path, audit_path = artifacts.write(tmp_path / "quiz.clean.json", tmp_path / "quiz.audit.json")
    raw = clean_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert "Қазақ тарихы" in clean_path.read_text(encoding="utf-8")
    assert json.loads(clean_path.read_text(encoding="utf-8"))["items"][0]["answers"] == [2]
    assert json.loads(audit_path.read_text(encoding="utf-8"))["question_count"] == 1