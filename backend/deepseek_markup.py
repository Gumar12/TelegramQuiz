"""DeepSeek-backed DOCX structure markup for QuizBot Studio."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from backend.parsers.docx_reader import read_docx_to_ir
from backend.pipeline.document_ir import DocumentBlock


SYSTEM_PROMPT = """Ты разметчик структуры DOCX для QuizBot.

Тебе дан markdown-поток, извлечённый из DOCX. В нём есть блоки:
[BLOCK p-0001 | paragraph | bold=false]
[BLOCK p-0002 | option | label=A | bold=true]
[IMAGE img-0001 | after=p-0064 | filename=image_001.jpg]

Твоя задача — только определить структуру документа.
Не создавай квиз, не переписывай текст, не сокращай текст, не исправляй ошибки.
Верни только связи между исходными block_id/image_id.

Жёсткие правила:
1. Используй только block_id и image_id из входного текста.
2. Не возвращай текст вопросов, вариантов, контекста или объяснений.
3. Не добавляй новые вопросы, варианты, ответы или контекст.
4. Не меняй правильный ответ.
5. Если правильный ответ выделен bold=true, используй этот option как правильный.
6. Если уверенности мало, не угадывай: добавь warning и confidence ниже 0.75.
7. Верни только валидный JSON. Никакого текста вне JSON.

Как определять вопрос:
- paragraph перед вариантами A/B/C/D обычно является вопросом.
- Если перед вариантами есть строки 1./2./3. или I./II./III., это часть текста вопроса.
- Вопрос может состоять из нескольких paragraph/list_item блоков.
- Варианты ответа идут в option_block_ids.

Как определять контекст:
- Контекст — источник, цитата, длинный исторический текст, фрагмент документа, биография или описание, после которого идут вопросы по этому источнику.
- Контекст может относиться к одному вопросу или к нескольким вопросам подряд.
- Контекст продолжается для следующих вопросов, пока не встретится новый контекст, заголовок, явный переход к другой теме или вопрос, который не зависит от предыдущего источника.
- Не помещай контекст в explanation.

Как определять изображения:
- IMAGE перед вопросом относится к следующему вопросу.
- IMAGE внутри или сразу после контекста относится к context и вопросам этого context.
- IMAGE между вопросом и вариантами относится к этому вопросу.
- Если не уверен, добавь warning.

Формат ответа:
{
  "document_id": "string",
  "questions": [
    {
      "id": "q001",
      "question_block_ids": ["p-0001"],
      "option_block_ids": ["p-0002", "p-0003", "p-0004", "p-0005"],
      "correct_option_block_ids": ["p-0002"],
      "context_block_ids": [],
      "media_ids": [],
      "confidence": 0.95,
      "warnings": []
    }
  ],
  "context_regions": [
    {
      "id": "ctx001",
      "block_ids": ["p-0100", "p-0101"],
      "applies_to_question_ids": ["q020", "q021"],
      "media_ids": [],
      "confidence": 0.9,
      "warnings": []
    }
  ],
  "ignored_block_ids": [],
  "global_warnings": []
}
"""

OPTION_RE = re.compile(r"^\s*([A-ZА-Я])[\).]\s+(.+)$", re.I)


class DeepSeekMarkupError(RuntimeError):
    """Raised when DeepSeek markup cannot be requested or parsed."""


def blocks_markdown_from_docx(docx_path: str | Path, *, media_dir: str | Path) -> str:
    """Return the block markdown sent to DeepSeek and write DOCX media to ``media_dir``."""

    source_path = Path(docx_path)
    ir = read_docx_to_ir(source_path, media_dir=media_dir)
    lines = [
        "# DOCX_BLOCK_STREAM",
        f"document_id: {ir.source_id}",
        f"source_path: {source_path.as_posix()}",
        "",
    ]
    previous_block_id = ""
    for block in ir.blocks:
        if block.kind == "break":
            continue
        if block.kind == "image":
            filename = Path(block.media_refs[0]).name if block.media_refs else ""
            meta = ["image"]
            if previous_block_id:
                meta.append(f"after={previous_block_id}")
            if filename:
                meta.append(f"filename={filename}")
            lines.extend([f"[IMAGE {block.block_id} | {' | '.join(meta)}]", ""])
            previous_block_id = block.block_id
            continue

        text = block.text.strip()
        if not text:
            continue
        block_kind = _block_kind(block)
        meta = [
            block_kind,
            f"bold={str(_has_bold(block)).lower()}",
            f"blank_before={block.blank_before}",
        ]
        if block.page_break_before:
            meta.append("page_break_before=true")
        if block.section_break_before:
            meta.append("section_break_before=true")
        option_label = _option_label(text)
        if option_label:
            meta.append(f"label={option_label}")
        if block.style:
            meta.append(f"style={_clean_meta_value(block.style)}")
        lines.extend([f"[BLOCK {block.block_id} | {' | '.join(meta)}]", text, ""])
        previous_block_id = block.block_id

    return "\n".join(lines).rstrip() + "\n"


def request_markup(
    blocks_md: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
    timeout_seconds: float,
    max_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ask DeepSeek to return JSON block markup for a DOCX block stream."""

    if not api_key.strip():
        raise DeepSeekMarkupError("DEEPSEEK_API_KEY is not set")
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Разметь следующий документ. Верни только JSON по заданной схеме.\n\n"
                    "```md\n"
                    f"{blocks_md}\n"
                    "```"
                ),
            },
        ],
        "temperature": 0,
        "stream": False,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    try:
        raw = _post_chat_completion(
            payload,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        if exc.code != 400:
            raise DeepSeekMarkupError(f"DeepSeek HTTP {exc.code}: {error_body}") from exc
        payload.pop("response_format", None)
        try:
            raw = _post_chat_completion(
                payload,
                api_key=api_key,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
        except urllib.error.HTTPError as retry_exc:
            retry_body = retry_exc.read().decode("utf-8", errors="replace")
            raise DeepSeekMarkupError(f"DeepSeek HTTP {retry_exc.code}: {retry_body}") from retry_exc
        except urllib.error.URLError as retry_exc:
            raise DeepSeekMarkupError(f"DeepSeek request failed: {retry_exc.reason}") from retry_exc
    except urllib.error.URLError as exc:
        raise DeepSeekMarkupError(f"DeepSeek request failed: {exc.reason}") from exc

    content = _message_content(raw)
    try:
        markup = json.loads(content)
    except json.JSONDecodeError:
        try:
            markup = json.loads(_extract_json_object(content))
        except json.JSONDecodeError as exc:
            raise DeepSeekMarkupError("DeepSeek message content is not valid JSON") from exc
    if not isinstance(markup, dict):
        raise DeepSeekMarkupError("DeepSeek returned JSON, but root value is not an object")
    return markup, raw


def _post_chat_completion(
    payload: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _message_content(raw: dict[str, Any]) -> str:
    try:
        content = raw["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekMarkupError("DeepSeek response does not contain choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise DeepSeekMarkupError("DeepSeek returned empty message content")
    return content.strip()


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise DeepSeekMarkupError("DeepSeek message content is not valid JSON")
    return text[start : end + 1]


def _block_kind(block: DocumentBlock) -> str:
    if block.kind == "heading":
        return "heading"
    if _option_label(block.text):
        return "option"
    return "paragraph"


def _option_label(text: str) -> str:
    match = OPTION_RE.match(text.strip())
    return match.group(1).upper() if match else ""


def _has_bold(block: DocumentBlock) -> bool:
    return any(span.text.strip() for span in block.bold_spans)


def _clean_meta_value(value: str) -> str:
    return re.sub(r"[|\r\n]+", " ", value).strip()
