"""Prompt, structured output schema, and OpenAI adapter for quiz normalization."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from normalizer_io import (
    build_report,
    clean_payload,
    load_v2_dataset,
    review_payload,
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


SYSTEM_PROMPT = """Ты нормализуешь вопросы викторины по истории Казахстана.

Верни только валидный JSON по заданной схеме.

Правила:
- Не добавляй факты вне исходного элемента.
- Не делай частично правильные дистракторы.
- Не используй варианты "все ответы верны" или "нет правильного ответа".
- Не используй многоточие.
- Сохраняй историческую точность в пределах контекста исходного элемента.
- Делай варианты ответа похожими по типу и длине.
- Если вопрос зависит от изображения, а текста недостаточно, добавь quality_flags ["needs_visual_review"].
- Ограничения длины: question 1-300, option 1-100, explanation 0-200.
"""


def build_messages(raw: RawQuestion, previous_error: str | None = None) -> list[dict[str, str]]:
    user_payload = {
        "task": "Normalize this raw quiz item into the required JSON object.",
        "previous_error": previous_error,
        "input_item": raw.model_dump(),
        "output_rules": [
            "Return one JSON object only.",
            "Use exactly four options.",
            "correct is a 1-based index into options.",
            "correct_answer must exactly match options[correct - 1].",
            "Не добавляй факты вне исходного элемента.",
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def build_response_schema() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "normalized_quiz_question",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "question",
                "correct_answer",
                "options",
                "correct",
                "explanation",
                "explanation_full",
                "quality_flags",
            ],
            "properties": {
                "question": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 300,
                },
                "correct_answer": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                },
                "options": {
                    "type": "array",
                    "minItems": 4,
                    "maxItems": 4,
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 100,
                    },
                },
                "correct": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 4,
                },
                "explanation": {
                    "type": "string",
                    "maxLength": 200,
                },
                "explanation_full": {
                    "type": "string",
                },
                "quality_flags": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["needs_visual_review"],
                    },
                },
            },
        },
    }


def extract_json_object(output: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        parsed = json.loads(output)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Expected a JSON object or JSON object string")


def call_openai_normalizer(
    client: OpenAI,
    model: str,
    raw: RawQuestion,
    previous_error: str | None = None,
) -> GPTQuestion:
    response = client.responses.create(
        model=model,
        input=build_messages(raw, previous_error),
        text={"format": build_response_schema()},
    )
    parsed = extract_json_object(response.output_text)
    return GPTQuestion(**parsed)


NormalizeOne = Callable[[RawQuestion, str | None], GPTQuestion | dict[str, Any]]


def shuffle_options(item: CleanQuestion, seed: int) -> CleanQuestion:
    options = list(item.options)
    correct_answer = item.options[item.correct - 1]
    random.Random(f"{seed}:{item.source_item_id}").shuffle(options)
    correct = options.index(correct_answer) + 1
    return item.model_copy(
        update={
            "options": options,
            "correct": correct,
            "correct_answer": options[correct - 1],
        }
    )


def _as_gpt_question(output: GPTQuestion | dict[str, Any]) -> GPTQuestion:
    if isinstance(output, GPTQuestion):
        return output
    if isinstance(output, dict):
        return GPTQuestion(**output)
    raise ValueError("Expected GPTQuestion or dict output")


def _review_question(
    raw: RawQuestion,
    error_reason: str,
    last_gpt_output: GPTQuestion | dict[str, Any] | None,
    attempts: int,
    notes: str,
) -> ReviewQuestion:
    if isinstance(last_gpt_output, GPTQuestion):
        serialized_output: dict[str, Any] | str | None = last_gpt_output.model_dump()
    else:
        serialized_output = last_gpt_output
    return ReviewQuestion(
        source_item_id=raw.id,
        error_reason=error_reason,
        raw_item=raw.model_dump(),
        last_gpt_output=serialized_output,
        attempts=attempts,
        notes=notes,
    )


def normalize_one_with_retries(
    raw: RawQuestion,
    normalize_one: NormalizeOne,
    max_retries: int,
    seed: int,
) -> CleanQuestion | ReviewQuestion:
    attempts_allowed = max(1, max_retries)
    previous_error: str | None = None
    last_gpt_output: GPTQuestion | dict[str, Any] | None = None
    last_note = ""

    for attempt in range(1, attempts_allowed + 1):
        try:
            last_gpt_output = normalize_one(raw, previous_error)
            gpt = _as_gpt_question(last_gpt_output)
            clean = build_clean_question(raw, gpt)
            if "needs_visual_review" in clean.quality_flags:
                return _review_question(
                    raw,
                    "needs_visual_review",
                    last_gpt_output,
                    attempt,
                    "GPT output requested visual review",
                )
            validate_clean_question(clean)
            clean = shuffle_options(clean, seed)
            validate_clean_question(clean)
            return clean
        except json.JSONDecodeError as exc:
            previous_error = "bad_json"
            last_note = str(exc)
        except ValidationError as exc:
            previous_error = "missing_required_field"
            last_note = str(exc)
        except LocalValidationError as exc:
            previous_error = exc.reason
            last_note = str(exc)
        except OpenAIError as exc:
            previous_error = "gpt_request_failed"
            last_note = str(exc)

    return _review_question(
        raw,
        "max_retries_exceeded",
        last_gpt_output,
        attempts_allowed,
        f"Last error: {previous_error}. {last_note}",
    )


def iter_selected_raw_questions(
    data: dict[str, Any],
    limit: int | None,
    start_id: int | None,
) -> list[RawQuestion]:
    questions = [item if isinstance(item, RawQuestion) else RawQuestion(**item) for item in data.get("questions", [])]
    if start_id is not None:
        questions = [item for item in questions if item.id >= start_id]
    if limit is not None:
        questions = questions[:limit]
    return questions


def normalize_dataset(
    data: dict[str, Any],
    normalize_one: NormalizeOne,
    limit: int | None,
    start_id: int | None,
    max_retries: int,
    seed: int,
) -> tuple[list[CleanQuestion], list[ReviewQuestion]]:
    clean: list[CleanQuestion] = []
    review: list[ReviewQuestion] = []
    for raw in iter_selected_raw_questions(data, limit, start_id):
        result = normalize_one_with_retries(raw, normalize_one, max_retries, seed)
        if isinstance(result, ReviewQuestion):
            review.append(result)
        else:
            clean.append(result)
    return clean, review


__all__ = [
    "NormalizeOne",
    "SYSTEM_PROMPT",
    "build_messages",
    "build_response_schema",
    "extract_json_object",
    "call_openai_normalizer",
    "shuffle_options",
    "_as_gpt_question",
    "normalize_one_with_retries",
    "iter_selected_raw_questions",
    "normalize_dataset",
]
