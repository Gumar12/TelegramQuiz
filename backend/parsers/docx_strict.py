"""Parse strict prepared quiz markdown into structured quiz items."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from backend.pipeline.encoding import detect_suspect_encoding, normalize_text
from backend.pipeline.reports import ReportIssue

StrictItemType = Literal["title", "context", "reset_context", "question"]
QuestionMode = Literal["single", "multiple", "unknown"]


@dataclass(slots=True)
class StrictOption:
    text: str
    correct: bool = False
    source_ref: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StrictItem:
    type: StrictItemType
    text: str = ""
    media: list[str] = field(default_factory=list)
    question: str = ""
    options: list[StrictOption] = field(default_factory=list)
    answers: list[int] = field(default_factory=list)
    mode: QuestionMode = "unknown"
    explanation: str = ""
    source_ref: dict[str, Any] = field(default_factory=dict)
    section_title: str | None = None
    context_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["options"] = [option.to_dict() for option in self.options]
        return data


@dataclass(slots=True)
class StrictParseResult:
    source_id: str
    items: list[StrictItem]
    issues: list[ReportIssue] = field(default_factory=list)

    @property
    def questions(self) -> list[StrictItem]:
        return [item for item in self.items if item.type == "question"]

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "question_count": self.question_count,
            "has_errors": self.has_errors,
            "items": [item.to_dict() for item in self.items],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def parse_prepared_file(path: str | Path) -> StrictParseResult:
    source_path = Path(path)
    return parse_prepared_markdown(
        source_path.read_text(encoding="utf-8"),
        source_id=str(source_path),
    )


def parse_prepared_markdown(text: str, *, source_id: str = "prepared.md") -> StrictParseResult:
    parser = _StrictPreparedParser(str(text), source_id=source_id)
    return parser.run()


class _StrictPreparedParser:
    def __init__(self, text: str, *, source_id: str) -> None:
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.source_id = source_id
        self.items: list[StrictItem] = []
        self.issues: list[ReportIssue] = []
        self.index = 0
        self.context_counter = 0
        self.current_section: str | None = None
        self.current_context_id: str | None = None

    def run(self) -> StrictParseResult:
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            line = raw.strip()
            line_no = self.index + 1
            if not line:
                self.index += 1
                continue
            if line.startswith("#SECTION"):
                self._parse_section(line, line_no)
                continue
            if line == "#CONTEXT":
                self._parse_context(line_no)
                continue
            if line == "#RESET_CONTEXT":
                self.items.append(
                    StrictItem(
                        type="reset_context",
                        source_ref=self._source_ref(line_no),
                        section_title=self.current_section,
                    )
                )
                self.current_context_id = None
                self.index += 1
                continue
            if line == "#Q":
                self._parse_question(line_no)
                continue
            if line.startswith("#"):
                self.issues.append(
                    _issue(
                        "strict_unknown_marker",
                        "error",
                        f"Неизвестный strict-маркер: {line}.",
                        "Используй только #SECTION, #CONTEXT, #END_CONTEXT, #RESET_CONTEXT, #Q, #A, #A*, #EXPLANATION, #END_Q.",
                        source_ref=self._source_ref(line_no),
                    )
                )
            else:
                self.issues.append(
                    _issue(
                        "strict_text_outside_block",
                        "error",
                        "В strict-source найден текст вне блока.",
                        "Перемести строку в #SECTION, #CONTEXT или #Q, чтобы parser не потерял данные.",
                        source_ref=self._source_ref(line_no),
                    )
                )
            self.index += 1
        return StrictParseResult(source_id=self.source_id, items=self.items, issues=self.issues)

    def _parse_section(self, line: str, line_no: int) -> None:
        title = ""
        if line == "#SECTION":
            next_index = self.index + 1
            if next_index < len(self.lines):
                next_line = self.lines[next_index].strip()
                if next_line and not next_line.startswith("#"):
                    title = normalize_text(next_line)
                    self.index = next_index + 1
                else:
                    self.index += 1
            else:
                self.index += 1
        elif line.startswith("#SECTION:"):
            title = normalize_text(line.split(":", 1)[1])
            self.index += 1
        else:
            self.issues.append(
                _issue(
                    "strict_section_marker_invalid",
                    "error",
                    "Маркер секции должен быть #SECTION или #SECTION: название.",
                    "Исправь строку секции в prepared.md.",
                    source_ref=self._source_ref(line_no),
                )
            )
            self.index += 1
            return

        self.issues.extend(detect_suspect_encoding(title, source_ref=self._source_ref(line_no)))
        if not title:
            self.issues.append(
                _issue(
                    "strict_section_title_empty",
                    "error",
                    "У секции пустое название.",
                    "Добавь название после #SECTION: или на следующей строке.",
                    source_ref=self._source_ref(line_no),
                )
            )
            return

        self.current_section = title
        self.current_context_id = None
        self.items.append(
            StrictItem(
                type="title",
                text=title,
                source_ref=self._source_ref(line_no),
                section_title=title,
            )
        )

    def _parse_context(self, start_line: int) -> None:
        self.index += 1
        text_lines: list[str] = []
        media: list[str] = []
        end_line = start_line
        found_end = False
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            line = raw.strip()
            end_line = self.index + 1
            if line == "#END_CONTEXT":
                self.index += 1
                found_end = True
                break
            media_ref = _parse_media_line(line)
            if media_ref is not None:
                media.append(media_ref)
            elif line:
                text_lines.append(raw.rstrip())
            self.index += 1
        if not found_end:
            self.issues.append(
                _issue(
                    "strict_context_missing_end",
                    "error",
                    "Контекст начался с #CONTEXT, но не закрыт #END_CONTEXT.",
                    "Добавь #END_CONTEXT перед следующим блоком.",
                    source_ref=self._source_ref(start_line),
                )
            )

        text = normalize_text("\n".join(text_lines))
        if text:
            self.issues.extend(detect_suspect_encoding(text, source_ref=self._source_ref(start_line, end_line)))
        if not text and not media:
            self.issues.append(
                _issue(
                    "strict_context_empty",
                    "warning",
                    "Контекст пустой: нет текста и media.",
                    "Удали пустой context block или добавь текст/изображение.",
                    source_ref=self._source_ref(start_line, end_line),
                )
            )

        self.context_counter += 1
        context_id = f"ctx-{self.context_counter:04d}"
        self.current_context_id = context_id
        self.items.append(
            StrictItem(
                type="context",
                text=text,
                media=media,
                source_ref=self._source_ref(start_line, end_line),
                section_title=self.current_section,
                context_id=context_id,
            )
        )

    def _parse_question(self, start_line: int) -> None:
        self.index += 1
        question_lines: list[str] = []
        explanation_lines: list[str] = []
        option_lines: list[str] = []
        options: list[StrictOption] = []
        current_correct = False
        current_option_start: int | None = None
        read_mode: Literal["question", "option", "explanation"] = "question"
        end_line = start_line
        found_end = False

        def flush_option() -> None:
            nonlocal option_lines, current_correct, current_option_start
            if current_option_start is None:
                return
            option_text = normalize_text("\n".join(option_lines))
            if not option_text:
                self.issues.append(
                    _issue(
                        "option_text_empty",
                        "error",
                        "Один из вариантов ответа пустой.",
                        "Заполни вариант после #A/#A* или удали его.",
                        source_ref=self._source_ref(current_option_start),
                    )
                )
            options.append(
                StrictOption(
                    text=option_text,
                    correct=current_correct,
                    source_ref=self._source_ref(current_option_start, end_line),
                )
            )
            option_lines = []
            current_correct = False
            current_option_start = None

        while self.index < len(self.lines):
            raw = self.lines[self.index]
            line = raw.strip()
            end_line = self.index + 1
            if line == "#END_Q":
                flush_option()
                found_end = True
                self.index += 1
                break
            if line in {"#A", "#A*"}:
                flush_option()
                current_correct = line == "#A*"
                current_option_start = self.index + 1
                read_mode = "option"
                self.index += 1
                continue
            if line == "#EXPLANATION":
                flush_option()
                read_mode = "explanation"
                self.index += 1
                continue
            if line.startswith("#"):
                self.issues.append(
                    _issue(
                        "strict_unknown_marker_in_question",
                        "error",
                        f"Неизвестный marker внутри вопроса: {line}.",
                        "Закрой вопрос #END_Q или исправь marker.",
                        source_ref=self._source_ref(self.index + 1),
                    )
                )
                self.index += 1
                continue
            if line:
                if read_mode == "question":
                    question_lines.append(raw.rstrip())
                elif read_mode == "option":
                    option_lines.append(raw.rstrip())
                else:
                    explanation_lines.append(raw.rstrip())
            self.index += 1

        if not found_end:
            flush_option()
            self.issues.append(
                _issue(
                    "strict_question_missing_end",
                    "error",
                    "Вопрос начался с #Q, но не закрыт #END_Q.",
                    "Добавь #END_Q после последнего варианта.",
                    source_ref=self._source_ref(start_line, end_line),
                )
            )

        question_text = normalize_text("\n".join(question_lines))
        if question_text:
            self.issues.extend(detect_suspect_encoding(question_text, source_ref=self._source_ref(start_line, end_line)))
        for option in options:
            if option.text:
                self.issues.extend(detect_suspect_encoding(option.text, source_ref=option.source_ref))
        explanation_text = normalize_text("\n".join(explanation_lines))
        if explanation_text:
            self.issues.extend(detect_suspect_encoding(explanation_text, source_ref=self._source_ref(start_line, end_line)))
        if not question_text:
            self.issues.append(
                _issue(
                    "question_text_empty",
                    "error",
                    "Пустой текст вопроса.",
                    "Добавь текст вопроса сразу после #Q.",
                    source_ref=self._source_ref(start_line, end_line),
                )
            )
        if len(options) < 2:
            self.issues.append(
                _issue(
                    "too_few_options",
                    "error",
                    "У вопроса меньше двух вариантов ответа.",
                    "Добавь минимум два варианта через #A/#A* или пропусти вопрос.",
                    source_ref=self._source_ref(start_line, end_line),
                )
            )

        answers = [position for position, option in enumerate(options, start=1) if option.correct]
        if not answers:
            self.issues.append(
                _issue(
                    "answer_missing",
                    "error",
                    "Не найден правильный ответ для вопроса.",
                    "Отметь правильный вариант marker-строкой #A*.",
                    source_ref=self._source_ref(start_line, end_line),
                )
            )
        mode_value: QuestionMode = "unknown"
        if len(answers) == 1:
            mode_value = "single"
        elif len(answers) > 1:
            mode_value = "multiple"

        self.items.append(
            StrictItem(
                type="question",
                question=question_text,
                options=options,
                answers=answers,
                mode=mode_value,
                explanation=explanation_text,
                source_ref=self._source_ref(start_line, end_line),
                section_title=self.current_section,
                context_id=self.current_context_id,
            )
        )

    def _source_ref(self, start_line: int, end_line: int | None = None) -> dict[str, Any]:
        ref = {"source_id": self.source_id, "line": start_line}
        if end_line is not None and end_line != start_line:
            ref["end_line"] = end_line
        return ref


def _parse_media_line(line: str) -> str | None:
    if line.startswith("![") and "](" in line and line.endswith(")"):
        value = line.rsplit("](", 1)[1][:-1].strip()
        return value or None
    return None


def _issue(
    code: str,
    severity: Literal["info", "warning", "error"],
    message_ru: str,
    action_ru: str,
    *,
    source_ref: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReportIssue:
    return ReportIssue(
        code=code,
        severity=severity,
        message_ru=message_ru,
        action_ru=action_ru,
        source_ref=source_ref or {},
        metadata=metadata or {},
    )