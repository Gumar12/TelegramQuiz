"""Prompt, structured output schema, and OpenAI adapter for quiz normalization."""
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


__all__ = [
    "SYSTEM_PROMPT",
    "build_messages",
    "build_response_schema",
    "extract_json_object",
    "call_openai_normalizer",
]
