"""Глобальные настройки: env-переменные и константы скорости/таймаутов.

Все задержки рандомизированы — Telegram не любит регулярные паттерны.
"""
import os
import random
from dotenv import load_dotenv

load_dotenv()

# --- Credentials ---
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE", "")
SESSION_NAME = "quizbot_session"

# --- Target bot ---
BOT_USERNAME = "QuizBot"

# --- Pacing (консервативно под живой аккаунт) ---
DELAY_BETWEEN_MESSAGES = (3.0, 6.0)       # сек, между любыми двумя send/click
DELAY_BETWEEN_QUESTIONS = (20.0, 40.0)    # сек, между концом одного вопроса и началом следующего
LONG_PAUSE_EVERY_N_QUESTIONS = 10          # каждые 10 вопросов
LONG_PAUSE_DURATION = (60.0, 120.0)       # сек

# --- Timeouts / retries ---
WAIT_REPLY_TIMEOUT = 15.0
MAX_RETRIES_ON_FLOOD = 3


def rand_delay(rng: tuple[float, float]) -> float:
    """Случайная задержка из заданного диапазона."""
    return random.uniform(*rng)


def assert_credentials() -> None:
    """Проверяет, что .env заполнен. Падает с понятной ошибкой, если нет."""
    missing = [
        name
        for name, val in [("API_ID", API_ID), ("API_HASH", API_HASH), ("PHONE", PHONE)]
        if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing env vars: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill in values from https://my.telegram.org"
        )
