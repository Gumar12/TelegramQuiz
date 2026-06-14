"""Чтение questions.json и его превращение в list[Question]."""
import json
from pathlib import Path
from pydantic import ValidationError

from backend.models import Question


def load_json(path: str | Path) -> list[Question]:
    """Читает JSON-файл и парсит в список Question.

    Падает с понятной ошибкой, если файла нет, JSON битый, или валидация
    pydantic не прошла.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Questions file not found: {p}")

    raw_text = p.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {p}: {e}") from e

    if isinstance(raw, dict) and "questions" in raw:
        raw = raw["questions"]

    if not isinstance(raw, list):
        raise ValueError(f"Expected top-level JSON array or object with questions, got {type(raw).__name__}")

    questions: list[Question] = []
    for i, item in enumerate(raw, start=1):
        try:
            questions.append(Question(**item))
        except ValidationError as e:
            raise ValueError(f"Question #{i} invalid:\n{e}") from e

    if not questions:
        raise ValueError(f"No questions found in {p}")

    return questions
