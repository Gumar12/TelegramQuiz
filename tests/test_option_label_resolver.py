from backend.parsers.option_labels import resolve_option_labels


def issue_codes(result):
    return [issue.code for issue in result.issues]


def test_latin_positions():
    result = resolve_option_labels(["A", "B", "C", "D"])

    assert result.label_scheme == "latin_abcd"
    assert [label.position for label in result.labels] == [1, 2, 3, 4]
    assert [label.canonical_position for label in result.labels] == [1, 2, 3, 4]
    assert result.issues == []


def test_cyrillic_ve_is_position_three():
    result = resolve_option_labels(["А", "Б", "В", "Г"])

    assert result.label_scheme == "cyrillic_abvg"
    assert result.labels[2].raw_label == "В"
    assert result.labels[2].position == 3
    assert result.labels[2].script == "cyrillic"
    assert result.labels[2].codepoint == "U+0412"


def test_mixed_scheme_returns_warning_but_preserves_raw_positions():
    result = resolve_option_labels(["A", "А", "B", "В"])

    assert result.label_scheme == "mixed"
    assert [label.position for label in result.labels] == [1, 2, 3, 4]
    assert issue_codes(result) == ["option_label_scheme_mixed"]
    assert result.issues[0].severity == "warning"


def test_script_and_codepoint_metadata():
    result = resolve_option_labels(["A", "А", "B", "В"])

    metadata = [
        (label.raw_label, label.script, label.codepoint, label.unicode_name)
        for label in result.labels
    ]
    assert metadata == [
        ("A", "latin", "U+0041", "LATIN CAPITAL LETTER A"),
        ("А", "cyrillic", "U+0410", "CYRILLIC CAPITAL LETTER A"),
        ("B", "latin", "U+0042", "LATIN CAPITAL LETTER B"),
        ("В", "cyrillic", "U+0412", "CYRILLIC CAPITAL LETTER VE"),
    ]


def test_to_dict_includes_canonical_position_metadata():
    result = resolve_option_labels(["А", "Б", "В", "Г"])

    third = result.to_dict()["labels"][2]
    assert third["raw_label"] == "В"
    assert third["position"] == 3
    assert third["canonical_position"] == 3
    assert third["codepoint"] == "U+0412"
