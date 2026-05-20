"""Бизнес-проверки сверх pydantic — то, что касается списка целиком."""
from models import Question


def check_no_duplicate_questions(questions: list[Question]) -> None:
    """Падает, если два вопроса в списке имеют одинаковый текст."""
    seen: dict[str, int] = {}
    for i, q in enumerate(questions, start=1):
        key = q.question.strip().lower()
        if key in seen:
            raise ValueError(
                f"Duplicate question text at #{i} and #{seen[key]}: {q.question!r}"
            )
        seen[key] = i


def check_question_count(questions: list[Question], max_count: int = 100) -> None:
    """Хард-кап на количество вопросов в одном квизе.

    Telegram-квиз технически тянет много, но за один заход через userbot
    больше 100 — повышенный риск anti-spam от Telegram.
    """
    if len(questions) > max_count:
        raise ValueError(
            f"Too many questions in one quiz: {len(questions)} > {max_count}. "
            f"Split into multiple files."
        )


def validate_all(questions: list[Question]) -> None:
    """Запускает все list-level проверки."""
    check_no_duplicate_questions(questions)
    check_question_count(questions)
