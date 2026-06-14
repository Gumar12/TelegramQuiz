"""Unicode and UTF-8 helpers for generated parser artifacts."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any

from backend.pipeline.reports import ReportIssue

_SPACE_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2007": " ",
        "\u202f": " ",
    }
)
_MOJIBAKE_RE = re.compile(r"(?:Рџ|РЅ|Рє|Р°|Рё|Рµ|СЃ|С‚|С‹|СЏ|Ð|Ñ)")
_LETTER = r"A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі"
_MASS_QUESTION_MARKS_RE = re.compile(rf"[{_LETTER}]\?{{2,}}[{_LETTER}]")


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", str(text))
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.translate(_SPACE_TRANSLATION)
    lines = [" ".join(line.split()).strip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def _issue(
    code: str,
    message_ru: str,
    action_ru: str,
    *,
    source_ref: dict[str, Any] | None = None,
    severity: str = "error",
) -> ReportIssue:
    return ReportIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        message_ru=message_ru,
        action_ru=action_ru,
        source_ref=source_ref or {},
    )


def detect_suspect_encoding(
    text: str,
    *,
    source_ref: dict[str, Any] | None = None,
) -> list[ReportIssue]:
    normalized = normalize_text(text)
    issues: list[ReportIssue] = []
    if "�" in normalized:
        issues.append(
            _issue(
                "text_contains_replacement_char",
                "В тексте найден символ �, часть данных могла потеряться.",
                "Вернись к исходному документу и экспортируй его заново.",
                source_ref=source_ref,
            )
        )
    if _MOJIBAKE_RE.search(normalized):
        issues.append(
            _issue(
                "text_mojibake_detected",
                "Текст выглядит как результат неправильного чтения UTF-8/Windows-1251.",
                "Открой исходник и повтори импорт через UTF-8, не продолжай upload.",
                source_ref=source_ref,
            )
        )
    if _MASS_QUESTION_MARKS_RE.search(normalized):
        issues.append(
            _issue(
                "text_encoding_suspect",
                "Текст похож на поврежденную кодировку.",
                "Проверь исходный DOCX/JSON или импортируй файл заново в UTF-8.",
                source_ref=source_ref,
            )
        )
    return issues


def write_text_utf8(path: str | Path, content: str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes((content.replace("\r\n", "\n").replace("\r", "\n")).encode("utf-8"))
    return output_path


def write_json_utf8(path: str | Path, data: Any) -> Path:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return write_text_utf8(path, content)


def configure_cli_output_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")