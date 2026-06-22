"""Pure validation service for Wave 2 clean quiz JSON artifacts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from backend.pipeline.encoding import normalize_text

IssueSeverity = Literal["error", "warning"]

KNOWN_ITEM_TYPES = frozenset({"title", "context", "reset_context", "question"})
QUESTION_MODES = frozenset({"single", "multiple"})
MAX_OPTIONS = 10
SIMILAR_QUESTION_THRESHOLD = 0.92
MEDIA_SUFFIXES = frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"})


@dataclass(slots=True)
class ValidationIssue:
    code: str
    severity: IssueSeverity
    message_ru: str
    action_ru: str
    source_question_index: int | None = None
    clean_item_index: int | None = None
    question_text: str = ""
    actions: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message_ru": self.message_ru,
            "action_ru": self.action_ru,
            "actions": list(self.actions),
            "evidence": dict(self.evidence),
        }
        if self.source_question_index is not None:
            data["source_question_index"] = self.source_question_index
        if self.clean_item_index is not None:
            data["clean_item_index"] = self.clean_item_index
        if self.question_text:
            data["question_text"] = self.question_text
        return data


@dataclass(slots=True)
class ValidationReport:
    quiz_file_hash: str
    question_count: int
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def hard_errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def has_hard_errors(self) -> bool:
        return bool(self.hard_errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "validation-report.v1",
            "quiz_file_hash": self.quiz_file_hash,
            "question_count": self.question_count,
            "hard_error_count": len(self.hard_errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def stable_quiz_hash(clean_json: Any) -> str:
    """Hash quiz data using canonical JSON so formatting-only changes do not matter."""
    encoded = json.dumps(
        clean_json,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def compute_quiz_file_hash(path: str | Path) -> str:
    quiz_path = Path(path)
    raw = quiz_path.read_bytes()
    try:
        return stable_quiz_hash(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "sha256:" + hashlib.sha256(raw).hexdigest()


def load_clean_quiz_file(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Clean quiz JSON must be a top-level object")
    return data


def validate_clean_quiz_file(
    path: str | Path,
    *,
    allow_duplicate_questions: bool | None = None,
    media_base_dir: str | Path | None = None,
) -> ValidationReport:
    quiz_path = Path(path)
    try:
        clean_json = json.loads(quiz_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ValidationReport(
            quiz_file_hash=compute_quiz_file_hash(quiz_path),
            question_count=0,
            issues=[
                _error(
                    "invalid_json",
                    "JSON-файл clean quiz не читается.",
                    "Исправь JSON и запусти validation заново.",
                    evidence={"message": str(exc)},
                )
            ],
        )
    return validate_clean_quiz(
        clean_json,
        allow_duplicate_questions=allow_duplicate_questions,
        media_base_dir=media_base_dir,
    )


def validate_clean_quiz(
    clean_json: Any,
    *,
    allow_duplicate_questions: bool | None = None,
    media_base_dir: str | Path | None = None,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    question_count = 0
    seen_questions: list[tuple[int, str, str]] = []
    media_base = Path(media_base_dir) if media_base_dir is not None else None

    if not isinstance(clean_json, Mapping):
        return ValidationReport(
            quiz_file_hash=stable_quiz_hash(clean_json),
            question_count=0,
            issues=[
                _error(
                    "invalid_schema",
                    "Clean quiz JSON должен быть объектом.",
                    "Исправь верхний уровень JSON.",
                )
            ],
        )

    title = clean_json.get("title")
    if not isinstance(title, str) or not normalize_text(title):
        issues.append(
            _error(
                "invalid_schema",
                "В clean JSON должен быть непустой строковый title.",
                "Заполни title в JSON.",
            )
        )

    settings = clean_json.get("settings")
    if not isinstance(settings, Mapping):
        issues.append(
            _error(
                "invalid_schema",
                "В clean JSON должен быть объект settings.",
                "Исправь settings в JSON.",
            )
        )

    items = clean_json.get("items")
    if not isinstance(items, list):
        issues.append(
            _error(
                "invalid_schema",
                "В clean JSON должен быть массив items.",
                "Исправь items в JSON.",
            )
        )
        return ValidationReport(
            quiz_file_hash=stable_quiz_hash(clean_json),
            question_count=0,
            issues=issues,
        )

    duplicate_questions_allowed = _allow_duplicate_questions(
        clean_json,
        override=allow_duplicate_questions,
    )

    for clean_item_index, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            issues.append(
                _error(
                    "invalid_schema",
                    f"Item #{clean_item_index} должен быть объектом.",
                    "Исправь item в JSON.",
                    clean_item_index=clean_item_index,
                )
            )
            continue

        item_type = item.get("type")
        if item_type not in KNOWN_ITEM_TYPES:
            issues.append(
                _error(
                    "invalid_schema",
                    f"Item #{clean_item_index} содержит неизвестный type.",
                    "Исправь type на title, context, reset_context или question.",
                    clean_item_index=clean_item_index,
                    evidence={"type": item_type},
                )
            )
            continue

        if item_type == "context":
            issues.extend(
                _validate_media(
                    item.get("media"),
                    media_base=media_base,
                    clean_item_index=clean_item_index,
                )
            )
            continue
        if item_type != "question":
            continue

        question_count += 1
        question_text = normalize_text(item.get("question")) if isinstance(item.get("question"), str) else ""
        issues.extend(
            _validate_question_item(
                item,
                source_question_index=question_count,
                clean_item_index=clean_item_index,
                question_text=question_text,
                media_base=media_base,
            )
        )
        if question_text:
            normalized_key = _question_key(question_text)
            seen_questions.append((question_count, normalized_key, question_text))

    if not duplicate_questions_allowed:
        issues.extend(_duplicate_question_warnings(seen_questions))
    return ValidationReport(
        quiz_file_hash=stable_quiz_hash(clean_json),
        question_count=question_count,
        issues=issues,
    )


def _allow_duplicate_questions(
    clean_json: Mapping[str, Any],
    *,
    override: bool | None,
) -> bool:
    if override is not None:
        return bool(override)
    if bool(clean_json.get("allow_duplicate_questions")):
        return True
    settings = clean_json.get("settings")
    return isinstance(settings, Mapping) and bool(settings.get("allow_duplicate_questions"))


def _validate_question_item(
    item: Mapping[str, Any],
    *,
    source_question_index: int,
    clean_item_index: int,
    question_text: str,
    media_base: Path | None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    question_kwargs = {
        "source_question_index": source_question_index,
        "clean_item_index": clean_item_index,
        "question_text": question_text,
    }

    if not question_text:
        issues.append(
            _error(
                "question_text_empty",
                "Текст вопроса пустой.",
                "Заполни вопрос или пропусти его в review.",
                **question_kwargs,
            )
        )

    options_value = item.get("options")
    option_texts: list[str] = []
    if not isinstance(options_value, list):
        issues.append(
            _error(
                "invalid_schema",
                "Question item должен содержать массив options.",
                "Исправь options в JSON.",
                **question_kwargs,
            )
        )
    else:
        for option_index, option in enumerate(options_value, start=1):
            if not isinstance(option, Mapping):
                issues.append(
                    _error(
                        "invalid_schema",
                        f"Вариант #{option_index} должен быть объектом.",
                        "Исправь options[] на объекты с полем text.",
                        evidence={"option_index": option_index},
                        **question_kwargs,
                    )
                )
                option_texts.append("")
                continue
            text_value = option.get("text")
            option_text = normalize_text(text_value) if isinstance(text_value, str) else ""
            option_texts.append(option_text)
            if not option_text:
                issues.append(
                    _error(
                        "option_text_empty",
                        f"Вариант #{option_index} пустой.",
                        "Заполни или удали пустой вариант, затем проверь answers.",
                        evidence={"option_index": option_index},
                        **question_kwargs,
                    )
                )
        if len(option_texts) < 2:
            issues.append(
                _error(
                    "too_few_options",
                    "У вопроса меньше двух вариантов ответа.",
                    "Добавь варианты или пропусти вопрос.",
                    evidence={"option_count": len(option_texts)},
                    **question_kwargs,
                )
            )
        if len(option_texts) > MAX_OPTIONS:
            issues.append(
                _error(
                    "too_many_options",
                    f"У вопроса больше {MAX_OPTIONS} вариантов ответа.",
                    "Уменьши число вариантов или проверь поддержку upload flow.",
                    evidence={"option_count": len(option_texts), "max_options": MAX_OPTIONS},
                    **question_kwargs,
                )
            )

    answers_value = item.get("answers")
    answers: list[int] = []
    if not isinstance(answers_value, list):
        issues.append(
            _error(
                "answer_missing",
                "У вопроса нет массива answers.",
                "Укажи правильный ответ или пропусти вопрос.",
                **question_kwargs,
            )
        )
    else:
        for answer in answers_value:
            if isinstance(answer, bool) or not isinstance(answer, int):
                issues.append(
                    _error(
                        "invalid_schema",
                        "answers должен содержать 1-based целые номера вариантов.",
                        "Исправь answers в JSON.",
                        evidence={"answer": answer},
                        **question_kwargs,
                    )
                )
                continue
            answers.append(answer)
        if not answers:
            issues.append(
                _error(
                    "answer_missing",
                    "У вопроса нет правильного ответа.",
                    "Укажи правильный ответ или пропусти вопрос.",
                    **question_kwargs,
                )
            )
        for answer in answers:
            if answer < 1 or answer > len(option_texts):
                issues.append(
                    _error(
                        "answer_index_out_of_range",
                        "answers указывает на несуществующий вариант.",
                        "Исправь номер ответа или пропусти вопрос.",
                        evidence={"answer": answer, "option_count": len(option_texts)},
                        **question_kwargs,
                    )
                )
        if len(set(answers)) != len(answers):
            issues.append(
                _error(
                    "answer_index_duplicate",
                    "В answers повторяется один и тот же номер.",
                    "Убери дублирующийся номер ответа.",
                    evidence={"answers": list(answers)},
                    **question_kwargs,
                )
            )

    mode = item.get("mode")
    if mode not in QUESTION_MODES:
        issues.append(
            _error(
                "mode_invalid",
                "mode должен быть single или multiple.",
                "Исправь mode в JSON.",
                evidence={"mode": mode},
                **question_kwargs,
            )
        )
    elif mode == "single" and len(answers) > 1:
        issues.append(
            _error(
                "mode_answer_count_conflict",
                "single-вопрос содержит несколько правильных ответов.",
                "Переключи mode на multiple или оставь один answer.",
                evidence={"mode": mode, "answers": list(answers)},
                **question_kwargs,
            )
        )

    issues.extend(
        _validate_media(
            item.get("media"),
            media_base=media_base,
            source_question_index=source_question_index,
            clean_item_index=clean_item_index,
            question_text=question_text,
        )
    )
    return issues


def _validate_media(
    media_value: Any,
    *,
    media_base: Path | None,
    source_question_index: int | None = None,
    clean_item_index: int | None = None,
    question_text: str = "",
) -> list[ValidationIssue]:
    if media_value is None:
        return []

    issues: list[ValidationIssue] = []
    if not isinstance(media_value, list):
        return [
            _error(
                "invalid_schema",
                "media должен быть массивом строк.",
                "Исправь media в JSON.",
                source_question_index=source_question_index,
                clean_item_index=clean_item_index,
                question_text=question_text,
            )
        ]

    for media_path in media_value:
        if not isinstance(media_path, str) or not normalize_text(media_path):
            issues.append(
                _error(
                    "invalid_schema",
                    "media должен содержать непустые строки.",
                    "Исправь media в JSON.",
                    source_question_index=source_question_index,
                    clean_item_index=clean_item_index,
                    question_text=question_text,
                    evidence={"media": media_path},
                )
            )
            continue
        if media_base is None:
            continue
        if not _media_path_exists(media_base, media_path):
            issues.append(
                _error(
                    "media_missing",
                    "Указанный media-файл не найден в разрешенной базовой директории.",
                    "Добавь файл, исправь путь или пропусти affected question.",
                    source_question_index=source_question_index,
                    clean_item_index=clean_item_index,
                    question_text=question_text,
                    evidence={"media": media_path},
                )
            )
    return issues


def _media_path_exists(media_base: Path, media_path: str) -> bool:
    return _resolve_media_path(media_base, media_path) is not None


def _resolve_media_path(media_base: Path, media_path: str) -> Path | None:
    normalized = media_path.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/") or _looks_like_windows_absolute_path(normalized):
        return None

    candidates = [normalized]
    if normalized.startswith("media/"):
        candidates.append(normalized.split("/", 1)[1])

    base = media_base.resolve()
    for candidate_path in candidates:
        candidate = (base / candidate_path).resolve()
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        if candidate.suffix.lower() not in MEDIA_SUFFIXES:
            continue
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _looks_like_windows_absolute_path(path: str) -> bool:
    return len(path) >= 3 and path[1] == ":" and path[0].isalpha() and path[2] == "/"


def _duplicate_question_warnings(
    seen_questions: Iterable[tuple[int, str, str]]
) -> list[ValidationIssue]:
    warnings: list[ValidationIssue] = []
    questions = list(seen_questions)
    for right_position, (right_index, right_key, right_text) in enumerate(questions):
        for left_index, left_key, left_text in questions[:right_position]:
            if right_key == left_key:
                similarity = 1.0
            else:
                similarity = SequenceMatcher(None, left_key, right_key).ratio()
            if similarity < SIMILAR_QUESTION_THRESHOLD:
                continue
            warnings.append(
                _warning(
                    "possible_duplicate_question",
                    "Вопрос похож на уже встречавшийся вопрос.",
                    "Проверь оба вопроса и выбери confirm, send_both, skip_question или edit.",
                    source_question_index=right_index,
                    question_text=right_text,
                    actions=["confirm", "send_both", "skip_question", "edit", "abort"],
                    evidence={
                        "matched_question_indexes": [left_index],
                        "matched_question_text": left_text,
                        "similarity": round(similarity, 3),
                    },
                )
            )
            break
    return warnings


def _question_key(text: str) -> str:
    return " ".join(normalize_text(text).casefold().split())


def _error(
    code: str,
    message_ru: str,
    action_ru: str,
    *,
    source_question_index: int | None = None,
    clean_item_index: int | None = None,
    question_text: str = "",
    evidence: dict[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity="error",
        message_ru=message_ru,
        action_ru=action_ru,
        source_question_index=source_question_index,
        clean_item_index=clean_item_index,
        question_text=question_text,
        actions=["skip_question", "edit", "abort"] if source_question_index is not None else ["edit", "abort"],
        evidence=evidence or {},
    )


def _warning(
    code: str,
    message_ru: str,
    action_ru: str,
    *,
    source_question_index: int | None = None,
    clean_item_index: int | None = None,
    question_text: str = "",
    actions: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity="warning",
        message_ru=message_ru,
        action_ru=action_ru,
        source_question_index=source_question_index,
        clean_item_index=clean_item_index,
        question_text=question_text,
        actions=actions or ["confirm", "skip_question", "edit", "abort"],
        evidence=evidence or {},
    )
