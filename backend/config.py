"""Глобальные настройки: env-переменные и константы скорости/таймаутов.

Все задержки рандомизированы — Telegram не любит регулярные паттерны.
"""
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

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

DEFAULT_STUDIO_CORS_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)


def studio_cors_origins(raw: str | None = None) -> list[str]:
    """Return explicit local origins allowed to call the Studio API from a browser."""
    value = os.getenv("STUDIO_CORS_ORIGINS", "") if raw is None else raw
    if not str(value).strip():
        return list(DEFAULT_STUDIO_CORS_ORIGINS)

    origins: list[str] = []
    seen: set[str] = set()
    for item in str(value).split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if "*" in origin:
            raise ValueError("STUDIO_CORS_ORIGINS must not contain wildcards")
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("STUDIO_CORS_ORIGINS entries must be absolute http(s) origins")
        if parsed.path or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("STUDIO_CORS_ORIGINS entries must not include path, query or fragment")
        normalized = f"{parsed.scheme}://{parsed.netloc}"
        if normalized not in seen:
            seen.add(normalized)
            origins.append(normalized)
    if not origins:
        raise ValueError("STUDIO_CORS_ORIGINS must include at least one origin")
    return origins

# --- Credentials ---
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE", "")
SESSION_NAME = str(RUNTIME_DIR / "quizbot_session")
LOG_PATH = RUNTIME_DIR / "quizbot_uploader.log"
PROBE_LOG_PATH = RUNTIME_DIR / "probe.log"

# --- Optional AI markup for DOCX parsing ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
DEEPSEEK_BASE_URL = (os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip() or "https://api.deepseek.com").rstrip("/")
DEEPSEEK_TIMEOUT_SECONDS = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "240"))
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "80000"))

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
    "slow": {
        "DELAY_BETWEEN_MESSAGES": (6.0, 10.0),
        "DELAY_BETWEEN_QUESTIONS": (60.0, 90.0),
        "LONG_PAUSE_EVERY_N_QUESTIONS": 8,
        "LONG_PAUSE_DURATION": (180.0, 300.0),
    },
}

AUTO_SPEED_POLICY = {
    "preset": "fast",
    "cooldown_every_uploaded": 40,
    "cooldown_duration": (300.0, 420.0),
}

# --- ETA model ---
ETA_SETTINGS_FILENAME = "eta_settings.json"
ETA_BOT_RESPONSE_SECONDS = float(os.getenv("ETA_BOT_RESPONSE_SECONDS", "2.0"))
ETA_MIN_BOT_RESPONSE_SECONDS = 0.0
ETA_MAX_BOT_RESPONSE_SECONDS = 30.0

# --- Timeouts / retries ---
WAIT_REPLY_TIMEOUT = 15.0
MAX_RETRIES_ON_FLOOD = 3
# Любой FloodWait дольше этого порога не «спим» внутри ретрая (это могут быть
# часы), а классифицируем в контролируемую паузу с retry-after-метаданными.
FLOOD_WAIT_MAX_SECONDS = float(os.getenv("FLOOD_WAIT_MAX_SECONDS", "300"))
# Доп. джиттер поверх e.seconds для FloodWait-ретраев ниже порога.
FLOOD_WAIT_RETRY_JITTER = (1.0, 3.0)


@dataclass(frozen=True, slots=True)
class TimingProfile:
    speed_mode: str
    delay_between_messages: tuple[float, float]
    delay_between_questions: tuple[float, float]
    long_pause_every_n_questions: int
    long_pause_duration: tuple[float, float]
    flood_wait_max_seconds: float = FLOOD_WAIT_MAX_SECONDS


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


def build_timing_profile(mode: str) -> TimingProfile:
    """Build an immutable timing profile for a single run."""
    resolved_mode = auto_speed_preset(0) if mode == "auto" else mode
    if resolved_mode not in SPEED_PRESETS:
        raise ValueError(
            f"Unknown speed mode {mode!r}. Available: {', '.join(SPEED_PRESETS)}"
        )

    preset = SPEED_PRESETS[resolved_mode]
    return TimingProfile(
        speed_mode=resolved_mode,
        delay_between_messages=tuple(preset["DELAY_BETWEEN_MESSAGES"]),
        delay_between_questions=tuple(preset["DELAY_BETWEEN_QUESTIONS"]),
        long_pause_every_n_questions=int(preset["LONG_PAUSE_EVERY_N_QUESTIONS"]),
        long_pause_duration=tuple(preset["LONG_PAUSE_DURATION"]),
        flood_wait_max_seconds=float(FLOOD_WAIT_MAX_SECONDS),
    )


def auto_speed_preset(uploaded_questions: int) -> str:
    """Return the concrete preset for upload --speed auto."""
    return str(AUTO_SPEED_POLICY["preset"])


def load_eta_settings(runtime_dir: str | Path | None = None) -> dict[str, float]:
    """Load tunable ETA settings stored next to runtime state."""
    settings = {"bot_response_seconds": _clamp_eta_seconds(ETA_BOT_RESPONSE_SECONDS)}
    path = _eta_settings_path(runtime_dir)
    if not path.exists():
        return settings
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if isinstance(payload, dict) and "bot_response_seconds" in payload:
        settings["bot_response_seconds"] = _clamp_eta_seconds(payload["bot_response_seconds"])
    return settings


def save_eta_settings(settings: dict[str, float], runtime_dir: str | Path | None = None) -> dict[str, float]:
    """Persist tunable ETA settings and return sanitized values."""
    current = load_eta_settings(runtime_dir)
    if "bot_response_seconds" in settings:
        current["bot_response_seconds"] = _clamp_eta_seconds(settings["bot_response_seconds"])
    path = _eta_settings_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return current


def estimate_timing_profile(mode: str, *, runtime_dir: str | Path | None = None) -> dict[str, float | int]:
    """Build ETA timings from the same speed presets used by uploads."""
    profile = build_timing_profile(mode)
    eta_settings = load_eta_settings(runtime_dir)
    return {
        "seconds_per_question": (
            _avg_delay(profile.delay_between_messages)
            + _avg_delay(profile.delay_between_questions)
            + eta_settings["bot_response_seconds"]
        ),
        "long_pause_every": int(profile.long_pause_every_n_questions or 0),
        "long_pause_seconds": _avg_delay(profile.long_pause_duration),
        "cooldown_every_uploaded": int(AUTO_SPEED_POLICY.get("cooldown_every_uploaded") or 0) if mode == "auto" else 0,
        "cooldown_seconds": _avg_delay(AUTO_SPEED_POLICY.get("cooldown_duration", (0.0, 0.0))) if mode == "auto" else 0.0,
        "bot_response_seconds": eta_settings["bot_response_seconds"],
    }


def _eta_settings_path(runtime_dir: str | Path | None = None) -> Path:
    return Path(runtime_dir) / ETA_SETTINGS_FILENAME if runtime_dir is not None else RUNTIME_DIR / ETA_SETTINGS_FILENAME


def _avg_delay(value: object) -> float:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (float(value[0]) + float(value[1])) / 2
    return float(value or 0)


def _clamp_eta_seconds(value: object) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = ETA_BOT_RESPONSE_SECONDS
    return max(ETA_MIN_BOT_RESPONSE_SECONDS, min(ETA_MAX_BOT_RESPONSE_SECONDS, seconds))


def assert_credentials() -> None:
    """Проверяет legacy env-credentials для старых CLI/probe сценариев."""
    missing = [
        name
        for name, val in [("API_ID", API_ID), ("API_HASH", API_HASH), ("PHONE", PHONE)]
        if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing env vars: {', '.join(missing)}. "
            "The web platform does not use these legacy env vars; configure "
            "Telegram account profiles on the backend side. For legacy CLI/probe usage, "
            "provide API_ID/API_HASH/PHONE manually."
        )
