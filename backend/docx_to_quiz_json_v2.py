"""Convert source DOCX quiz notes into the extended v2 JSON format."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn

from backend import config


DATE_RE = re.compile(r"^\s*\d{1,2}\s+мая\s*$", re.I)
SECTION_RE = re.compile(r"^\s*(УТРО|ОБЕД|ВЕЧЕР|повтор.*)\s*$", re.I)
OPTION_RE = re.compile(r"^\s*([AАBВCСDД])(?:\)|\.\s+)\s*(.+)$", re.I)
OPTION_TOKEN_RE = re.compile(r"(?<!\w)([AАBВCСDД])(?:\)|\.\s+)\s*", re.I)
NUMBERED_RE = re.compile(r"^\s*(\d+)[\.\)]\s*(.+)$")
ANSWER_PREFIX_RE = re.compile(r"^\s*(?:✔️|✅)?\s*(?:Ответ\s*[:：]\s*)?(.*)$", re.I)
ANSWER_CHOICE_RE = re.compile(r"^\s*(?:Ответ|Answer)\s*[:：]\s*(.+)$", re.I)
ANSWER_CHOICE_TOKEN_RE = re.compile(r"(?<![A-Za-zА-Яа-я])([AАBВCСDД])(?![A-Za-zА-Яа-я])", re.I)
ROMAN_STATEMENT_RE = re.compile(r"^\s*[IVXLCDM]+\.\s+\S+", re.I)
ROMAN_LINE_RE = re.compile(r"^\s*([IVXLCDM]+)\.\s+(.+)$", re.I)
QUESTION_STARTS = (
    "какой",
    "какая",
    "какое",
    "какие",
    "кто",
    "где",
    "когда",
    "что",
    "в чем",
    "почему",
    "как ",
    "каким",
    "какую",
)
STATEMENT_SELECTION_PROMPTS = (
    "выберите верные",
    "выберите верное",
    "установите верные",
    "укажите верные",
    "верные утверждения",
    "правильные утверждения",
)
QUOTE_OPENERS = ("«", '"', "“")
QUOTE_CLOSERS = ("»", '"', "”")


def clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def starts_quote_context(line: str) -> bool:
    return clean(line).startswith(QUOTE_OPENERS)


def closes_quote_context(line: str) -> bool:
    s = clean(line)
    if not s:
        return False
    for closer in QUOTE_CLOSERS:
        if closer in s[1:]:
            return True
    return False


def quote_balance_delta(line: str) -> int:
    s = clean(line)
    return s.count("«") + s.count("“") - s.count("»") - s.count("”")


def run_is_bold(run: Any) -> bool:
    if run.bold is not None:
        return bool(run.bold)

    style = getattr(run, "style", None)
    font = getattr(style, "font", None)
    return bool(getattr(font, "bold", False))


def iter_docx_blocks(docx_path: str | Path, media_dir: str | Path) -> list[dict[str, Any]]:
    """Return document paragraphs and inline images in their document order."""
    doc = Document(docx_path)
    out_dir = Path(media_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocks: list[dict[str, Any]] = []
    image_counter = 1
    blank_before = 0

    for para in doc.paragraphs:
        paragraph_text_parts: list[str] = []
        paragraph_bold_parts: list[str] = []
        paragraph_images: list[str] = []
        style_name = (para.style.name if para.style else "") or ""
        is_heading = style_name.lower().startswith("heading")

        for run in para.runs:
            if run.text:
                paragraph_text_parts.append(run.text)
                if run_is_bold(run):
                    paragraph_bold_parts.append(run.text)

            for drawing in run._element.xpath(".//w:drawing"):
                for blip in drawing.xpath(".//a:blip"):
                    r_id = blip.get(qn("r:embed"))
                    if not r_id:
                        continue
                    image_part = doc.part.related_parts.get(r_id)
                    if not image_part:
                        continue

                    ext = image_part.content_type.split("/")[-1]
                    if ext == "jpeg":
                        ext = "jpg"
                    filename = f"image_{image_counter:03d}.{ext}"
                    image_counter += 1

                    out_path = out_dir / filename
                    out_path.write_bytes(image_part.blob)
                    paragraph_images.append(str(out_path.as_posix()))

        text = clean("".join(paragraph_text_parts))
        if text:
            block: dict[str, Any] = {"type": "text", "text": text}
            bold_text = clean("".join(paragraph_bold_parts))
            if bold_text:
                block["bold_text"] = bold_text
                block["has_bold"] = True
            if blank_before:
                block["blank_before"] = blank_before
            if is_heading:
                block["is_heading"] = True
            blocks.append(block)
            blank_before = 0
        for image_path in paragraph_images:
            blocks.append({"type": "image", "path": image_path})
        if paragraph_images:
            blank_before = 0
        if not text and not paragraph_images:
            blank_before += 1

    return blocks


def split_inline_qa(line: str, *, allow_colon: bool = True) -> tuple[str, str] | None:
    s = clean(line)
    if len(s) < 8 or DATE_RE.match(s) or SECTION_RE.match(s) or OPTION_RE.match(s):
        return None

    if allow_colon and ":" in s and not s.lower().startswith("контекст"):
        left, right = s.split(":", 1)
        if len(left) > 8 and len(right) > 2:
            return clean(left), clean(right)

    for sep in [" — ", " - "]:
        if sep in s:
            left, right = s.split(sep, 1)
            if len(left) > 8 and len(right) > 2:
                return clean(left), clean(right)

    return None


def is_question_line(line: str) -> bool:
    s = clean(line)
    lowered = s.lower()
    return s.endswith("?") or lowered.startswith(QUESTION_STARTS)


def is_answer_prompt_line(line: str) -> bool:
    s = clean(line)
    if not s.endswith(":"):
        return False
    if DATE_RE.match(s) or SECTION_RE.match(s) or OPTION_RE.match(s):
        return False
    if s.lower().startswith("РєРѕРЅС‚РµРєСЃС‚"):
        return False
    return len(s.rstrip(":").strip()) > 8


def normalize_answer(raw: str) -> str:
    s = clean(raw)
    match = ANSWER_PREFIX_RE.match(s)
    if match:
        s = match.group(1)
    return s.lstrip("✔️✅").strip()


def compact_for_option(answer: str, max_len: int = 100) -> str:
    ans = normalize_answer(answer)
    lowered = ans.casefold()
    semantic_patterns = [
        ("кишкентай", "Кишкентай"),
        (
            "декларация о государственном суверенитете казахской сср",
            "Декларация о государственном суверенитете Казахской ССР",
        ),
        ("сырдарьинская область", "Сырдарьинская область"),
        ("ограничению власти биев и султанов", "ограничение власти биев и султанов"),
        ("противостояние с большевиками", "противостояние большевикам"),
        ("устав о сибирских киргизах", "Устав о сибирских киргизах"),
        ("жиембет-жырау", "Жиембет-жырау"),
        ("централизация производства и распределения", "централизация производства и распределения"),
        ("знания своих семи предков", "знание семи предков"),
        ("объединить силы трех жузов", "объединение сил трех жузов"),
        ("массовый голод", "массовый голод и сокращение населения"),
    ]
    for needle, replacement in semantic_patterns:
        if needle in lowered and len(replacement) <= max_len:
            return replacement

    ans = re.sub(
        r"^(Это|В этот день|В указанном периоде|В годы|После)\s+",
        "",
        ans,
        flags=re.I,
    )
    if ROMAN_STATEMENT_RE.match(ans):
        return ans[: max_len - 1].rstrip() + "…" if len(ans) > max_len else ans
    first_sentence = re.split(r"[.;]", ans)[0].strip()
    if 3 <= len(first_sentence) <= max_len:
        return first_sentence
    return ans[: max_len - 1].rstrip() + "…" if len(ans) > max_len else ans


def make_explanation(answer: str, max_len: int = 200) -> str:
    normalized = normalize_answer(answer)
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 1].rstrip() + "…"


def guess_question_type(
    question: str,
    answer: str,
    options: list[str] | None,
    media: list[str],
) -> str:
    if media:
        return "media_context_quiz"
    if options:
        return "multiple_choice"
    if len(question) > 250:
        return "long_question"
    if len(answer) > 100:
        return "short_answer_with_explanation"
    return "simple_quiz"


ROMAN_TO_INT = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
    "XI": 11,
    "XII": 12,
    "XIII": 13,
    "XIV": 14,
    "XV": 15,
    "XVI": 16,
    "XVII": 17,
    "XVIII": 18,
    "XIX": 19,
    "XX": 20,
    "XXI": 21,
}
INT_TO_ROMAN = {value: key for key, value in ROMAN_TO_INT.items()}


def _key(text: str) -> str:
    return clean(text).casefold()


def split_option_line(line: str) -> list[str]:
    s = clean(line)
    matches = list(OPTION_TOKEN_RE.finditer(s))
    if not matches or matches[0].start() != 0:
        return []

    options: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(s)
        option = clean(s[start:end])
        if option:
            options.append(option)
    return options


def option_block_marks_correct(block: dict[str, Any], option_text: str) -> bool:
    bold_text = clean(str(block.get("bold_text", "")))
    if not bold_text and block.get("has_bold"):
        bold_text = clean(str(block.get("text", "")))
    if not bold_text:
        return False

    option_key = _key(option_text)
    bold_match = OPTION_RE.match(bold_text)
    if bold_match:
        bold_text = clean(bold_match.group(2))
    bold_key = _key(bold_text)

    if len(bold_key) < 2:
        return False
    return bold_key == option_key or bold_key in option_key or option_key in bold_key


def parse_correct_index_line(line: str, max_index: int) -> list[int]:
    s = clean(line)
    if not re.fullmatch(r"\d+(?:\s*(?:,|;|и)\s*\d+)+", s, flags=re.I):
        return []
    indexes = [int(value) for value in re.findall(r"\d+", s)]
    if len(indexes) < 2 or len(set(indexes)) != len(indexes):
        return []
    if any(index < 1 or index > max_index for index in indexes):
        return []
    return indexes


def parse_answer_choice_line(line: str, max_index: int) -> list[int]:
    match = ANSWER_CHOICE_RE.match(clean(line))
    if not match:
        return []

    payload = match.group(1)
    letter_indexes = {
        "A": 1,
        "А": 1,
        "B": 2,
        "В": 2,
        "C": 3,
        "С": 3,
        "D": 4,
        "Д": 4,
    }
    indexes: list[int] = []
    for token in ANSWER_CHOICE_TOKEN_RE.findall(payload):
        index = letter_indexes.get(token.upper())
        if index and 1 <= index <= max_index and index not in indexes:
            indexes.append(index)
    if indexes:
        return indexes

    number_indexes = [int(value) for value in re.findall(r"\d+", payload)]
    if (
        number_indexes
        and len(set(number_indexes)) == len(number_indexes)
        and all(1 <= index <= max_index for index in number_indexes)
    ):
        return number_indexes
    return []


def numbered_statement_options(
    blocks: list[dict[str, Any]],
    start_index: int,
) -> tuple[list[str], int]:
    options: list[str] = []
    index = start_index
    while index < len(blocks) and blocks[index]["type"] == "text":
        match = NUMBERED_RE.match(clean(blocks[index].get("text", "")))
        if not match:
            break
        number = int(match.group(1))
        if number != len(options) + 1:
            break
        option = clean(match.group(2))
        if not option:
            break
        options.append(option)
        index += 1
    return options, index


def roman_statement_block(
    blocks: list[dict[str, Any]],
    start_index: int,
) -> tuple[list[str], int]:
    statements: list[str] = []
    index = start_index
    expected_number = 1

    while index < len(blocks) and blocks[index]["type"] == "text":
        line = clean(blocks[index].get("text", ""))
        match = ROMAN_LINE_RE.match(line)
        if not match:
            break
        roman_number = ROMAN_TO_INT.get(match.group(1).upper())
        if roman_number != expected_number:
            break
        statements.append(line)
        expected_number += 1
        index += 1

    return statements, index


def statement_context_text(statements: list[str]) -> str:
    return "\n".join(clean(statement) for statement in statements if clean(statement))


def next_text_is_option_group(blocks: list[dict[str, Any]], index: int) -> bool:
    return (
        index + 1 < len(blocks)
        and blocks[index + 1]["type"] == "text"
        and bool(split_option_line(clean(blocks[index + 1].get("text", ""))))
    )


def _add_unique(candidates: list[str], option: str, correct_key: str) -> None:
    option = clean(option)
    if not option or len(option) > 100:
        return
    option_key = _key(option)
    if option_key == correct_key:
        return
    if option_key in {_key(candidate) for candidate in candidates}:
        return
    candidates.append(option)


def _century_distractors(answer: str) -> list[str]:
    match = re.fullmatch(r"([IVXLCDM]+)\s+веке", clean(answer), flags=re.I)
    if not match:
        return []
    century = ROMAN_TO_INT.get(match.group(1).upper())
    if not century:
        return []
    values = [century - 1, century + 1, century + 2, century - 2]
    return [f"{INT_TO_ROMAN[value]} веке" for value in values if value in INT_TO_ROMAN]


def _year_distractors(answer: str) -> list[str]:
    if not re.fullmatch(r"\d{3,4}", clean(answer)):
        return []
    year = int(answer)
    values = [year - 1, year + 1, year + 5, year - 5, year + 10, year - 10]
    return [str(value) for value in values if value > 0]


def contextual_distractors(item: dict[str, Any]) -> list[str]:
    question = _key(item.get("question", ""))
    answer = clean(item.get("correct_answer", ""))
    answer_key = _key(answer)
    context = _key(f"{item.get('context_title', '')} {item.get('context', '')}")
    combined = f"{question} {answer_key} {context}"
    candidates: list[str] = []

    if _century_distractors(answer):
        return _century_distractors(answer)[:3]
    if _year_distractors(answer):
        return _year_distractors(answer)[:3]

    if any(prompt in question for prompt in STATEMENT_SELECTION_PROMPTS):
        return []

    keyword_rules = [
        (("съезд", "осудив"), ["XIX съезд", "XXI съезд", "XVIII съезд"]),
        (("административных реформ", "традиционного общества"), ["ликвидация ханской власти", "введение окружного управления", "переселение русских крестьян"]),
        (("алаш-орд", "советской власти"), ["сотрудничество с большевиками", "политический нейтралитет", "поддержка царской власти"]),
        (("малого октября", "демограф"), ["рост численности населения", "массовая урбанизация", "переселение в южные области"]),
        (("указ 1822", "ханской власти"), ["Устав 1824 года", "Временное положение 1868 года", "Степное положение 1891 года"]),
        (("жырау",), ["Бухар жырау", "Асан Кайгы", "Актамберды жырау"]),
        (("кенесары", "1916", "схож"), ["антиколониальной направленности", "руководстве султанов", "религиозном характере"]),
        (("саки", "редко использовали"), ["лук и стрелы", "седло и стремена", "акинак и кинжал"]),
        (("он ок будун",), ["уйсуней", "кангюев", "карлуков"]),
        (("байтурсын",), ["сборник «Қырық мысал»", "роман «Путь Абая»", "пьеса «Еңлік-Кебек»"]),
        (("тасмолин",), ["звериный стиль", "каменные балбалы", "городища"]),
        (("жангир",), ["Аңыракайская битва", "Булантинская битва", "Атлахская битва"]),
        (("военного коммунизма",), ["восстановление рыночной торговли", "развитие частного предпринимательства", "переход к индустриализации"]),
        (("инициатор", "съезд"), ["И. Сталин", "Л. Брежнев", "М. Горбачев"]),
        (("закончилась эпоха",), ["оттепели", "застоя", "перестройки"]),
        (("после съезда",), ["начало коллективизации", "введение НЭПа", "создание СССР"]),
        (("бокеевская орда",), ["в Жетысу", "на Сырдарье", "в Центральном Казахстане"]),
        (("государство тимура", "территории"), ["Дешт-и-Кыпчака", "Жетысу", "Хорезма"]),
        (("жас тулпар",), ["Алаш", "Үш жүз", "Невада-Семей"]),
        (("культ", "сталина"), ["Верховный Совет СССР", "Совет Министров СССР", "Коминтерн"]),
        (("курмангазы",), ["Сарыарқа", "Адай", "Балбырауын"]),
        (("жеты ата",), ["почитание духов предков", "свадебный обряд", "разделение на жузы"]),
        (("1924", "регион"), ["Жетысу", "Акмолинская область", "Семиреченская область"]),
        (("25 октября 1990",), ["Конституция Казахской ССР", "Акт о независимости", "Декларация прав человека"]),
        (("ордабасы",), ["разделить войска по жузам", "заключить мир с джунгарами", "перенести столицу в Туркестан"]),
    ]
    for keywords, options in keyword_rules:
        if all(keyword in combined for keyword in keywords):
            for option in options:
                _add_unique(candidates, option, answer_key)
            return candidates[:3]

    if "чингизид" in combined or "так как" in question:
        for option in [
            "был чингизидом",
            "принял ханский титул",
            "происходил из рода Джучи",
            "был потомком Чингисхана",
        ]:
            _add_unique(candidates, option, answer_key)
        return candidates[:3]

    if "улус" in combined or "чагата" in combined or "чингизхан" in combined:
        for option in ["Улуса Джучи", "Могулистана", "Золотой Орды", "Улуса Угэдэя"]:
            _add_unique(candidates, option, answer_key)
        return candidates[:3]

    if "портрет" in combined or "изображ" in combined:
        for option in ["Чингисхан", "Абылай хан", "Тауке хан", "Кенесары хан", "Бату хан"]:
            _add_unique(candidates, option, answer_key)
        return candidates[:3]

    if "организац" in combined:
        for option in ["Алаш", "Үш жүз", "Невада-Семей", "Азат"]:
            _add_unique(candidates, option, answer_key)

    if "съезд" in combined:
        for option in ["XIX съезд", "XXI съезд", "XVIII съезд", "XXII съезд"]:
            _add_unique(candidates, option, answer_key)

    if not candidates and any(word in combined for word in ["хан", "правител", "личность"]):
        for option in ["Абылай хан", "Тауке хан", "Кенесары хан", "Букей хан"]:
            _add_unique(candidates, option, answer_key)

    return candidates[:3]


def attach_distractors(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pool: list[str] = []
    for item in items:
        correct_answer = item.get("correct_answer", "")
        if correct_answer and 2 <= len(correct_answer) <= 100:
            pool.append(correct_answer)

    for item in items:
        if item.get("options"):
            continue

        correct_answer = item.get("correct_answer", "")
        if not correct_answer:
            continue

        distractors = contextual_distractors(item)
        if len(distractors) < 3:
            item["type"] = "needs_distractor_review"
            item["options"] = []
            item["correct"] = None
            item["distractors_source"] = "needs_contextual_distractors"
            continue

        item["options"] = [correct_answer] + distractors[:3]
        item["correct"] = 1
        item["distractors_source"] = "heuristic_same_document"

    return items


def parse_blocks_to_items(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current_date = ""
    current_section = ""
    current_context_title = ""
    current_context_text: list[str] = []
    current_context_media: list[str] = []
    quote_context_open = False
    quote_context_depth = 0
    collecting_context = False

    pending_question: str | None = None
    pending_options: list[str] = []
    pending_correct_options: list[int] = []
    pending_correct_source = "source_document_bold"
    pending_context_text: list[str] = []
    pending_media: list[str] = []

    def reset_context() -> None:
        nonlocal current_context_title, current_context_text, current_context_media
        nonlocal quote_context_open, quote_context_depth, collecting_context
        current_context_title = ""
        current_context_text = []
        current_context_media = []
        quote_context_open = False
        quote_context_depth = 0
        collecting_context = False

    def context_text() -> str:
        return clean("\n".join(current_context_text))

    def pending_context() -> str:
        parts = [part for part in [context_text(), statement_context_text(pending_context_text)] if part]
        return "\n".join(parts)

    def flush_pending() -> None:
        nonlocal pending_question, pending_options, pending_correct_options, pending_correct_source, pending_context_text, pending_media
        if not pending_question:
            return

        correct_answers = [
            pending_options[correct - 1]
            for correct in pending_correct_options
            if 1 <= correct <= len(pending_options)
        ]
        if len(correct_answers) == 1:
            correct: int | list[int] | None = pending_correct_options[0]
            correct_answer = correct_answers[0]
        elif len(correct_answers) > 1:
            correct = list(pending_correct_options)
            correct_answer = "; ".join(correct_answers)
        else:
            correct = None
            correct_answer = ""
        item_type = (
            "multiple_answer"
            if len(correct_answers) > 1
            else guess_question_type(
                pending_question,
                correct_answer,
                pending_options,
                list(current_context_media + pending_media),
            )
            if correct
            else "needs_answer_review"
        )

        item = {
            "id": len(items) + 1,
            "date": current_date,
            "section": current_section,
            "context_title": current_context_title,
            "context": pending_context(),
            "media": list(current_context_media + pending_media),
            "question": pending_question,
            "correct_answer": correct_answer,
            "options": pending_options if pending_options else [],
            "correct": correct,
            "correct_answers": correct_answers if correct_answers else [],
            "explanation": "",
            "explanation_full": "",
            "type": item_type,
            "source": "docx_v2",
        }
        if correct:
            item["distractors_source"] = pending_correct_source
        items.append(item)
        pending_question = None
        pending_options = []
        pending_correct_options = []
        pending_correct_source = "source_document_bold"
        pending_context_text = []
        pending_media = []

    i = 0
    while i < len(blocks):
        block = blocks[i]

        if block["type"] == "image":
            if current_context_title or current_context_text:
                current_context_media.append(block["path"])
            else:
                if pending_question and pending_options:
                    flush_pending()
                pending_media.append(block["path"])
            i += 1
            continue

        line = clean(block.get("text", ""))
        if not line:
            i += 1
            continue

        # A run of >=2 blank paragraphs separates context blocks from the
        # standalone questions that follow; end the current context here so it
        # does not bleed onto unrelated questions.
        if block.get("blank_before", 0) >= 2:
            flush_pending()
            reset_context()
            pending_media = []

        # A Heading 2 paragraph opens a new context block (title + following
        # paragraph), e.g. "Культ личности Сталина", "Тимур".
        if block.get("is_heading"):
            flush_pending()
            reset_context()
            current_context_title = line
            collecting_context = True
            pending_media = []
            i += 1
            continue

        if DATE_RE.match(line):
            flush_pending()
            current_date = line
            current_section = ""
            reset_context()
            pending_media = []
            i += 1
            continue

        if SECTION_RE.match(line):
            flush_pending()
            current_section = line
            reset_context()
            pending_media = []
            i += 1
            continue

        if line.lower().startswith("контекст"):
            flush_pending()
            current_context_title = line
            current_context_text = []
            current_context_media = []
            collecting_context = True
            pending_media = []
            i += 1
            continue

        if starts_quote_context(line) and not next_text_is_option_group(blocks, i):
            flush_pending()
            current_context_title = "Контекст"
            current_context_text = []
            current_context_media = []
            quote_context_depth = max(0, quote_balance_delta(line))
            quote_context_open = quote_context_depth > 0 or not closes_quote_context(line)
            current_context_title = current_context_title or "Контекст"
            current_context_text.append(line)
            i += 1
            continue

        if quote_context_open:
            current_context_title = current_context_title or "Контекст"
            current_context_text.append(line)
            inline = split_inline_qa(line, allow_colon=False)
            if inline:
                question, answer = inline
                media = list(current_context_media + pending_media)
                normalized_answer = normalize_answer(answer)
                items.append(
                    {
                        "id": len(items) + 1,
                        "date": current_date,
                        "section": current_section,
                        "context_title": current_context_title,
                        "context": context_text(),
                        "media": media,
                        "question": question,
                        "correct_answer": compact_for_option(answer),
                        "options": [],
                        "correct": None,
                        "explanation": make_explanation(answer),
                        "explanation_full": normalized_answer,
                        "type": guess_question_type(question, answer, None, media),
                        "source": "docx_v2",
                    }
                )
                pending_media = []
            if quote_context_depth > 0:
                quote_context_depth = max(0, quote_context_depth + quote_balance_delta(line))
                quote_context_open = quote_context_depth > 0
            elif closes_quote_context(line):
                quote_context_open = False
            i += 1
            continue

        option_texts = split_option_line(line)
        if option_texts and pending_question:
            for option_text in option_texts:
                pending_options.append(option_text)
                if option_block_marks_correct(block, option_text):
                    pending_correct_options.append(len(pending_options))
                    pending_correct_source = "source_document_bold"
            i += 1
            continue

        if pending_question and pending_options:
            answer_choices = parse_answer_choice_line(line, len(pending_options))
            if answer_choices:
                pending_correct_options = answer_choices
                pending_correct_source = "source_document_answer_line"
                flush_pending()
                i += 1
                continue

        numbered_match = NUMBERED_RE.match(line)
        if numbered_match:
            line = clean(numbered_match.group(2))

        roman_statements, option_start = roman_statement_block(blocks, i + 1)
        if (
            roman_statements
            and option_start < len(blocks)
            and blocks[option_start]["type"] == "text"
            and split_option_line(clean(blocks[option_start].get("text", "")))
        ):
            flush_pending()
            collecting_context = False
            pending_question = clean(line.rstrip(":"))
            pending_options = []
            pending_correct_options = []
            pending_correct_source = "source_document_bold"
            pending_context_text = roman_statements
            pending_media = []
            i = option_start
            continue

        next_is_option_group = next_text_is_option_group(blocks, i)
        if next_is_option_group and not split_option_line(line) and not ROMAN_STATEMENT_RE.match(line):
            flush_pending()
            collecting_context = False
            pending_question = clean(line.rstrip(":"))
            pending_options = []
            pending_correct_options = []
            pending_correct_source = "source_document_bold"
            pending_context_text = []
            i += 1
            continue

        inline_candidate = split_inline_qa(line)
        if (
            collecting_context
            and current_context_title
            and not pending_question
            and not is_question_line(line)
            and not is_answer_prompt_line(line)
            and (inline_candidate is None or len(line) > 300)
        ):
            current_context_text.append(line)
            i += 1
            continue

        inline = inline_candidate
        if inline:
            flush_pending()
            question, answer = inline
            media = list(current_context_media + pending_media)
            normalized_answer = normalize_answer(answer)
            items.append(
                {
                    "id": len(items) + 1,
                    "date": current_date,
                    "section": current_section,
                    "context_title": current_context_title,
                    "context": context_text(),
                    "media": media,
                    "question": question,
                    "correct_answer": compact_for_option(answer),
                    "options": [],
                    "correct": None,
                    "explanation": make_explanation(answer),
                    "explanation_full": normalized_answer,
                    "type": guess_question_type(question, answer, None, media),
                    "source": "docx_v2",
                }
            )
            pending_media = []
            i += 1
            continue

        if is_answer_prompt_line(line):
            flush_pending()
            j = i + 1
            while j < len(blocks) and blocks[j]["type"] == "image":
                pending_media.append(blocks[j]["path"])
                j += 1
            if j < len(blocks) and blocks[j]["type"] == "text":
                numbered_options, answer_index = numbered_statement_options(blocks, j)
                if len(numbered_options) >= 2 and answer_index < len(blocks) and blocks[answer_index]["type"] == "text":
                    answer_block = blocks[answer_index]
                    answer_line = clean(
                        str(answer_block.get("bold_text") or answer_block.get("text", ""))
                    )
                    correct_indexes = parse_correct_index_line(answer_line, len(numbered_options))
                    if correct_indexes:
                        correct_answers = [
                            numbered_options[correct - 1]
                            for correct in correct_indexes
                        ]
                        media = list(current_context_media + pending_media)
                        items.append(
                            {
                                "id": len(items) + 1,
                                "date": current_date,
                                "section": current_section,
                                "context_title": current_context_title,
                                "context": context_text(),
                                "media": media,
                                "question": clean(line.rstrip(":")),
                                "correct_answer": "; ".join(correct_answers),
                                "correct_answers": correct_answers,
                                "options": numbered_options,
                                "correct": correct_indexes,
                                "explanation": "",
                                "explanation_full": "",
                                "type": "multiple_answer",
                                "source": "docx_v2",
                                "distractors_source": "source_document_answer_indexes",
                            }
                        )
                        pending_media = []
                        i = answer_index + 1
                        continue

                next_line = clean(blocks[j]["text"])
                if split_option_line(next_line):
                    pending_question = clean(line.rstrip(":"))
                    pending_options = []
                    pending_correct_options = []
                    pending_correct_source = "source_document_bold"
                    pending_context_text = []
                    i = j
                    continue
                if (
                    next_line
                    and not DATE_RE.match(next_line)
                    and not SECTION_RE.match(next_line)
                    and not OPTION_RE.match(next_line)
                ):
                    answer = normalize_answer(next_line)
                    question = clean(line.rstrip(":"))
                    media = list(current_context_media + pending_media)
                    items.append(
                        {
                            "id": len(items) + 1,
                            "date": current_date,
                            "section": current_section,
                            "context_title": current_context_title,
                            "context": context_text(),
                            "media": media,
                            "question": question,
                            "correct_answer": compact_for_option(answer),
                            "options": [],
                            "correct": None,
                            "explanation": make_explanation(answer),
                            "explanation_full": answer,
                            "type": guess_question_type(question, answer, None, media),
                            "source": "docx_v2",
                        }
                    )
                    pending_media = []
                    i = j + 1
                    continue

        if is_question_line(line):
            flush_pending()
            collecting_context = False
            pending_question = line
            pending_options = []
            pending_correct_options = []
            pending_correct_source = "source_document_bold"
            pending_context_text = []
            pending_media = []

            j = i + 1
            while j < len(blocks) and blocks[j]["type"] == "image":
                pending_media.append(blocks[j]["path"])
                j += 1

            if j < len(blocks) and blocks[j]["type"] == "text":
                next_line = clean(blocks[j]["text"])
                if (
                    next_line
                    and not is_question_line(next_line)
                    and not OPTION_RE.match(next_line)
                    and not DATE_RE.match(next_line)
                    and not SECTION_RE.match(next_line)
                ):
                    answer = normalize_answer(next_line)
                    media = list(current_context_media + pending_media)
                    items.append(
                        {
                            "id": len(items) + 1,
                            "date": current_date,
                            "section": current_section,
                            "context_title": current_context_title,
                            "context": context_text(),
                            "media": media,
                            "question": pending_question,
                            "correct_answer": compact_for_option(answer),
                            "options": [],
                            "correct": None,
                            "explanation": make_explanation(answer),
                            "explanation_full": answer,
                            "type": guess_question_type(pending_question, answer, None, media),
                            "source": "docx_v2",
                        }
                    )
                    pending_question = None
                    pending_media = []
                    i = j + 1
                    continue

            i += 1
            continue

        i += 1

    flush_pending()
    return attach_distractors(items)


def build_output(
    docx_path: str | Path,
    output_json: str | Path,
    media_dir: str | Path,
    title: str,
    description: str,
) -> dict[str, Any]:
    blocks = iter_docx_blocks(docx_path, media_dir)
    items = parse_blocks_to_items(blocks)
    report = {
        "blocks_total": len(blocks),
        "items_total": len(items),
        "items_with_media": sum(1 for item in items if item.get("media")),
        "items_needs_review": sum(
            1 for item in items if str(item.get("type", "")).startswith("needs_")
        ),
        "items_with_long_explanation": sum(
            1 for item in items if len(item.get("explanation_full", "")) > 200
        ),
    }
    data = {
        "quiz_title": title,
        "quiz_description": description,
        "format_version": "2.0",
        "telegram_limits": {
            "poll_question_max_chars": 255,
            "option_max_chars": 100,
            "explanation_max_chars": 200,
            "note": "Long context/images should be sent before the poll or stored in explanation_full.",
        },
        "report": report,
        "questions": items,
    }
    Path(output_json).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data


def group_label(item: dict[str, Any]) -> str:
    label = " ".join(
        part.strip()
        for part in [str(item.get("date", "")), str(item.get("section", ""))]
        if part and part.strip()
    )
    return label or "Без группы"


def format_group_summary(data: dict[str, Any]) -> list[str]:
    counts = Counter(group_label(item) for item in data.get("questions", []))
    lines = [f"Групп: {len(counts)}"]
    lines.extend(f"{group}: {count}" for group, count in counts.items())
    return lines


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert DOCX quiz notes to questions_v2 JSON.")
    parser.add_argument("--input", required=True, help="Input DOCX file")
    parser.add_argument("--output", default=str(config.DATA_DIR / "questions_v2.json"), help="Output JSON path")
    parser.add_argument("--media-dir", default=str(config.DATA_DIR / "media"), help="Where extracted images are saved")
    parser.add_argument("--title", default="История Казахстана")
    parser.add_argument("--description", default="Тест по истории Казахстана")
    parser.add_argument("--show-groups", action="store_true", help="Print parsed group names and question counts")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    data = build_output(args.input, args.output, args.media_dir, args.title, args.description)
    print("Done.")
    print(json.dumps(data["report"], ensure_ascii=False, indent=2))
    if args.show_groups:
        print("Groups:")
        for line in format_group_summary(data):
            print(line)


if __name__ == "__main__":
    main()
