"""Prompt, structured output schema, and OpenAI adapter for quiz normalization."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path
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
    raise ValueError("GPT output is not a JSON object")


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
        except ValueError as exc:
            previous_error = "bad_json"
            last_note = str(exc)
        except OpenAIError as exc:
            previous_error = "gpt_request_failed"
            last_note = str(exc)

    return _review_question(
        raw,
        previous_error if previous_error in {"bad_json", "gpt_request_failed"} else "max_retries_exceeded",
        last_gpt_output,
        attempts_allowed,
        f"Last error: {previous_error}. {last_note}",
    )


def iter_selected_raw_questions(
    data: dict[str, Any],
    limit: int | None,
    start_id: int | None,
) -> list[RawQuestion]:
    selected: list[RawQuestion | dict[str, Any]] = []
    for item in data.get("questions", []):
        item_id = item.id if isinstance(item, RawQuestion) else item.get("id")
        if start_id is not None and (item_id is None or item_id < start_id):
            continue
        selected.append(item)
        if limit is not None and len(selected) >= limit:
            break
    return [item if isinstance(item, RawQuestion) else RawQuestion(**item) for item in selected]


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
            if result.error_reason == "gpt_request_failed":
                break
        else:
            clean.append(result)
    return clean, review


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _normalized_path(path: str) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _path_collision_error(args: argparse.Namespace) -> str | None:
    paths = {
        "input": args.input,
        "output": args.output,
        "review": args.review,
        "report": args.report,
    }
    seen: dict[str, str] = {}
    for name, path in paths.items():
        normalized = _normalized_path(path)
        if normalized in seen:
            return f"ERROR: --{name} path collides with --{seen[normalized]} path"
        seen[normalized] = name
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize v2 quiz questions with GPT.")
    parser.add_argument("--input", required=True, help="Path to source questions_v2 JSON")
    parser.add_argument("--output", required=True, help="Path to write clean questions JSON")
    parser.add_argument("--review", required=True, help="Path to write review questions JSON")
    parser.add_argument("--report", required=True, help="Path to write normalizer report JSON")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", ""), help="OpenAI model name")
    parser.add_argument("--limit", type=_non_negative_int, default=None, help="Maximum number of questions to normalize")
    parser.add_argument("--start-id", type=int, default=None, help="First source item id to include")
    parser.add_argument("--max-retries", type=_positive_int, default=3, help="Maximum GPT attempts per question")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic option shuffle seed")
    parser.add_argument("--dry-run", action="store_true", help="Print report without writing output files")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    load_dotenv()
    args.model = args.model or os.getenv("OPENAI_MODEL", "")
    if not args.model:
        print("ERROR: --model is required or OPENAI_MODEL must be set", file=sys.stderr)
        return 1
    collision_error = _path_collision_error(args)
    if collision_error:
        print(collision_error, file=sys.stderr)
        return 1
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY must be set", file=sys.stderr)
        return 1

    source_data = load_v2_dataset(args.input)
    total = len(iter_selected_raw_questions(source_data, args.limit, args.start_id))
    client = OpenAI()

    def api_normalizer(raw: RawQuestion, previous_error: str | None = None) -> GPTQuestion:
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
    )

    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if any(item.error_reason == "gpt_request_failed" for item in review) else 0

    write_json_atomic(args.output, clean_payload(source_data, clean))
    write_json_atomic(args.review, review_payload(source_data, review))
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(item.error_reason == "gpt_request_failed" for item in review) else 0


def main() -> None:
    raise SystemExit(run(parse_args()))


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
    "_non_negative_int",
    "_positive_int",
    "_path_collision_error",
    "parse_args",
    "run",
    "main",
]


if __name__ == "__main__":
    main()
