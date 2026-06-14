# GPT Normalizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `gpt_normalizer.py`, a CLI that converts `questions_v2.json` into validated `clean_questions.json`, `review_questions.json`, and `normalizer_report.json`.

**Architecture:** Keep the normalizer separate from the existing Telethon uploader. Put pure schema and validation logic in `normalizer_models.py`, JSON/file/report helpers in `normalizer_io.py`, and API orchestration plus CLI in `gpt_normalizer.py`. The OpenAI call is behind a small function so unit tests can use fake normalizers without network access.

**Tech Stack:** Python 3.10+, Pydantic v2, OpenAI Python SDK Responses API with Structured Outputs, pytest, python-dotenv.

---

## File Structure

- Create: `normalizer_models.py`
  - Defines allowed review reasons, Pydantic models, output builders, and local validation.
- Create: `normalizer_io.py`
  - Reads `questions_v2.json`, writes JSON atomically, and builds report objects.
- Create: `gpt_normalizer.py`
  - CLI entry point, prompt construction, OpenAI adapter, retry loop, and dataset orchestration.
- Create: `tests/fixtures/questions_v2_sample.json`
  - Small deterministic v2 fixture with clean, dirty, and media-linked items.
- Create: `tests/test_normalizer_models.py`
  - Tests schema validation, review reasons, source id preservation, and weak distractor checks.
- Create: `tests/test_normalizer_io.py`
  - Tests input parsing, atomic write behavior, and report counts.
- Create: `tests/test_gpt_normalizer.py`
  - Tests orchestration using fake GPT outputs; no real API calls.
- Modify: `requirements.txt`
  - Add `openai` and `pytest`.
- Modify: `.env.example`
  - Add `OPENAI_API_KEY` and `OPENAI_MODEL`.
- Modify: `.gitignore`
  - Ignore generated question/report files.
- Modify: `README.md`
  - Add a short `gpt_normalizer.py` usage section.

---

## Task 1: Dependencies, Env, And Generated File Ignores

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Update `requirements.txt`**

Set the file to:

```text
telethon>=1.36
pydantic>=2.0
python-dotenv>=1.0
openai>=1.68.0
pytest>=8.0
```

- [ ] **Step 2: Update `.env.example`**

Append:

```env

# OpenAI API for gpt_normalizer.py
OPENAI_API_KEY=replace_me
OPENAI_MODEL=gpt-4.1-mini
```

- [ ] **Step 3: Update `.gitignore`**

Append:

```gitignore

# Generated quiz pipeline data
questions_v2.json
clean_questions.json
review_questions.json
normalizer_report.json
.normalizer_tmp/
quizbot_pipeline_v2/
```

- [ ] **Step 4: Install dependencies**

Run:

```bash
python -m pip install -r requirements.txt
```

Expected: `Successfully installed` or `Requirement already satisfied` for `openai` and `pytest`.

- [ ] **Step 5: Verify OpenAI SDK exposes Responses API**

Run:

```bash
python -c "from openai import OpenAI; c = OpenAI(api_key='test'); print(hasattr(c, 'responses'))"
```

Expected:

```text
True
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.example .gitignore
git commit -m "chore: add normalizer dependencies and generated ignores"
```

---

## Task 2: Add Normalizer Test Fixtures

**Files:**
- Create: `tests/fixtures/questions_v2_sample.json`

- [ ] **Step 1: Create fixture directory and file**

Create `tests/fixtures/questions_v2_sample.json`:

```json
{
  "quiz_title": "История Казахстана",
  "quiz_description": "Тест по истории Казахстана",
  "format_version": "2.0",
  "telegram_limits": {
    "poll_question_max_chars": 300,
    "option_max_chars": 100,
    "explanation_max_chars": 200
  },
  "report": {
    "items_total": 3
  },
  "questions": [
    {
      "id": 1,
      "date": "10 мая",
      "section": "",
      "context_title": "",
      "context": "",
      "media": [],
      "question": "Какой указ 1822 года заложил основу для ликвидации ханской власти в Среднем жузе?",
      "correct_answer": "Устав о сибирских киргизах 1822 года, разработанный М",
      "options": [
        "Устав о сибирских киргизах 1822 года, разработанный М",
        "Внедрение колониальной системы управления привело к ограничению власти биев и султанов",
        "Массовый голод и откочевки привели к катастрофическому сокращению населения",
        "Правительство Алаш-Орды вступило в противостояние с большевиками"
      ],
      "correct": 1,
      "explanation": "Устав о сибирских киргизах 1822 года, разработанный М. Сперанским, упразднил ханскую власть.",
      "explanation_full": "Устав о сибирских киргизах 1822 года, разработанный М. Сперанским, ввел систему окружного управления и окончательно упразднил институт ханской власти на территории Среднего жуза.",
      "type": "short_answer_with_explanation",
      "source": "docx_v2",
      "distractors_source": "heuristic_same_document"
    },
    {
      "id": 2,
      "date": "11 мая",
      "section": "УТРО",
      "context_title": "Контекст Nº2",
      "context": "На иллюстрации показан исторический деятель эпохи средневековых государств.",
      "media": ["media/image_003.png"],
      "question": "На портрете изображён:",
      "correct_answer": "Эмир Тимур",
      "options": ["Эмир Тимур", "Абылай хан", "Касым хан", "Тауке хан"],
      "correct": 1,
      "explanation": "На портрете изображён Эмир Тимур.",
      "explanation_full": "На портрете изображён Эмир Тимур, правитель XIV века.",
      "type": "media_context_quiz",
      "source": "docx_v2"
    },
    {
      "id": 3,
      "date": "11 мая",
      "section": "ОБЕД",
      "context_title": "",
      "context": "",
      "media": [],
      "question": "Кто возглавил национально-освободительное движение казахов Младшего жуза?",
      "correct_answer": "Сырым Датов",
      "options": ["Сырым Датов", "Кенесары Касымов", "Жанкожа Нурмухамедулы", "Есет Котибарулы"],
      "correct": 1,
      "explanation": "Движение против колониальной политики возглавил батыр Сырым Датов.",
      "explanation_full": "Движение против колониальной политики возглавил батыр Сырым Датов.",
      "type": "simple_quiz",
      "source": "docx_v2"
    }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/questions_v2_sample.json
git commit -m "test: add normalizer v2 fixture"
```

---

## Task 3: Local Models And Validator

**Files:**
- Create: `tests/test_normalizer_models.py`
- Create: `normalizer_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/test_normalizer_models.py`:

```python
import pytest

from normalizer_models import (
    ALLOWED_ERROR_REASONS,
    CleanQuestion,
    LocalValidationError,
    ReviewQuestion,
    validate_clean_question,
)


def valid_clean_payload():
    return {
        "source_item_id": 17,
        "date": "11 мая",
        "section": "УТРО",
        "context_title": "Контекст Nº2",
        "context": "Текст контекста",
        "media": ["media/image_003.png"],
        "question": "На портрете изображён:",
        "correct_answer": "Эмир Тимур",
        "options": ["Эмир Тимур", "Абылай хан", "Касым хан", "Тауке хан"],
        "correct": 1,
        "explanation": "На портрете изображён Эмир Тимур.",
        "explanation_full": "На портрете изображён Эмир Тимур, правитель XIV века.",
        "type": "media_context_quiz",
        "source": "gpt_normalized",
        "quality_flags": [],
    }


def test_clean_question_accepts_valid_payload():
    item = CleanQuestion(**valid_clean_payload())
    validate_clean_question(item)
    assert item.source_item_id == 17


def test_rejects_too_long_question():
    payload = valid_clean_payload()
    payload["question"] = "А" * 301
    item = CleanQuestion(**payload)
    with pytest.raises(LocalValidationError) as exc:
        validate_clean_question(item)
    assert exc.value.reason == "too_long_question"


def test_rejects_duplicate_options_after_normalization():
    payload = valid_clean_payload()
    payload["options"] = ["Эмир Тимур", " эмир   тимур ", "Касым хан", "Тауке хан"]
    item = CleanQuestion(**payload)
    with pytest.raises(LocalValidationError) as exc:
        validate_clean_question(item)
    assert exc.value.reason == "duplicate_options"


def test_rejects_correct_answer_mismatch():
    payload = valid_clean_payload()
    payload["correct_answer"] = "Тамерлан"
    item = CleanQuestion(**payload)
    with pytest.raises(LocalValidationError) as exc:
        validate_clean_question(item)
    assert exc.value.reason == "correct_not_in_options"


def test_rejects_weak_distractor_substring():
    payload = valid_clean_payload()
    payload["options"] = ["Эмир Тимур", "Тимур", "Касым хан", "Тауке хан"]
    item = CleanQuestion(**payload)
    with pytest.raises(LocalValidationError) as exc:
        validate_clean_question(item)
    assert exc.value.reason == "weak_distractors"


def test_review_question_requires_allowed_reason():
    assert "bad_json" in ALLOWED_ERROR_REASONS
    ReviewQuestion(
        source_item_id=1,
        error_reason="bad_json",
        raw_item={"id": 1},
        last_gpt_output={},
        attempts=1,
        notes="JSON parsing failed",
    )
    with pytest.raises(ValueError):
        ReviewQuestion(
            source_item_id=1,
            error_reason="unknown_reason",
            raw_item={"id": 1},
            last_gpt_output={},
            attempts=1,
            notes="bad reason",
        )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_normalizer_models.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'normalizer_models'`.

- [ ] **Step 3: Create `normalizer_models.py`**

```python
"""Models and local validation for GPT-normalized quiz questions."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ErrorReason = Literal[
    "bad_json",
    "too_long_question",
    "too_long_option",
    "too_long_explanation",
    "duplicate_options",
    "correct_not_in_options",
    "weak_distractors",
    "missing_required_field",
    "gpt_request_failed",
    "max_retries_exceeded",
    "needs_visual_review",
]

ALLOWED_ERROR_REASONS = set(ErrorReason.__args__)


class LocalValidationError(ValueError):
    """Validation failure carrying a stable review error reason."""

    def __init__(self, reason: ErrorReason, message: str):
        super().__init__(message)
        self.reason = reason


class RawQuestion(BaseModel):
    id: int
    date: str = ""
    section: str = ""
    context_title: str = ""
    context: str = ""
    media: list[str] = Field(default_factory=list)
    question: str
    correct_answer: str = ""
    options: list[str] = Field(default_factory=list)
    correct: int | None = None
    explanation: str = ""
    explanation_full: str = ""
    type: str = ""
    source: str = ""


class GPTQuestion(BaseModel):
    question: str
    correct_answer: str
    options: list[str]
    correct: int
    explanation: str
    explanation_full: str
    quality_flags: list[str] = Field(default_factory=list)


class CleanQuestion(GPTQuestion):
    source_item_id: int
    date: str = ""
    section: str = ""
    context_title: str = ""
    context: str = ""
    media: list[str] = Field(default_factory=list)
    type: str = ""
    source: str = "gpt_normalized"

    @field_validator("source")
    @classmethod
    def source_is_gpt_normalized(cls, value: str) -> str:
        if value != "gpt_normalized":
            raise ValueError("source must be gpt_normalized")
        return value


class ReviewQuestion(BaseModel):
    source_item_id: int
    error_reason: ErrorReason
    raw_item: dict[str, Any]
    last_gpt_output: dict[str, Any] | str | None
    attempts: int = Field(ge=0)
    notes: str = ""


def normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _raise(reason: ErrorReason, message: str) -> None:
    raise LocalValidationError(reason, message)


def validate_clean_question(item: CleanQuestion) -> None:
    if not (1 <= len(item.question) <= 300):
        _raise("too_long_question", f"question length is {len(item.question)}")

    if len(item.options) != 4:
        _raise("missing_required_field", f"expected 4 options, got {len(item.options)}")

    for option in item.options:
        if not (1 <= len(option) <= 100):
            _raise("too_long_option", f"option length is {len(option)}: {option!r}")

    if len(item.explanation) > 200:
        _raise("too_long_explanation", f"explanation length is {len(item.explanation)}")

    if not (1 <= item.correct <= 4):
        _raise("correct_not_in_options", f"correct index out of range: {item.correct}")

    normalized_options = [normalize_key(option) for option in item.options]
    if len(set(normalized_options)) != len(normalized_options):
        _raise("duplicate_options", "options are not unique after normalization")

    correct_option = item.options[item.correct - 1]
    if normalize_key(item.correct_answer) != normalize_key(correct_option):
        _raise("correct_not_in_options", "correct_answer does not match options[correct - 1]")

    correct_key = normalize_key(correct_option)
    for option in item.options:
        option_key = normalize_key(option)
        if option_key == correct_key:
            continue
        if "…" in option or "..." in option:
            _raise("weak_distractors", f"option contains ellipsis: {option!r}")
        if option_key in {"вариант 1", "вариант 2", "вариант 3", "другое", "нет правильного варианта"}:
            _raise("weak_distractors", f"technical fallback option: {option!r}")
        if correct_key in option_key or option_key in correct_key:
            _raise("weak_distractors", f"option overlaps with correct answer: {option!r}")


def build_clean_question(raw: RawQuestion, gpt: GPTQuestion) -> CleanQuestion:
    return CleanQuestion(
        source_item_id=raw.id,
        date=raw.date,
        section=raw.section,
        context_title=raw.context_title,
        context=raw.context,
        media=list(raw.media),
        question=gpt.question,
        correct_answer=gpt.correct_answer,
        options=list(gpt.options),
        correct=gpt.correct,
        explanation=gpt.explanation,
        explanation_full=gpt.explanation_full,
        type=raw.type,
        source="gpt_normalized",
        quality_flags=list(gpt.quality_flags),
    )
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest tests/test_normalizer_models.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add normalizer_models.py tests/test_normalizer_models.py
git commit -m "feat: add normalizer models and validation"
```

---

## Task 4: JSON IO And Report Helpers

**Files:**
- Create: `tests/test_normalizer_io.py`
- Create: `normalizer_io.py`

- [ ] **Step 1: Write failing IO tests**

Create `tests/test_normalizer_io.py`:

```python
import json
from pathlib import Path

from normalizer_io import build_report, load_v2_dataset, write_json_atomic
from normalizer_models import CleanQuestion, ReviewQuestion


def test_load_v2_dataset_reads_questions_fixture():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")
    assert data["quiz_title"] == "История Казахстана"
    assert len(data["questions"]) == 3
    assert data["questions"][0]["id"] == 1


def test_write_json_atomic_writes_utf8_json(tmp_path):
    target = tmp_path / "out.json"
    write_json_atomic(target, {"text": "История Казахстана"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"text": "История Казахстана"}
    assert not list(tmp_path.glob("*.tmp"))


def test_build_report_counts_review_reasons():
    clean = [
        CleanQuestion(
            source_item_id=1,
            question="Кто возглавил движение?",
            correct_answer="Сырым Датов",
            options=["Сырым Датов", "Абылай хан", "Касым хан", "Тауке хан"],
            correct=1,
            explanation="Движение возглавил Сырым Датов.",
            explanation_full="Движение против колониальной политики возглавил Сырым Датов.",
        )
    ]
    review = [
        ReviewQuestion(
            source_item_id=2,
            error_reason="needs_visual_review",
            raw_item={"id": 2},
            last_gpt_output={},
            attempts=1,
            notes="media-dependent",
        )
    ]
    report = build_report(
        input_path="questions_v2.json",
        output_path="clean_questions.json",
        review_path="review_questions.json",
        model="gpt-4.1-mini",
        max_retries=3,
        total=2,
        clean=clean,
        review=review,
    )
    assert report["items_total"] == 2
    assert report["items_clean"] == 1
    assert report["items_review"] == 1
    assert report["error_reason_counts"] == {"needs_visual_review": 1}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_normalizer_io.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'normalizer_io'`.

- [ ] **Step 3: Create `normalizer_io.py`**

```python
"""File IO helpers for the GPT normalizer."""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from normalizer_models import CleanQuestion, ReviewQuestion


def load_v2_dataset(path: str | Path) -> dict[str, Any]:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected top-level JSON object")
    if not isinstance(data.get("questions"), list):
        raise ValueError("Expected top-level 'questions' list")
    return data


def write_json_atomic(path: str | Path, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)


def clean_payload(source_data: dict[str, Any], clean: list[CleanQuestion]) -> dict[str, Any]:
    return {
        "quiz_title": source_data.get("quiz_title", ""),
        "quiz_description": source_data.get("quiz_description", ""),
        "format_version": "2.1-clean",
        "questions": [item.model_dump() for item in clean],
    }


def review_payload(source_data: dict[str, Any], review: list[ReviewQuestion]) -> dict[str, Any]:
    return {
        "quiz_title": source_data.get("quiz_title", ""),
        "quiz_description": source_data.get("quiz_description", ""),
        "format_version": "2.1-review",
        "questions": [item.model_dump() for item in review],
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_report(
    *,
    input_path: str,
    output_path: str,
    review_path: str,
    model: str,
    max_retries: int,
    total: int,
    clean: list[CleanQuestion],
    review: list[ReviewQuestion],
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    reason_counts = Counter(item.error_reason for item in review)
    return {
        "input": input_path,
        "output": output_path,
        "review": review_path,
        "model": model,
        "started_at": started_at or utc_now_iso(),
        "finished_at": finished_at or utc_now_iso(),
        "items_total": total,
        "items_clean": len(clean),
        "items_review": len(review),
        "max_retries": max_retries,
        "error_reason_counts": dict(sorted(reason_counts.items())),
    }
```

- [ ] **Step 4: Run IO tests**

Run:

```bash
python -m pytest tests/test_normalizer_io.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Run all normalizer unit tests**

Run:

```bash
python -m pytest tests/test_normalizer_models.py tests/test_normalizer_io.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add normalizer_io.py tests/test_normalizer_io.py
git commit -m "feat: add normalizer json io and reports"
```

---

## Task 5: Prompt, Structured Output Schema, And OpenAI Adapter

**Files:**
- Create: `tests/test_gpt_normalizer.py`
- Create: `gpt_normalizer.py`

- [ ] **Step 1: Write failing prompt/schema tests**

Create `tests/test_gpt_normalizer.py`:

```python
import json

from gpt_normalizer import (
    build_messages,
    build_response_schema,
    extract_json_object,
)
from normalizer_models import RawQuestion


def raw_question():
    return RawQuestion(
        id=1,
        date="10 мая",
        section="",
        context_title="",
        context="",
        media=[],
        question="Какой указ 1822 года заложил основу для ликвидации ханской власти?",
        correct_answer="Устав о сибирских киргизах 1822 года, разработанный М",
        options=[
            "Устав о сибирских киргизах 1822 года, разработанный М",
            "Внедрение колониальной системы управления",
            "Массовый голод и откочевки",
            "Правительство Алаш-Орды",
        ],
        correct=1,
        explanation="Устав 1822 года упразднил ханскую власть.",
        explanation_full="Устав о сибирских киргизах 1822 года, разработанный М. Сперанским, ввел окружное управление.",
        type="short_answer_with_explanation",
        source="docx_v2",
    )


def test_build_messages_include_json_instruction_and_source_item():
    messages = build_messages(raw_question(), previous_error=None)
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "JSON" in serialized
    assert "source_item_id" not in serialized
    assert "Не добавляй факты" in serialized
    assert "Устав о сибирских киргизах" in serialized


def test_build_response_schema_has_required_fields_and_no_extra_properties():
    schema = build_response_schema()
    assert schema["type"] == "json_schema"
    assert schema["strict"] is True
    inner = schema["schema"]
    assert inner["additionalProperties"] is False
    assert set(inner["required"]) == {
        "question",
        "correct_answer",
        "options",
        "correct",
        "explanation",
        "explanation_full",
        "quality_flags",
    }


def test_extract_json_object_accepts_dict_and_json_string():
    assert extract_json_object({"question": "Q"}) == {"question": "Q"}
    assert extract_json_object('{"question":"Q"}') == {"question": "Q"}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_gpt_normalizer.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing functions in `gpt_normalizer.py`.

- [ ] **Step 3: Create `gpt_normalizer.py` with prompt/schema/API helpers**

```python
"""CLI and OpenAI orchestration for normalizing v2 quiz questions."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI

from normalizer_io import (
    build_report,
    clean_payload,
    load_v2_dataset,
    review_payload,
    utc_now_iso,
    write_json_atomic,
)
from normalizer_models import (
    CleanQuestion,
    GPTQuestion,
    LocalValidationError,
    RawQuestion,
    ReviewQuestion,
    build_clean_question,
    validate_clean_question,
)


SYSTEM_PROMPT = """Ты нормализуешь вопросы для Telegram quiz poll.
Верни только JSON по заданной схеме.
Не добавляй факты вне предоставленного item.
Не делай ложные варианты частично правильными.
Не используй варианты вроде "все ответы верны" или "нет правильного ответа".
Не обрезай ответы многоточием.
Сохраняй историческую точность в рамках предоставленного контекста.
Делай варианты одного типа и похожей длины.
Если вопрос зависит от изображения и текстового контекста недостаточно, добавь quality_flags ["needs_visual_review"].
Лимиты: question 1-300 символов, каждый option 1-100 символов, explanation 0-200 символов.
"""


def build_messages(raw: RawQuestion, previous_error: str | None) -> list[dict[str, str]]:
    payload = raw.model_dump()
    user_prompt = {
        "task": "Normalize this quiz item into clean Telegram quiz-poll fields.",
        "previous_error": previous_error or "",
        "input_item": payload,
        "output_rules": [
            "Return JSON only.",
            "Return exactly four options.",
            "Place correct_answer in options and set correct as a 1-based index.",
            "Do not use ellipsis.",
            "Keep explanation <= 200 characters.",
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
    ]


def build_response_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "normalized_quiz_question",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "correct_answer": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "correct": {"type": "integer"},
                "explanation": {"type": "string"},
                "explanation_full": {"type": "string"},
                "quality_flags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "question",
                "correct_answer",
                "options",
                "correct",
                "explanation",
                "explanation_full",
                "quality_flags",
            ],
            "additionalProperties": False,
        },
    }


def extract_json_object(output: Any) -> dict[str, Any]:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        parsed = json.loads(output)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("GPT output is not a JSON object")


def call_openai_normalizer(client: OpenAI, model: str, raw: RawQuestion, previous_error: str | None) -> GPTQuestion:
    response = client.responses.create(
        model=model,
        input=build_messages(raw, previous_error),
        text={"format": build_response_schema()},
    )
    parsed = extract_json_object(response.output_text)
    return GPTQuestion(**parsed)
```

- [ ] **Step 4: Run prompt/schema tests**

Run:

```bash
python -m pytest tests/test_gpt_normalizer.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add gpt_normalizer.py tests/test_gpt_normalizer.py
git commit -m "feat: add normalizer prompt and openai adapter"
```

---

## Task 6: Dataset Orchestration, Retry, And Review Output

**Files:**
- Modify: `tests/test_gpt_normalizer.py`
- Modify: `gpt_normalizer.py`

- [ ] **Step 1: Append orchestration tests**

Append to `tests/test_gpt_normalizer.py`:

```python
from normalizer_io import load_v2_dataset
from gpt_normalizer import normalize_dataset


def test_normalize_dataset_accepts_fake_clean_outputs():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    def fake_normalizer(raw, previous_error):
        if raw.id == 1:
            return {
                "question": "Какой указ ликвидировал ханскую власть в Среднем жузе?",
                "correct_answer": "Устав о сибирских киргизах 1822 года",
                "options": [
                    "Устав о сибирских киргизах 1822 года",
                    "Устав об оренбургских киргизах 1824 года",
                    "Степное положение 1891 года",
                    "Реформа 1867-1868 годов",
                ],
                "correct": 1,
                "explanation": "Устав 1822 года ввёл окружное управление и упразднил ханскую власть.",
                "explanation_full": raw.explanation_full,
                "quality_flags": [],
            }
        if raw.id == 2:
            return {
                "question": raw.question,
                "correct_answer": "Эмир Тимур",
                "options": ["Эмир Тимур", "Абылай хан", "Касым хан", "Тауке хан"],
                "correct": 1,
                "explanation": raw.explanation[:200],
                "explanation_full": raw.explanation_full,
                "quality_flags": [],
            }
        return {
            "question": raw.question,
            "correct_answer": "Сырым Датов",
            "options": ["Сырым Датов", "Абылай хан", "Касым хан", "Тауке хан"],
            "correct": 1,
            "explanation": raw.explanation[:200],
            "explanation_full": raw.explanation_full,
            "quality_flags": [],
        }

    clean, review = normalize_dataset(
        data,
        normalize_one=fake_normalizer,
        limit=2,
        start_id=None,
        max_retries=1,
        seed=42,
    )
    assert len(clean) == 2
    assert len(review) == 0
    assert clean[0].source_item_id == 1


def test_normalize_dataset_sends_bad_outputs_to_review():
    data = load_v2_dataset("tests/fixtures/questions_v2_sample.json")

    def bad_normalizer(raw, previous_error):
        return {
            "question": raw.question,
            "correct_answer": "Сырым Датов",
            "options": ["Сырым Датов", "Сырым Датов", "Касым хан", "Тауке хан"],
            "correct": 1,
            "explanation": raw.explanation[:200],
            "explanation_full": raw.explanation_full,
            "quality_flags": [],
        }

    clean, review = normalize_dataset(
        data,
        normalize_one=bad_normalizer,
        limit=1,
        start_id=None,
        max_retries=2,
        seed=42,
    )
    assert clean == []
    assert len(review) == 1
    assert review[0].source_item_id == 1
    assert review[0].error_reason in {"duplicate_options", "max_retries_exceeded"}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_gpt_normalizer.py -q
```

Expected: FAIL with `ImportError` for `normalize_dataset`.

- [ ] **Step 3: Add orchestration functions to `gpt_normalizer.py`**

Append below `call_openai_normalizer`:

```python
NormalizeOne = Callable[[RawQuestion, str | None], GPTQuestion | dict[str, Any]]


def shuffle_options(item: CleanQuestion, seed: int) -> CleanQuestion:
    rng = random.Random(f"{seed}:{item.source_item_id}")
    indexed = list(enumerate(item.options, start=1))
    rng.shuffle(indexed)
    old_correct = item.correct
    new_options = [option for _, option in indexed]
    new_correct = next(i for i, (old_index, _) in enumerate(indexed, start=1) if old_index == old_correct)
    data = item.model_dump()
    data["options"] = new_options
    data["correct"] = new_correct
    data["correct_answer"] = new_options[new_correct - 1]
    return CleanQuestion(**data)


def _as_gpt_question(output: GPTQuestion | dict[str, Any]) -> GPTQuestion:
    if isinstance(output, GPTQuestion):
        return output
    return GPTQuestion(**output)


def normalize_one_with_retries(
    raw: RawQuestion,
    *,
    normalize_one: NormalizeOne,
    max_retries: int,
    seed: int,
) -> tuple[CleanQuestion | None, ReviewQuestion | None]:
    previous_error: str | None = None
    last_output: dict[str, Any] | str | None = None

    for attempt in range(1, max_retries + 1):
        try:
            gpt = _as_gpt_question(normalize_one(raw, previous_error))
            last_output = gpt.model_dump()
            clean = build_clean_question(raw, gpt)
            if "needs_visual_review" in clean.quality_flags:
                return None, ReviewQuestion(
                    source_item_id=raw.id,
                    error_reason="needs_visual_review",
                    raw_item=raw.model_dump(),
                    last_gpt_output=last_output,
                    attempts=attempt,
                    notes="GPT marked this item as requiring visual review.",
                )
            clean = shuffle_options(clean, seed)
            validate_clean_question(clean)
            return clean, None
        except json.JSONDecodeError as exc:
            previous_error = "bad_json"
            last_output = str(exc)
        except LocalValidationError as exc:
            previous_error = exc.reason
            last_output = last_output or str(exc)
        except Exception as exc:
            previous_error = "gpt_request_failed"
            last_output = str(exc)

    return None, ReviewQuestion(
        source_item_id=raw.id,
        error_reason="max_retries_exceeded",
        raw_item=raw.model_dump(),
        last_gpt_output=last_output,
        attempts=max_retries,
        notes=f"Last error reason: {previous_error}",
    )


def iter_selected_raw_questions(
    data: dict[str, Any],
    *,
    limit: int | None,
    start_id: int | None,
) -> list[RawQuestion]:
    raws = [RawQuestion(**item) for item in data["questions"]]
    if start_id is not None:
        raws = [item for item in raws if item.id >= start_id]
    if limit is not None:
        raws = raws[:limit]
    return raws


def normalize_dataset(
    data: dict[str, Any],
    *,
    normalize_one: NormalizeOne,
    limit: int | None,
    start_id: int | None,
    max_retries: int,
    seed: int,
) -> tuple[list[CleanQuestion], list[ReviewQuestion]]:
    clean: list[CleanQuestion] = []
    review: list[ReviewQuestion] = []
    for raw in iter_selected_raw_questions(data, limit=limit, start_id=start_id):
        clean_item, review_item = normalize_one_with_retries(
            raw,
            normalize_one=normalize_one,
            max_retries=max_retries,
            seed=seed,
        )
        if clean_item is not None:
            clean.append(clean_item)
        if review_item is not None:
            review.append(review_item)
    return clean, review
```

- [ ] **Step 4: Run orchestration tests**

Run:

```bash
python -m pytest tests/test_gpt_normalizer.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add gpt_normalizer.py tests/test_gpt_normalizer.py
git commit -m "feat: add normalizer retry orchestration"
```

---

## Task 7: CLI Main And File Outputs

**Files:**
- Modify: `tests/test_gpt_normalizer.py`
- Modify: `gpt_normalizer.py`

- [ ] **Step 1: Add CLI argument tests**

Append to `tests/test_gpt_normalizer.py`:

```python
from gpt_normalizer import parse_args


def test_parse_args_defaults():
    args = parse_args([
        "--input", "questions_v2.json",
        "--output", "clean_questions.json",
        "--review", "review_questions.json",
        "--report", "normalizer_report.json",
        "--model", "gpt-4.1-mini",
    ])
    assert args.seed == 42
    assert args.max_retries == 3
    assert args.limit is None
    assert args.start_id is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/test_gpt_normalizer.py::test_parse_args_defaults -q
```

Expected: FAIL with `ImportError` for `parse_args`.

- [ ] **Step 3: Add CLI functions to `gpt_normalizer.py`**

Append:

```python
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize questions_v2.json with GPT.")
    parser.add_argument("--input", required=True, help="Path to questions_v2.json")
    parser.add_argument("--output", required=True, help="Path to clean_questions.json")
    parser.add_argument("--review", required=True, help="Path to review_questions.json")
    parser.add_argument("--report", required=True, help="Path to normalizer_report.json")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", ""), help="OpenAI model name")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N selected questions")
    parser.add_argument("--start-id", type=int, default=None, help="Start from source item id")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per item")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic option shuffle seed")
    parser.add_argument("--dry-run", action="store_true", help="Print report without writing output files")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    load_dotenv()
    if not args.model:
        print("ERROR: set --model or OPENAI_MODEL", file=sys.stderr)
        return 1
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: set OPENAI_API_KEY", file=sys.stderr)
        return 1

    started_at = utc_now_iso()
    source_data = load_v2_dataset(args.input)
    total = len(iter_selected_raw_questions(source_data, limit=args.limit, start_id=args.start_id))

    client = OpenAI()

    def api_normalizer(raw: RawQuestion, previous_error: str | None) -> GPTQuestion:
        return call_openai_normalizer(client, args.model, raw, previous_error)

    clean, review = normalize_dataset(
        source_data,
        normalize_one=api_normalizer,
        limit=args.limit,
        start_id=args.start_id,
        max_retries=args.max_retries,
        seed=args.seed,
    )

    report = build_report(
        input_path=args.input,
        output_path=args.output,
        review_path=args.review,
        model=args.model,
        max_retries=args.max_retries,
        total=total,
        clean=clean,
        review=review,
        started_at=started_at,
        finished_at=utc_now_iso(),
    )

    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    write_json_atomic(args.output, clean_payload(source_data, clean))
    write_json_atomic(args.review, review_payload(source_data, review))
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run CLI argument test**

Run:

```bash
python -m pytest tests/test_gpt_normalizer.py::test_parse_args_defaults -q
```

Expected: PASS.

- [ ] **Step 5: Run all normalizer tests**

Run:

```bash
python -m pytest tests/test_normalizer_models.py tests/test_normalizer_io.py tests/test_gpt_normalizer.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add gpt_normalizer.py tests/test_gpt_normalizer.py
git commit -m "feat: add gpt normalizer cli"
```

---

## Task 8: README Usage Notes

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a `GPT normalizer` section**

Append this section to `README.md`:

```markdown
## GPT normalizer

`gpt_normalizer.py` takes the extended v2 pipeline output and produces QuizBot-ready clean questions plus a manual-review file.

Input:

```text
questions_v2.json
```

Outputs:

```text
clean_questions.json
review_questions.json
normalizer_report.json
```

Environment:

```env
OPENAI_API_KEY=replace_me
OPENAI_MODEL=gpt-4.1-mini
```

Smoke run:

```bash
python gpt_normalizer.py --input questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json --limit 5
```

Full run:

```bash
python gpt_normalizer.py --input questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json
```

The normalizer does not upload anything to Telegram. Review `review_questions.json` before using the clean output for upload.
```

- [ ] **Step 2: Run tests after README change**

Run:

```bash
python -m pytest tests/test_normalizer_models.py tests/test_normalizer_io.py tests/test_gpt_normalizer.py -q
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add gpt normalizer usage"
```

---

## Task 9: Manual Smoke Procedure

**Files:**
- No source changes required.

- [ ] **Step 1: Extract v2 archive to a temporary local directory**

Run:

```powershell
New-Item -ItemType Directory -Force -Path .normalizer_tmp
Expand-Archive -LiteralPath quizbot_pipeline_v2.zip -DestinationPath .normalizer_tmp -Force
Copy-Item -LiteralPath .normalizer_tmp\quizbot_pipeline_v2\questions_v2.json -Destination questions_v2.json -Force
```

Expected: `questions_v2.json` exists in the project root and is ignored by git.

- [ ] **Step 2: Run 5-question GPT smoke test**

Run:

```bash
python gpt_normalizer.py --input questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json --limit 5
```

Expected:

```text
"items_total": 5
```

The command may require `OPENAI_API_KEY` and network access.

- [ ] **Step 3: Inspect output shape**

Run:

```bash
python -c "import json; d=json.load(open('clean_questions.json', encoding='utf-8')); print(len(d['questions'])); print(d['questions'][0]['source_item_id']); print(d['questions'][0]['options'])"
```

Expected: prints a clean question count, a numeric `source_item_id`, and four options.

- [ ] **Step 4: Inspect review reasons**

Run:

```bash
python -c "import json; d=json.load(open('review_questions.json', encoding='utf-8')); print([q['error_reason'] for q in d['questions']])"
```

Expected: prints `[]` or a list of allowed `error_reason` values.

- [ ] **Step 5: Verify git does not show generated files**

Run:

```bash
git status --short
```

Expected: source files may be modified during implementation, but generated `questions_v2.json`, `clean_questions.json`, `review_questions.json`, `normalizer_report.json`, `.normalizer_tmp/`, and `quizbot_pipeline_v2/` do not appear.

- [ ] **Step 6: Commit final implementation state**

```bash
git status --short
git log --oneline -5
```

Expected: implementation commits from Tasks 1-8 are present. No generated data files are staged.

---

## Self-Review Checklist

- Spec coverage:
  - `source_item_id`: covered in `CleanQuestion`, `ReviewQuestion`, tests, and output formats.
  - `error_reason`: covered by `ReviewQuestion`, allowed reasons, retry behavior, and tests.
  - Local limits: covered by `validate_clean_question`.
  - GPT strict JSON: covered by `build_response_schema` and prompt tests.
  - Retry/review/report: covered by `normalize_one_with_retries`, `normalize_dataset`, and report tests.
  - Media as metadata: covered by raw and clean models.
- Placeholder scan: no open-ended markers or unresolved task references.
- Type consistency:
  - Raw input model: `RawQuestion`.
  - GPT output model: `GPTQuestion`.
  - Clean output model: `CleanQuestion`.
  - Review output model: `ReviewQuestion`.
