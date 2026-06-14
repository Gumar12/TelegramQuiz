"""Prompt, structured output schema, and OpenAI adapter for quiz normalization."""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from backend import config
from backend.normalizer_io import (
    build_report,
    clean_payload,
    load_existing_results,
    load_v2_dataset,
    merge_clean,
    merge_review,
    resume_state,
    review_payload,
    write_json_atomic,
)
from backend.normalizer_models import (
    CleanQuestion,
    GPTQuestion,
    LocalValidationError,
    RawQuestion,
    ReviewQuestion,
    build_clean_question,
    normalize_key,
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
- Если вопрос зависит от изображения и изображение приложено, используй изображение вместе с текстовым контекстом.
- Добавляй quality_flags ["needs_visual_review"] только если приложенного изображения и текста недостаточно или изображение нельзя уверенно интерпретировать.
- Ограничения длины: question 1-300, option 1-100, explanation 0-200.
"""


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _ffprobe_for(ffmpeg_path: str) -> str:
    path = Path(ffmpeg_path)
    if path.name.lower().startswith("ffmpeg"):
        suffix = path.suffix
        return str(path.with_name(f"ffprobe{suffix}"))
    return "ffprobe"


def _probe_image_size(path: Path, ffprobe_path: str, timeout: int = 20) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    try:
        payload = json.loads(result.stdout.decode("utf-8"))
        stream = payload["streams"][0]
        return int(stream["width"]), int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _data_url_from_bytes(data: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _mime_type_for(path: Path) -> str:
    guessed = mimetypes.guess_type(str(path))[0]
    if guessed in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        return guessed
    return "image/jpeg"


def prepare_image_data_url(
    image_path: str | Path,
    *,
    ffmpeg_path: str = "ffmpeg",
    max_side: int = 1024,
    jpeg_quality: int = 3,
) -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    size = _probe_image_size(path, _ffprobe_for(ffmpeg_path), timeout=20)
    should_resize = bool(size and max(size) > max_side)
    if not should_resize:
        return _data_url_from_bytes(path.read_bytes(), _mime_type_for(path))

    with tempfile.TemporaryDirectory(prefix="quizbot_media_") as tmpdir:
        output_path = Path(tmpdir) / "image.jpg"
        try:
            subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-vf",
                    f"scale={max_side}:{max_side}:force_original_aspect_ratio=decrease",
                    "-frames:v",
                    "1",
                    "-q:v",
                    str(jpeg_quality),
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return _data_url_from_bytes(path.read_bytes(), _mime_type_for(path))
        return _data_url_from_bytes(output_path.read_bytes(), "image/jpeg")


def prepare_media_inputs(
    raw: RawQuestion,
    *,
    image_detail: str = "auto",
    ffmpeg_path: str = "ffmpeg",
    max_side: int = 1024,
    jpeg_quality: int = 3,
    media_root: str | Path | None = None,
) -> list[dict[str, str]]:
    media_inputs: list[dict[str, str]] = []
    for media in raw.media:
        try:
            if _is_http_url(media):
                image_url = media
            else:
                resolved_media = resolve_media_path(media, media_root=media_root)
                if resolved_media is None:
                    continue
                image_url = prepare_image_data_url(
                    resolved_media,
                    ffmpeg_path=ffmpeg_path,
                    max_side=max_side,
                    jpeg_quality=jpeg_quality,
                )
        except OSError:
            continue
        media_inputs.append(
            {
                "type": "input_image",
                "image_url": image_url,
                "detail": image_detail,
            }
        )
    return media_inputs


def resolve_media_path(media: str | Path, media_root: str | Path | None = None) -> Path | None:
    path = Path(media)
    if path.exists():
        return path

    if media_root is None:
        return None

    root = Path(media_root)
    filename = path.name
    candidates = [
        root / filename,
        root / "media" / filename,
    ]
    media_text = str(media).replace("\\", "/")
    if "/media/" in media_text:
        candidates.append(root / media_text.rsplit("/media/", 1)[1])

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _repair_instructions(previous_error: str | None) -> list[str]:
    if previous_error == "weak_distractors":
        return [
            "Предыдущая попытка провалилась из-за weak_distractors.",
            "не используй исходные варианты ответа, кроме правильного ответа.",
            "сгенерируй три новых правдоподобных, но неправильных варианта без многоточий.",
            "Все четыре варианта должны быть одного типа и не должны содержать обрезанный текст.",
        ]
    if previous_error:
        return [f"Исправь ошибку предыдущей попытки: {previous_error}."]
    return []


def _has_heuristic_distractors(raw: RawQuestion) -> bool:
    return raw.distractors_source == "heuristic_same_document"


TRUSTED_SOURCE_DISTRACTORS = {
    "source_document_bold",
    "source_document_answer_indexes",
}


def _valid_correct_indexes(correct: int | list[int] | None, option_count: int) -> list[int]:
    if correct is None:
        return []
    indexes = correct if isinstance(correct, list) else [correct]
    if not indexes or len(set(indexes)) != len(indexes):
        return []
    if any(not (1 <= index <= option_count) for index in indexes):
        return []
    return indexes


def style_example_from_raw(raw: RawQuestion) -> dict[str, Any] | None:
    if raw.distractors_source not in TRUSTED_SOURCE_DISTRACTORS:
        return None
    if len(raw.options) != 4:
        return None
    if not isinstance(raw.correct, int):
        return None
    if not _valid_correct_indexes(raw.correct, len(raw.options)):
        return None
    return {
        "source_item_id": raw.id,
        "date": raw.date,
        "section": raw.section,
        "question": raw.question,
        "correct_answer": raw.correct_answer,
        "options": list(raw.options),
        "correct": raw.correct,
    }


def build_style_examples(data: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    examples: list[dict[str, Any]] = []
    for item in data.get("questions", []):
        try:
            raw = item if isinstance(item, RawQuestion) else RawQuestion(**item)
        except (TypeError, ValidationError):
            continue
        example = style_example_from_raw(raw)
        if example is None:
            continue
        examples.append(example)
        if len(examples) >= limit:
            break
    return examples


def _build_source_document_question(raw: RawQuestion) -> CleanQuestion | None:
    if raw.distractors_source not in TRUSTED_SOURCE_DISTRACTORS:
        return None
    if raw.correct is None or len(raw.options) != 4:
        return None
    correct_indexes = _valid_correct_indexes(raw.correct, len(raw.options))
    if not correct_indexes:
        return None

    correct_answers = [raw.options[index - 1] for index in correct_indexes]
    correct_answer = correct_answers[0] if len(correct_answers) == 1 else "; ".join(correct_answers)

    if raw.correct_answer and raw.correct_answer != correct_answer:
        return None
    if raw.correct_answers and raw.correct_answers != correct_answers:
        return None

    return CleanQuestion(
        source_item_id=raw.id,
        date=raw.date,
        section=raw.section,
        context_title=raw.context_title,
        context=raw.context,
        media=list(raw.media),
        question=raw.question,
        correct_answer=correct_answer,
        correct_answers=correct_answers,
        options=list(raw.options),
        correct=raw.correct,
        explanation=raw.explanation,
        explanation_full=raw.explanation_full,
        type=raw.type,
        source=raw.distractors_source,
        quality_flags=[],
    )


def validate_against_raw_options(raw: RawQuestion, item: CleanQuestion) -> None:
    if not _has_heuristic_distractors(raw):
        return

    raw_correct_answers = raw.correct_answers or ([raw.correct_answer] if raw.correct_answer else [])
    correct_keys = {normalize_key(answer) for answer in raw_correct_answers}
    heuristic_wrong_options = {
        normalize_key(option)
        for option in raw.options
        if normalize_key(option) not in correct_keys
    }
    for option in item.options:
        option_key = normalize_key(option)
        if option_key in {normalize_key(answer) for answer in item.correct_answers or [item.correct_answer]}:
            continue
        if option_key in heuristic_wrong_options:
            raise LocalValidationError(
                "weak_distractors",
                f"reused heuristic source option: {option!r}",
            )


def build_messages(
    raw: RawQuestion,
    previous_error: str | None = None,
    media_inputs: list[dict[str, str]] | None = None,
    style_examples: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    media_inputs = media_inputs or []
    style_examples = style_examples or []
    user_payload = {
        "task": "Normalize this raw quiz item into the required JSON object.",
        "previous_error": previous_error,
        "repair_instructions": _repair_instructions(previous_error),
        "media_attached": bool(media_inputs),
        "style_examples": style_examples,
        "input_item": raw.model_dump(),
        "output_rules": [
            "Return one JSON object only.",
            "Use exactly four options.",
            "correct is a 1-based index into options.",
            "correct_answer must exactly match options[correct - 1].",
            "style_examples are examples of option style only; do not copy their facts unless they belong to the input_item.",
            "Generate wrong options with the same semantic type as the correct answer: person/person, date/date, place/place, event/event, term/term.",
            "Keep wrong options close to the correct answer in length, grammar form, and specificity.",
            "Не добавляй факты вне исходного элемента.",
            "Не используй многоточия и обрезанные варианты.",
            "Если input_item.distractors_source='heuristic_same_document', исходные options недоверенные: оставь только correct_answer, а три неправильных варианта сгенерируй заново.",
            "Если media_attached=true, используй приложенные input_image для вопросов по картинке.",
            "Если correct_answer пустой, но ответ есть в context/media, выведи его только из этого context/media.",
            "Если ответ нельзя определить из input_item context/media, верни quality_flags [\"needs_visual_review\"].",
        ],
    }
    user_content: list[dict[str, str]] = [
        {"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}
    ]
    user_content.extend(media_inputs)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
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
    image_detail: str = "auto",
    ffmpeg_path: str = "ffmpeg",
    max_side: int = 1024,
    jpeg_quality: int = 3,
    media_root: str | Path | None = None,
    style_examples: list[dict[str, Any]] | None = None,
) -> GPTQuestion:
    media_inputs = prepare_media_inputs(
        raw,
        image_detail=image_detail,
        ffmpeg_path=ffmpeg_path,
        max_side=max_side,
        jpeg_quality=jpeg_quality,
        media_root=media_root,
    )
    if raw.media and not media_inputs:
        raise LocalValidationError(
            "needs_visual_review",
            "declared media could not be prepared",
        )
    response = client.responses.create(
        model=model,
        input=build_messages(
            raw,
            previous_error,
            media_inputs=media_inputs,
            style_examples=style_examples,
        ),
        text={"format": build_response_schema()},
    )
    parsed = extract_json_object(response.output_text)
    return GPTQuestion(**parsed)


NormalizeOne = Callable[[RawQuestion, str | None], GPTQuestion | dict[str, Any]]
CancelCheck = Callable[[], None]


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None:
        cancel_check()


def shuffle_options(item: CleanQuestion, seed: int) -> CleanQuestion:
    options = list(item.options)
    correct_indexes = item.correct if isinstance(item.correct, list) else [item.correct]
    correct_answers = [item.options[index - 1] for index in correct_indexes]
    random.Random(f"{seed}:{item.source_item_id}").shuffle(options)
    indexed_answers = sorted(
        (options.index(correct_answer) + 1, correct_answer)
        for correct_answer in correct_answers
    )
    new_correct_indexes = [index for index, _ in indexed_answers]
    new_correct_answers = [answer for _, answer in indexed_answers]
    correct: int | list[int] = (
        new_correct_indexes[0] if len(new_correct_indexes) == 1 else new_correct_indexes
    )
    correct_answer = (
        new_correct_answers[0] if len(new_correct_answers) == 1 else "; ".join(new_correct_answers)
    )
    return item.model_copy(
        update={
            "options": options,
            "correct": correct,
            "correct_answer": correct_answer,
            "correct_answers": new_correct_answers,
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
    cancel_check: CancelCheck | None = None,
) -> CleanQuestion | ReviewQuestion:
    _check_cancel(cancel_check)
    source_document_question = _build_source_document_question(raw)
    if source_document_question is not None:
        try:
            validate_clean_question(source_document_question, check_distractor_quality=False)
            source_document_question = shuffle_options(source_document_question, seed)
            validate_clean_question(source_document_question, check_distractor_quality=False)
            return source_document_question
        except LocalValidationError:
            pass

    if not raw.correct_answer and not raw.correct_answers and not (raw.context or raw.media):
        return _review_question(
            raw,
            "missing_required_field",
            None,
            0,
            "Raw item has no usable correct answer",
        )

    attempts_allowed = max(1, max_retries)
    previous_error: str | None = None
    last_gpt_output: GPTQuestion | dict[str, Any] | None = None
    last_note = ""

    for attempt in range(1, attempts_allowed + 1):
        _check_cancel(cancel_check)
        try:
            last_gpt_output = normalize_one(raw, previous_error)
            _check_cancel(cancel_check)
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
            validate_against_raw_options(raw, clean)
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
            if exc.reason == "needs_visual_review":
                return _review_question(
                    raw,
                    "needs_visual_review",
                    last_gpt_output,
                    attempt,
                    last_note,
                )
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
    cancel_check: CancelCheck | None = None,
    skip_ids: set[int] | None = None,
) -> tuple[list[CleanQuestion], list[ReviewQuestion]]:
    skip_ids = skip_ids or set()
    clean: list[CleanQuestion] = []
    review: list[ReviewQuestion] = []
    for raw in iter_selected_raw_questions(data, limit, start_id):
        if raw.id in skip_ids:
            continue
        _check_cancel(cancel_check)
        result = normalize_one_with_retries(raw, normalize_one, max_retries, seed, cancel_check=cancel_check)
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
    parser.add_argument("--image-detail", choices=["low", "auto", "high"], default="high", help="OpenAI image detail level")
    parser.add_argument("--ffmpeg-path", default="ffmpeg", help="Path to ffmpeg executable for image preparation")
    parser.add_argument("--media-max-side", type=_positive_int, default=1024, help="Resize image longest side above this before sending")
    parser.add_argument("--media-jpeg-quality", type=_positive_int, default=3, help="ffmpeg JPEG q:v value for resized images")
    parser.add_argument("--media-root", default=None, help="Directory used to resolve stale or relative media paths by filename")
    parser.add_argument("--style-source", default=None, help="Optional full v2 JSON used to extract trusted document quiz examples")
    parser.add_argument("--style-examples", type=_non_negative_int, default=5, help="Number of trusted document examples to include in each GPT prompt")
    parser.add_argument("--dry-run", action="store_true", help="Print report without writing output files")
    return parser.parse_args(argv)


def run(args: argparse.Namespace, cancel_check: CancelCheck | None = None) -> int:
    load_dotenv()
    _check_cancel(cancel_check)
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

    _check_cancel(cancel_check)
    source_data = load_v2_dataset(args.input)
    style_source_data = load_v2_dataset(args.style_source) if args.style_source else source_data
    style_examples = build_style_examples(style_source_data, limit=args.style_examples)
    total = len(iter_selected_raw_questions(source_data, args.limit, args.start_id))
    _check_cancel(cancel_check)
    client = OpenAI()

    def api_normalizer(raw: RawQuestion, previous_error: str | None = None) -> GPTQuestion:
        return call_openai_normalizer(
            client,
            args.model,
            raw,
            previous_error,
            image_detail=args.image_detail,
            ffmpeg_path=args.ffmpeg_path,
            max_side=args.media_max_side,
            jpeg_quality=args.media_jpeg_quality,
            media_root=args.media_root,
            style_examples=style_examples,
        )

    # Resume support: pick up an earlier run that stopped (e.g. on an API outage)
    # by skipping already-finished items and merging into the existing output.
    existing_clean: list[CleanQuestion] = []
    done_ids: set[int] = set()
    carry_review: list[ReviewQuestion] = []
    if not args.dry_run:
        existing_clean, existing_review = load_existing_results(args.output, args.review)
        done_ids, carry_review = resume_state(existing_clean, existing_review)
        if done_ids:
            print(f"Resuming: {len(done_ids)} item(s) already done, skipping them", file=sys.stderr)

    clean, review = normalize_dataset(
        source_data,
        normalize_one=api_normalizer,
        limit=args.limit,
        start_id=args.start_id,
        max_retries=args.max_retries,
        seed=args.seed,
        cancel_check=cancel_check,
        skip_ids=done_ids,
    )
    merged_clean = merge_clean(existing_clean, clean)
    merged_review = merge_review(carry_review, review)
    report = build_report(
        input_path=args.input,
        output_path=args.output,
        review_path=args.review,
        model=args.model,
        max_retries=args.max_retries,
        total=total,
        clean=merged_clean,
        review=merged_review,
    )

    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if any(item.error_reason == "gpt_request_failed" for item in review) else 0

    write_json_atomic(args.output, clean_payload(source_data, merged_clean))
    write_json_atomic(args.review, review_payload(source_data, merged_review))
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(item.error_reason == "gpt_request_failed" for item in merged_review) else 0


def main() -> None:
    raise SystemExit(run(parse_args()))


__all__ = [
    "NormalizeOne",
    "SYSTEM_PROMPT",
    "build_messages",
    "build_response_schema",
    "build_style_examples",
    "extract_json_object",
    "call_openai_normalizer",
    "prepare_image_data_url",
    "prepare_media_inputs",
    "resolve_media_path",
    "validate_against_raw_options",
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
