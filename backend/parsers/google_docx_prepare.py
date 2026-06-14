"""Prepare Google Docs-exported DOCX IR into strict, reviewable quiz source."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.parsers.answer_resolver import AnswerResolution, resolve_answer_sources
from backend.parsers.option_labels import OptionLine, split_option_line
from backend.pipeline.document_ir import DocumentBlock, DocumentIR
from backend.pipeline.encoding import detect_suspect_encoding, normalize_text
from backend.pipeline.reports import ReportIssue


@dataclass(slots=True)
class PreparedOption:
    raw_label: str
    text: str
    correct: bool = False
    source_ref: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PreparedContext:
    id: str
    text: str = ""
    media: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PreparedQuestion:
    id: str
    question: str
    options: list[PreparedOption]
    answers: list[int]
    mode: str
    answer_source: str
    title: str | None = None
    context_id: str | None = None
    source_ref: dict[str, Any] = field(default_factory=dict)
    answer_evidence: dict[str, Any] = field(default_factory=dict)
    issues: list[ReportIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["options"] = [option.to_dict() for option in self.options]
        data["issues"] = [issue.to_dict() for issue in self.issues]
        return data


@dataclass(slots=True)
class BrokenQuestion:
    source_question_index: int
    question_text: str
    options: list[dict[str, Any]]
    answer_evidence: dict[str, Any]
    issue_code: str
    reason_ru: str
    action_ru: str
    source_ref: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PreparedDocxResult:
    source_id: str
    questions: list[PreparedQuestion]
    contexts: list[PreparedContext] = field(default_factory=list)
    titles: list[dict[str, Any]] = field(default_factory=list)
    issues: list[ReportIssue] = field(default_factory=list)
    broken_questions: list[BrokenQuestion] = field(default_factory=list)
    prepared_markdown: str = ""

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def requires_review(self) -> bool:
        return bool(self.broken_questions) or any(
            issue.severity in {"warning", "error"} for issue in self.issues
        )

    def to_prepared_json(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "question_count": self.question_count,
            "requires_review": self.requires_review,
            "titles": self.titles,
            "contexts": [context.to_dict() for context in self.contexts],
            "questions": [question.to_dict() for question in self.questions],
        }

    def to_report(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "question_count": self.question_count,
            "warning_count": sum(1 for issue in self.issues if issue.severity == "warning"),
            "error_count": sum(1 for issue in self.issues if issue.severity == "error"),
            "requires_review": self.requires_review,
            "issues": [issue.to_dict() for issue in self.issues],
            "broken_questions": [question.to_dict() for question in self.broken_questions],
        }


def prepare_google_docx(ir: DocumentIR) -> PreparedDocxResult:
    preparer = _GoogleDocxPreparer(ir)
    return preparer.run()


class _GoogleDocxPreparer:
    def __init__(self, ir: DocumentIR) -> None:
        self.ir = ir
        self.questions: list[PreparedQuestion] = []
        self.contexts: list[PreparedContext] = []
        self.titles: list[dict[str, Any]] = []
        self.issues: list[ReportIssue] = []
        self.broken_questions: list[BrokenQuestion] = []
        self.current_title: str | None = None
        self.active_context: PreparedContext | None = None
        self.pending_context_blocks: list[DocumentBlock] = []
        self.pending_media: list[str] = []
        self.context_counter = 0

    def run(self) -> PreparedDocxResult:
        blocks = self.ir.blocks
        index = 0
        while index < len(blocks):
            block = blocks[index]
            if block.kind == "heading":
                self._close_context()
                self.current_title = block.text
                self.titles.append({"text": block.text, "source_ref": block.source_ref})
                index += 1
                continue

            question_group = self._read_question_group(index)
            if question_group is not None:
                question, next_index = question_group
                self.questions.append(question)
                index = next_index
                continue

            if block.kind == "image":
                self._start_pending_context_if_needed(block)
                self.pending_media.extend(block.media_refs)
                index += 1
                continue

            if block.kind == "paragraph" and block.text:
                if block.page_break_before and self.pending_context_blocks:
                    self.issues.append(
                        _issue(
                            "context_continued_across_page_break",
                            "info",
                            "Контекст был разорван разрывом страницы в DOCX и склеен в один блок.",
                            "Проверь, что текст после разрыва страницы относится к тому же контексту.",
                            source_ref=block.source_ref,
                        )
                    )
                self._start_pending_context_if_needed(block)
                self.pending_context_blocks.append(block)
                index += 1
                continue

            index += 1

        result = PreparedDocxResult(
            source_id=self.ir.source_id,
            questions=self.questions,
            contexts=self.contexts,
            titles=self.titles,
            issues=self.issues,
            broken_questions=self.broken_questions,
        )
        result.prepared_markdown = _render_prepared_markdown(result)
        return result

    def _close_context(self) -> None:
        self.pending_context_blocks = []
        self.pending_media = []
        self.active_context = None

    def _start_pending_context_if_needed(self, block: DocumentBlock) -> None:
        if self.active_context is not None and not self.pending_context_blocks and not self.pending_media:
            self.active_context = None

    def _materialize_context(self) -> PreparedContext | None:
        if not self.pending_context_blocks and not self.pending_media:
            return self.active_context

        self.context_counter += 1
        text = "\n".join(
            normalize_text(block.text)
            for block in self.pending_context_blocks
            if block.text
        ).strip()
        source_refs = [block.source_ref for block in self.pending_context_blocks]
        context = PreparedContext(
            id=f"ctx-{self.context_counter:04d}",
            text=text,
            media=list(self.pending_media),
            source_refs=source_refs,
        )
        self.contexts.append(context)
        self.active_context = context
        self.pending_context_blocks = []
        self.pending_media = []
        return context

    def _read_question_group(self, index: int) -> tuple[PreparedQuestion, int] | None:
        blocks = self.ir.blocks
        question_block = blocks[index]
        if question_block.kind != "paragraph" or not question_block.text:
            return None
        question_line = split_option_line(question_block.text)
        question_text = question_block.text
        if question_line is not None:
            if not _looks_like_option_prefixed_question(question_line, blocks, index):
                return None
            question_text = question_line.text

        option_blocks: list[tuple[DocumentBlock, OptionLine]] = []
        cursor = index + 1
        while cursor < len(blocks):
            block = blocks[cursor]
            if block.kind != "paragraph":
                break
            option_line = split_option_line(block.text)
            if option_line is None:
                break
            if _starts_new_option_prefixed_question(option_blocks, option_line, blocks, cursor):
                break
            option_blocks.append((block, option_line))
            cursor += 1

        if len(option_blocks) < 2:
            return None

        if question_block.page_break_before and self.active_context is not None and not self.pending_context_blocks:
            self.issues.append(
                _issue(
                    "context_leak_blocked_by_page_break",
                    "warning",
                    "Разрыв страницы остановил протекание старого контекста к следующим вопросам.",
                    "Проверь, нужен ли этот контекст вопросам после разрыва.",
                    source_ref=question_block.source_ref,
                )
            )
            self.active_context = None

        pending_context_blocks = list(self.pending_context_blocks)
        context = self._materialize_context()
        local_issues: list[ReportIssue] = []
        if question_block.page_break_before and self.pending_context_blocks:
            local_issues.append(_question_split_issue(question_block))
        for option_block, _option_line in option_blocks:
            if option_block.page_break_before:
                local_issues.append(_question_split_issue(option_block))

        answer_line_block: DocumentBlock | None = None
        if cursor < len(blocks) and _is_answer_line(blocks[cursor].text):
            answer_line_block = blocks[cursor]
            if answer_line_block.page_break_before:
                local_issues.append(_question_split_issue(answer_line_block))
            cursor += 1

        question_text, option_blocks = _split_embedded_matching_statements(question_text, option_blocks)
        raw_labels = [option_line.raw_label for _block, option_line in option_blocks]
        bold_positions = [
            position
            for position, (option_block, _option_line) in enumerate(option_blocks, start=1)
            if option_block.bold_spans
        ]
        answer_line = answer_line_block.text if answer_line_block is not None else None
        resolution = resolve_answer_sources(
            raw_labels,
            answer_line=answer_line,
            bold_positions=bold_positions,
            source_ref=question_block.source_ref,
        )
        local_issues.extend(resolution.issues)

        all_text_blocks = [question_block, *(block for block, _option in option_blocks)]
        all_text_blocks.extend(pending_context_blocks)
        for text_block in all_text_blocks:
            local_issues.extend(detect_suspect_encoding(text_block.text, source_ref=text_block.source_ref))

        options = [
            PreparedOption(
                raw_label=option_line.raw_label,
                text=option_line.text,
                correct=position in resolution.answers,
                source_ref=option_block.source_ref,
            )
            for position, (option_block, option_line) in enumerate(option_blocks, start=1)
        ]
        question_index = len(self.questions) + 1
        question = PreparedQuestion(
            id=f"q-{question_index:04d}",
            question=normalize_text(question_text).rstrip(":"),
            options=options,
            answers=list(resolution.answers),
            mode=resolution.mode,
            answer_source=resolution.answer_source,
            title=self.current_title,
            context_id=context.id if context else None,
            source_ref=question_block.source_ref,
            answer_evidence={
                "answer_line_raw": answer_line,
                "raw_option_labels": raw_labels,
                "bold_positions": bold_positions,
                "answer_source": resolution.answer_source,
            },
            issues=local_issues,
        )
        self.issues.extend(local_issues)
        if any(issue.severity == "error" for issue in local_issues):
            first_error = next(issue for issue in local_issues if issue.severity == "error")
            self.broken_questions.append(
                BrokenQuestion(
                    source_question_index=question_index,
                    question_text=question.question,
                    options=[option.to_dict() for option in options],
                    answer_evidence=question.answer_evidence,
                    issue_code=first_error.code,
                    reason_ru=first_error.message_ru,
                    action_ru=first_error.action_ru,
                    source_ref=first_error.source_ref or question.source_ref,
                )
            )
        return question, cursor


def _is_answer_line(text: str) -> bool:
    lowered = normalize_text(text).casefold()
    return lowered.startswith("ответ") or lowered.startswith("правильный ответ")


def _question_split_issue(block: DocumentBlock) -> ReportIssue:
    return _issue(
        "question_split_by_page_break",
        "error",
        "Вопрос или варианты ответа разорваны разрывом страницы.",
        "Проверь этот вопрос в DOCX и подтверди, как его собрать.",
        source_ref=block.source_ref,
    )


def _issue(
    code: str,
    severity: str,
    message_ru: str,
    action_ru: str,
    *,
    source_ref: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReportIssue:
    return ReportIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        message_ru=message_ru,
        action_ru=action_ru,
        source_ref=source_ref or {},
        metadata=metadata or {},
    )


def _render_prepared_markdown(result: PreparedDocxResult) -> str:
    lines: list[str] = []
    last_title: str | None = None
    rendered_contexts: set[str] = set()
    contexts = {context.id: context for context in result.contexts}
    for question in result.questions:
        if question.title and question.title != last_title:
            lines.append(f"#SECTION: {question.title}")
            lines.append("")
            last_title = question.title
        if question.context_id and question.context_id not in rendered_contexts:
            context = contexts[question.context_id]
            lines.append("#CONTEXT")
            for media_ref in context.media:
                lines.append(f"![media]({media_ref})")
            if context.text:
                lines.append(context.text)
            lines.append("#END_CONTEXT")
            lines.append("")
            rendered_contexts.add(question.context_id)
        lines.append("#Q")
        lines.append(question.question)
        for option in question.options:
            lines.append("#A*" if option.correct else "#A")
            lines.append(option.text)
        lines.append("#END_Q")
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if lines else "")

def _is_first_option_label(raw_label: str) -> bool:
    return normalize_text(raw_label).casefold() in {"a", "а"}


def _looks_like_question_text(text: str) -> bool:
    stripped = normalize_text(text).rstrip()
    return stripped.endswith(":") or stripped.endswith("?")


def _count_following_option_lines(blocks: list[DocumentBlock], start: int) -> int:
    count = 0
    cursor = start
    while cursor < len(blocks):
        block = blocks[cursor]
        if block.kind != "paragraph" or split_option_line(block.text) is None:
            break
        count += 1
        cursor += 1
    return count


def _looks_like_option_prefixed_question(
    option_line: OptionLine,
    blocks: list[DocumentBlock],
    index: int,
) -> bool:
    return (
        _is_first_option_label(option_line.raw_label)
        and _looks_like_question_text(option_line.text)
        and _count_following_option_lines(blocks, index + 1) >= 2
    )


def _starts_new_option_prefixed_question(
    option_blocks: list[tuple[DocumentBlock, OptionLine]],
    option_line: OptionLine,
    blocks: list[DocumentBlock],
    cursor: int,
) -> bool:
    return (
        len(option_blocks) >= 2
        and _looks_like_option_prefixed_question(option_line, blocks, cursor)
    )


def _looks_like_matching_answer_choice(text: str) -> bool:
    normalized = normalize_text(text)
    return any(char.isdigit() for char in normalized) and "," in normalized and any(
        separator in normalized for separator in ("-", "–", "—")
    )


def _split_embedded_matching_statements(
    question_text: str,
    option_blocks: list[tuple[DocumentBlock, OptionLine]],
) -> tuple[str, list[tuple[DocumentBlock, OptionLine]]]:
    if len(option_blocks) < 6:
        return question_text, option_blocks

    for split_index in range(2, len(option_blocks) - 1):
        statement_blocks = option_blocks[:split_index]
        answer_blocks = option_blocks[split_index:]
        if len(answer_blocks) < 2:
            continue
        if not all(_looks_like_matching_answer_choice(option.text) for _block, option in answer_blocks):
            continue
        statement_lines = [normalize_text(block.text) for block, _option in statement_blocks]
        return "\n".join([question_text, *statement_lines]), answer_blocks

    return question_text, option_blocks
