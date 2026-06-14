import json
import unicodedata

from backend.pipeline.encoding import (
    detect_suspect_encoding,
    normalize_text,
    write_json_utf8,
    write_text_utf8,
)


def test_normalize_text_nfc_nbsp_and_line_endings():
    text = "Каза\u0301хстан\xa0  тарихы\r\nҚазақ\u202f тілі"

    normalized = normalize_text(text)

    assert unicodedata.is_normalized("NFC", normalized)
    assert normalized == unicodedata.normalize("NFC", "Каза\u0301хстан тарихы\nҚазақ тілі")


def test_detect_replacement_char():
    issues = detect_suspect_encoding("Абай�", source_ref={"block_id": "p-1"})

    assert [issue.code for issue in issues] == ["text_contains_replacement_char"]
    assert issues[0].severity == "error"
    assert issues[0].message_ru
    assert issues[0].action_ru
    assert issues[0].source_ref["block_id"] == "p-1"


def test_detect_mojibake_patterns():
    issues = detect_suspect_encoding("РџСЂРёРІРµС‚")

    assert any(issue.code == "text_mojibake_detected" for issue in issues)


def test_detect_latin_mojibake_patterns():
    issues = detect_suspect_encoding("ÐŸÑ€Ð¸Ð²ÐµÑ‚")

    assert any(issue.code == "text_mojibake_detected" for issue in issues)


def test_detect_mass_question_marks_inside_words():
    issues = detect_suspect_encoding("Қа??ақстан")

    assert any(issue.code == "text_encoding_suspect" for issue in issues)


def test_write_json_utf8_no_bom_ensure_ascii_false(tmp_path):
    out = tmp_path / "quiz.clean.json"

    write_json_utf8(out, {"text": "Қазақ тілі. История"})
    raw = out.read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\\u04" not in raw
    assert json.loads(raw.decode("utf-8"))["text"] == "Қазақ тілі. История"


def test_write_text_utf8_no_bom_lf(tmp_path):
    out = tmp_path / "report.md"

    write_text_utf8(out, "строка 1\r\nстрока 2")
    raw = out.read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8") == "строка 1\nстрока 2"