"""Глобальные настройки: env-переменные и константы скорости/таймаутов.

Все задержки рандомизированы — Telegram не любит регулярные паттерны.
"""
import os
import random
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
RUNTIME_DIR = DATA_DIR / "runtime"

ENV_FILE = BACKEND_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv(PROJECT_ROOT / ".env")

RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

# --- Credentials ---
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE", "")
SESSION_NAME = str(RUNTIME_DIR / "quizbot_session")
LOG_PATH = RUNTIME_DIR / "quizbot_uploader.log"
PROBE_LOG_PATH = RUNTIME_DIR / "probe.log"

# --- Target bot ---
BOT_USERNAME = "QuizBot"

# --- Pacing (консервативно под живой аккаунт) ---
DELAY_BETWEEN_MESSAGES = (3.0, 6.0)       # сек, между любыми двумя send/click
DELAY_BETWEEN_QUESTIONS = (20.0, 40.0)    # сек, между концом одного вопроса и началом следующего
LONG_PAUSE_EVERY_N_QUESTIONS = 10          # каждые 10 вопросов
LONG_PAUSE_DURATION = (60.0, 120.0)       # сек

SPEED_PRESETS = {
    "normal": {
        "DELAY_BETWEEN_MESSAGES": (3.0, 6.0),
        "DELAY_BETWEEN_QUESTIONS": (20.0, 40.0),
        "LONG_PAUSE_EVERY_N_QUESTIONS": 10,
        "LONG_PAUSE_DURATION": (60.0, 120.0),
    },
    "fast": {
        "DELAY_BETWEEN_MESSAGES": (1.5, 3.0),
        "DELAY_BETWEEN_QUESTIONS": (5.0, 10.0),
        "LONG_PAUSE_EVERY_N_QUESTIONS": 10,
        "LONG_PAUSE_DURATION": (20.0, 35.0),
    },
}

# --- Timeouts / retries ---
WAIT_REPLY_TIMEOUT = 15.0
MAX_RETRIES_ON_FLOOD = 3


def rand_delay(rng: tuple[float, float]) -> float:
    """Случайная задержка из заданного диапазона."""
    return random.uniform(*rng)


def apply_speed_mode(mode: str) -> None:
    """Apply pacing preset for the current process."""
    if mode not in SPEED_PRESETS:
        raise ValueError(
            f"Unknown speed mode {mode!r}. Available: {', '.join(SPEED_PRESETS)}"
        )

    preset = SPEED_PRESETS[mode]
    globals()["DELAY_BETWEEN_MESSAGES"] = preset["DELAY_BETWEEN_MESSAGES"]
    globals()["DELAY_BETWEEN_QUESTIONS"] = preset["DELAY_BETWEEN_QUESTIONS"]
    globals()["LONG_PAUSE_EVERY_N_QUESTIONS"] = preset["LONG_PAUSE_EVERY_N_QUESTIONS"]
    globals()["LONG_PAUSE_DURATION"] = preset["LONG_PAUSE_DURATION"]


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
            f"Copy backend/.env.example to backend/.env and fill in values from https://my.telegram.org"
        )
