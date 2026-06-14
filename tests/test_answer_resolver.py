from backend.parsers.answer_resolver import (
    resolve_answer_line,
    resolve_answer_sources,
    resolve_answers,
    resolve_bold_options,
)
from backend.parsers.option_labels import resolve_option_labels


def codes(result):
    return [issue.code for issue in result.issues]


def test_answer_line_single_latin():
    result = resolve_answer_line("Ответ: A", ["A", "B", "C", "D"])

    assert result.positions == [1]
    assert result.mode == "single"
    assert result.raw_labels == ["A"]
    assert result.issues == []


def test_answer_line_single_cyrillic_ve_is_third_option():
    result = resolve_answer_line("Правильный ответ: В", ["А", "Б", "В", "Г"])

    assert result.positions == [3]
    assert result.mode == "single"
    assert result.raw_labels == ["В"]
    assert result.issues == []


def test_answer_line_multiple_comma_and_space_forms():
    labels = ["A", "B", "C", "D"]

    comma = resolve_answer_line("Ответ: A, C", labels)
    space = resolve_answer_line("Ответ: A C", labels)

    assert comma.positions == [1, 3]
    assert comma.mode == "multiple"
    assert space.positions == [1, 3]
    assert space.mode == "multiple"


def test_full_text_answer_line_is_rejected():
    result = resolve_answer_line("Ответ: Урал", ["A", "B", "C", "D"])

    assert result.positions == []
    assert codes(result) == ["answer_line_not_letter"]
    assert result.issues[0].severity == "error"


def test_bold_single_and_multiple():
    single = resolve_bold_options(
        [
            {"text": "Урал"},
            {"text": "Иртыш", "bold": True},
            {"text": "Ишим"},
        ]
    )
    multiple = resolve_bold_options(
        [
            {"text": "Урал", "has_bold": True},
            {"text": "Иртыш"},
            {"text": "Ишим", "is_bold": True},
        ]
    )

    assert single.positions == [2]
    assert single.mode == "single"
    assert multiple.positions == [1, 3]
    assert multiple.mode == "multiple"


def test_bold_and_answer_line_match():
    result = resolve_answer_sources(
        ["A", "B", "C", "D"],
        answer_line="Ответ: A, C",
        bold_positions=[1, 3],
    )

    assert result.answers == [1, 3]
    assert result.mode == "multiple"
    assert result.answer_source == "both_match"
    assert result.is_resolved is True
    assert result.issues == []


def test_bold_and_answer_line_conflict():
    result = resolve_answer_sources(
        ["A", "B", "C", "D"],
        answer_line="Ответ: A",
        bold_positions=[2],
    )

    assert result.answers == []
    assert result.mode == "unknown"
    assert result.answer_source == "conflict"
    assert "answer_bold_and_line_conflict" in codes(result)
    assert result.is_resolved is False


def test_mixed_exact_raw_match_resolves_with_warning():
    label_result = resolve_option_labels(["A", "А", "B", "В"])
    result = resolve_answers(label_result, answer_line="Ответ: В")

    assert result.answers == [4]
    assert result.answer_source == "answer_line"
    assert "option_label_scheme_mixed" in codes(result)
    assert "answer_label_ambiguous_alphabet" not in codes(result)
    assert result.is_resolved is True


def test_mixed_non_match_returns_ambiguous_error_without_guessing():
    label_result = resolve_option_labels(["A", "А", "B", "В"])
    result = resolve_answers(label_result, answer_line="Ответ: Б")

    assert result.answers == []
    assert "option_label_scheme_mixed" in codes(result)
    assert "answer_label_ambiguous_alphabet" in codes(result)
    assert result.is_resolved is False
