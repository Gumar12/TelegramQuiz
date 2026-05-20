# QuizBot Uploader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Telethon-userbot CLI скрипт, который читает JSON со списком вопросов и заливает их в Telegram-квиз через @QuizBot от личного аккаунта пользователя с консервативной скоростью.

**Architecture:** Модульный CLI на Python 3.10+ с pydantic-валидацией и Telethon для общения с @QuizBot. Низкоуровневые примитивы (send/wait/click) изолированы в `quizbot_client.py`; высокоуровневый сценарий заливки — в `flow.py`. Тексты бота и подписи кнопок собираются на отдельном probe-шаге и фиксируются в константах `BOT_PROMPTS` — это самая хрупкая часть, изолируем её в одном месте.

**Tech Stack:** Python 3.10+, Telethon, pydantic v2, python-dotenv, asyncio, logging.

**Note on testing:** По явной просьбе пользователя автоматических тестов нет — это персональный скрипт, проверка только ручная (probe + smoke-прогон на 3 вопросах). Каждая задача завершается ручным smoke-check (импорт / синтаксис / dry-run) и коммитом.

---

## Task 1: Project scaffolding + git init

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `requirements.txt`
- Create: `questions.example.json`
- Create: `docs/probe-log.md` (placeholder)

- [ ] **Step 1: Initialize git repository**

Run:
```bash
cd C:\Users\Asus\Documents\Agentic\Quizbot
git init
git branch -M main
```

Expected: `Initialized empty Git repository`. No commit yet.

- [ ] **Step 2: Create `.gitignore`**

Содержимое:
```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
*.log

# Secrets — credentials, не коммитим
.env
*.session
*.session-journal

# Data — реальные вопросы могут быть приватными
questions.json

# IDE
.vscode/
.idea/
.DS_Store
```

- [ ] **Step 3: Create `.env.example`**

Содержимое:
```env
# Get these from https://my.telegram.org → API development tools
API_ID=123456
API_HASH=your_api_hash_here

# Your Telegram account phone in international format
PHONE=+77001234567
```

- [ ] **Step 4: Create `requirements.txt`**

Содержимое:
```
telethon>=1.36
pydantic>=2.0
python-dotenv>=1.0
```

- [ ] **Step 5: Create `questions.example.json`**

Содержимое:
```json
[
  {
    "question": "Кто был одним из основателей Казахского ханства?",
    "options": ["Керей", "Абылай хан", "Тауке хан", "Кенесары хан"],
    "correct": 1,
    "explanation": "Керей и Жанибек считаются основателями Казахского ханства."
  },
  {
    "question": "В каком году была принята Конституция Республики Казахстан?",
    "options": ["1991", "1993", "1995", "1997"],
    "correct": 3,
    "explanation": "Действующая Конституция принята на референдуме 30 августа 1995 года."
  },
  {
    "question": "Кто является автором эпоса \"Кобланды-батыр\"?",
    "options": ["Народный эпос", "Абай Кунанбаев", "Шакарим Кудайбердиев", "Мухтар Ауэзов"],
    "correct": 1,
    "explanation": "\"Кобланды-батыр\" — народный героический эпос, автор не установлен."
  }
]
```

- [ ] **Step 6: Create `docs/probe-log.md` placeholder**

Содержимое:
```markdown
# @QuizBot Probe Log

> Заполняется на Task 7 после ручного прохода создания квиза.
> Все тексты и подписи кнопок переносятся отсюда в `flow.py::BOT_PROMPTS`.

(будет заполнено)
```

- [ ] **Step 7: Install dependencies**

Run:
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Expected: Successfully installed telethon, pydantic, python-dotenv (и их зависимости).

- [ ] **Step 8: Commit**

```bash
git add .gitignore .env.example requirements.txt questions.example.json docs/
git commit -m "chore: project scaffolding"
```

---

## Task 2: `config.py` — env vars + constants

**Files:**
- Create: `config.py`

- [ ] **Step 1: Create `config.py` with full content**

```python
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
```

- [ ] **Step 2: Smoke-check imports**

Run:
```bash
python -c "import config; print('API_ID type:', type(config.API_ID).__name__); print('delay sample:', config.rand_delay(config.DELAY_BETWEEN_MESSAGES))"
```

Expected: печатает тип `int` и число между 3.0 и 6.0. Без ошибок.

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: config module with credentials and pacing constants"
```

---

## Task 3: `models.py` — pydantic Question

**Files:**
- Create: `models.py`

- [ ] **Step 1: Create `models.py` with full content**

```python
"""Pydantic-модель одного вопроса квиза.

Используется и для валидации входного JSON, и как типизированный объект
в `flow.py`.
"""
from pydantic import BaseModel, Field, field_validator, model_validator


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)
    correct: int = Field(ge=1)
    explanation: str = Field(default="", max_length=200)

    @field_validator("options")
    @classmethod
    def options_unique_and_bounded(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("options must be unique")
        for opt in v:
            if not (1 <= len(opt) <= 100):
                raise ValueError(f"option length out of range (1..100): {opt!r}")
        return v

    @model_validator(mode="after")
    def correct_in_range(self):
        if not (1 <= self.correct <= len(self.options)):
            raise ValueError(
                f"correct={self.correct} out of range 1..{len(self.options)}"
            )
        return self
```

- [ ] **Step 2: Smoke-check the model**

Run:
```bash
python -c "from models import Question; q = Question(question='Q?', options=['A','B'], correct=1); print('OK:', q.question, q.correct)"
```

Expected: `OK: Q? 1`.

- [ ] **Step 3: Smoke-check that invalid input is rejected**

Run:
```bash
python -c "from models import Question; Question(question='Q?', options=['A','B'], correct=5)"
```

Expected: `ValidationError` с понятным сообщением "correct=5 out of range 1..2".

- [ ] **Step 4: Commit**

```bash
git add models.py
git commit -m "feat: pydantic Question model with validators"
```

---

## Task 4: `parser.py` — load JSON

**Files:**
- Create: `parser.py`

- [ ] **Step 1: Create `parser.py` with full content**

```python
"""Чтение questions.json и его превращение в list[Question]."""
import json
from pathlib import Path
from pydantic import ValidationError

from models import Question


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

    if not isinstance(raw, list):
        raise ValueError(f"Expected top-level JSON array, got {type(raw).__name__}")

    questions: list[Question] = []
    for i, item in enumerate(raw, start=1):
        try:
            questions.append(Question(**item))
        except ValidationError as e:
            raise ValueError(f"Question #{i} invalid:\n{e}") from e

    if not questions:
        raise ValueError(f"No questions found in {p}")

    return questions
```

- [ ] **Step 2: Smoke-check on the example file**

Run:
```bash
python -c "from parser import load_json; qs = load_json('questions.example.json'); print(f'loaded {len(qs)} questions'); print('first:', qs[0].question)"
```

Expected: `loaded 3 questions` и текст первого вопроса.

- [ ] **Step 3: Commit**

```bash
git add parser.py
git commit -m "feat: JSON parser with pydantic validation"
```

---

## Task 5: `validator.py` — extra business checks

**Files:**
- Create: `validator.py`

- [ ] **Step 1: Create `validator.py` with full content**

```python
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
```

- [ ] **Step 2: Smoke-check on the example file**

Run:
```bash
python -c "from parser import load_json; from validator import validate_all; validate_all(load_json('questions.example.json')); print('all checks passed')"
```

Expected: `all checks passed`.

- [ ] **Step 3: Commit**

```bash
git add validator.py
git commit -m "feat: list-level business validators"
```

---

## Task 6: `quizbot_client.py` — Telethon wrapper

**Files:**
- Create: `quizbot_client.py`

- [ ] **Step 1: Create `quizbot_client.py` with full content**

```python
"""Низкоуровневая обёртка Telethon для диалога с @QuizBot.

Изолирует:
- логин через сессию
- conversation-режим (send → get_response)
- задержки и FloodWait-ретраи
- логирование стрелок ↔ для удобного дебага

Ничего не знает про вопросы — это уровень flow.py.
"""
import asyncio
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.custom.conversation import Conversation
from telethon.tl.custom.message import Message

import config

log = logging.getLogger(__name__)


class QuizBotClient:
    """Async context manager: открывает сессию + conversation с @QuizBot."""

    def __init__(self):
        self.client = TelegramClient(
            config.SESSION_NAME, config.API_ID, config.API_HASH
        )
        self._conv: Optional[Conversation] = None

    async def __aenter__(self) -> "QuizBotClient":
        await self.client.start(phone=config.PHONE)
        log.info("Telegram session started")
        self._conv = self.client.conversation(
            config.BOT_USERNAME,
            timeout=config.WAIT_REPLY_TIMEOUT,
            exclusive=True,
        )
        await self._conv.__aenter__()
        log.info("Opened conversation with @%s", config.BOT_USERNAME)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conv is not None:
            await self._conv.__aexit__(exc_type, exc_val, exc_tb)
        await self.client.disconnect()
        log.info("Telegram session closed")

    async def send_text(self, text: str) -> Message:
        """Шлёт текст в @QuizBot с задержкой и FloodWait-обработкой."""
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))
        last_exc: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES_ON_FLOOD):
            try:
                msg = await self._conv.send_message(text)
                log.info("→ %s", _truncate(text, 100))
                return msg
            except FloodWaitError as e:
                last_exc = e
                wait = e.seconds + 2
                log.warning(
                    "FloodWait %ds (attempt %d/%d) — sleeping",
                    e.seconds,
                    attempt + 1,
                    config.MAX_RETRIES_ON_FLOOD,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(f"FloodWait retries exhausted: {last_exc}")

    async def wait_reply(self) -> Message:
        """Ждёт следующий ответ от @QuizBot. Бросает asyncio.TimeoutError, если нет."""
        msg = await self._conv.get_response()
        log.info("← %s", _truncate(msg.text or "<no text>", 200))
        if msg.buttons:
            labels = [b.text for row in msg.buttons for b in row]
            log.debug("   buttons: %s", labels)
        return msg

    async def click(
        self,
        msg: Message,
        *,
        text: Optional[str] = None,
        index: Optional[int] = None,
    ) -> None:
        """Нажимает inline-кнопку по тексту или индексу."""
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))
        if text is not None:
            await msg.click(text=text)
            log.info("⌘ clicked button: %r", text)
        elif index is not None:
            await msg.click(index)
            log.info("⌘ clicked button index: %d", index)
        else:
            raise ValueError("must specify either text= or index=")


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"
```

- [ ] **Step 2: Smoke-check import only (no live connection)**

Run:
```bash
python -c "from quizbot_client import QuizBotClient; print('imports OK')"
```

Expected: `imports OK`. Никакого live-коннекта тут не делаем.

- [ ] **Step 3: Commit**

```bash
git add quizbot_client.py
git commit -m "feat: Telethon QuizBot client wrapper"
```

---

## Task 7: Probe script + manual probe run

**Files:**
- Create: `probe.py`
- Modify: `docs/probe-log.md`

⚠️ **Эта задача требует ручного действия от пользователя — он должен авторизоваться в Telegram (один раз) и пройти создание квиза в @QuizBot руками.**

- [ ] **Step 1: Create `probe.py`**

```python
"""Probe-скрипт: подключается к Telegram через Telethon и логирует ВСЕ
входящие сообщения от @QuizBot вместе с подписями inline-кнопок.

Запуск:
    1. Скопировать .env.example → .env, заполнить API_ID/API_HASH/PHONE
    2. python probe.py
    3. При первом запуске ввести код подтверждения из Telegram
    4. Открыть @QuizBot в любом Telegram-клиенте (телефон/десктоп)
    5. Создать тестовый квиз с 1-2 вопросами руками
    6. В терминале появятся все сообщения бота с разметкой кнопок
    7. Скопировать тексты и подписи кнопок в docs/probe-log.md
    8. Ctrl+C для выхода
"""
import asyncio
import logging

from telethon import TelegramClient, events

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("probe")


async def main() -> None:
    config.assert_credentials()
    client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
    await client.start(phone=config.PHONE)
    bot = await client.get_entity(config.BOT_USERNAME)
    log.info("Connected. Listening for messages from @%s (id=%s)", config.BOT_USERNAME, bot.id)
    log.info("Now go to @QuizBot in your Telegram app and create a test quiz manually.")
    log.info("Press Ctrl+C to stop.\n")

    @client.on(events.NewMessage(from_users=bot.id))
    async def handler(event):
        msg = event.message
        print("=" * 70)
        print("TEXT:")
        print(msg.text or "<no text>")
        if msg.buttons:
            print("\nBUTTONS:")
            for row_idx, row in enumerate(msg.buttons):
                for col_idx, btn in enumerate(row):
                    print(f"  [{row_idx},{col_idx}]: {btn.text!r}")
        print()

    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProbe stopped.")
```

- [ ] **Step 2: User: prepare `.env`**

```bash
copy .env.example .env
```
Открыть `.env` в редакторе, заполнить **API_ID**, **API_HASH**, **PHONE** из https://my.telegram.org → API development tools.

- [ ] **Step 3: User: run probe script**

```bash
python probe.py
```

При первом запуске Telethon спросит код подтверждения из Telegram (придёт в чат с самим собой). Возможно попросит 2FA-пароль, если он включён. После успешной авторизации создастся `quizbot_session.session` файл.

- [ ] **Step 4: User: пройти создание квиза в @QuizBot руками**

Параллельно (пока probe.py крутится) в любом Telegram-клиенте:
1. Открыть чат с @QuizBot, нажать `/start`
2. Создать новый квиз (через кнопку или команду)
3. Дать ему имя
4. Добавить 1 вопрос с 3-4 вариантами и пояснением
5. Дойти до завершения квиза и получения share-link

Все сообщения @QuizBot будут идти в терминал probe.py с разметкой кнопок.

- [ ] **Step 5: User: заполнить `docs/probe-log.md`**

Заменить плейсхолдер реальной таблицей. Шаблон:

```markdown
# @QuizBot Probe Log

> Заполнено вручную 2026-05-20.
> Эти значения переносятся в `flow.py::BOT_PROMPTS`.

## Шаг 1: После /start
- Текст бота: `<точный текст>`
- Кнопки:
  - `[0,0]`: `"<точная подпись>"`  ← Создать квиз

## Шаг 2: После клика "Создать квиз"
- Текст бота: `<точный текст>`
- Кнопки: <нет / есть какие>

## Шаг 3: После отправки имени квиза
- Текст бота: `<точный текст про первый вопрос>`

## Шаг 4: После отправки текста вопроса
- Текст бота: `<точный текст про варианты>`

## Шаг 5: Как бот принимает варианты
- По одному сообщению / одно сообщение со списком?
- После какого триггера бот спрашивает "какой правильный"?

## Шаг 6: Выбор правильного ответа
- Текст бота: `<точный текст>`
- Кнопки: список подписей (обычно 1/2/3/4 или сами тексты опций)

## Шаг 7: Объяснение
- Текст бота: `<точный текст>`
- Кнопка пропуска: `"<подпись>"` или команда `/skip`?

## Шаг 8: Следующий вопрос / завершение
- Текст бота после объяснения: `<точный текст>`
- Кнопки: `"<следующий>"`, `"<завершить>"` (точные подписи)

## Шаг 9: Финальное сообщение со share-link
- Формат share-link: `https://t.me/QuizBot?start=...` или другой
- Pattern для регэкспа: ___
```

- [ ] **Step 6: Stop probe + commit**

В терминале с probe.py: `Ctrl+C`.

```bash
git add probe.py docs/probe-log.md
git commit -m "feat: probe script + captured @QuizBot prompts"
```

⚠️ `.env` и `quizbot_session.session` НЕ должны попасть в коммит — `.gitignore` их закрывает.

---

## Task 8: `flow.py` — high-level upload scenario

**Files:**
- Create: `flow.py`

⚠️ Перед началом этой задачи у тебя на руках должен быть заполненный `docs/probe-log.md`. Тексты ниже — **шаблоны**, заменить на реальные значения из probe-log.

- [ ] **Step 1: Create `flow.py` with full content**

Подставить реальные тексты из `docs/probe-log.md` в словарь `BOT_PROMPTS` и в строковые литералы кликов (помечены `# FROM_PROBE`).

```python
"""Высокоуровневый сценарий заливки квиза в @QuizBot.

Состоит из трёх этапов:
1. create_quiz — /start → создать квиз → дать имя
2. upload_question — для каждого вопроса: текст → варианты → правильный → пояснение
3. finish_quiz — завершить, получить share-link

Тексты бота вынесены в BOT_PROMPTS из docs/probe-log.md. Если @QuizBot
поменяет UI, чинить здесь.
"""
import asyncio
import logging
import re
from typing import Optional

from telethon.tl.custom.message import Message

import config
from models import Question
from quizbot_client import QuizBotClient

log = logging.getLogger(__name__)

# --- Тексты, скопированные из docs/probe-log.md ---
# Используются как substring-маркеры (а не точное равенство), чтобы
# мелкие правки бота не ломали матчинг.
BOT_PROMPTS = {
    "start_menu":         "Create a new quiz",   # FROM_PROBE — подпись кнопки в стартовом меню
    "ask_quiz_name":      "send me the name",     # FROM_PROBE — текст после "Create a new quiz"
    "ask_question_text":  "send me the question", # FROM_PROBE — после имени или после "next question"
    "ask_option":         "Send the options",     # FROM_PROBE — после текста вопроса
    "ask_correct":        "which option is correct", # FROM_PROBE — после всех опций
    "ask_explanation":    "explanation",          # FROM_PROBE — после выбора правильного
    "ask_next_or_done":   "Add the next question", # FROM_PROBE — после пояснения / skip
    "finished":           "your quiz is ready",   # FROM_PROBE — финальное сообщение
}

# Подписи кнопок (точные, из probe). Регистр имеет значение.
BTN_CREATE_QUIZ = "Create a new quiz"     # FROM_PROBE
BTN_SKIP_EXPLANATION = "Skip"             # FROM_PROBE — или команда /skip если кнопки нет
BTN_DONE_WITH_OPTIONS = "/done"           # FROM_PROBE — команда или кнопка
BTN_NEXT_QUESTION = "Next question"       # FROM_PROBE
BTN_FINISH_QUIZ = "Done"                  # FROM_PROBE
SHARE_LINK_RE = re.compile(r"https?://t\.me/\S+")  # FROM_PROBE — формат ссылки


class UnexpectedBotState(RuntimeError):
    """Бот ответил не тем, что мы ждали. Hard abort."""


def assert_contains(text: Optional[str], expected_substr: str, step: str) -> None:
    haystack = (text or "").lower()
    needle = expected_substr.lower()
    if needle not in haystack:
        raise UnexpectedBotState(
            f"[{step}] expected to contain {expected_substr!r}, "
            f"got: {text!r}"
        )


async def create_quiz(client: QuizBotClient, quiz_name: str) -> None:
    """Старт + создание квиза + установка имени."""
    log.info("=== Creating quiz: %s ===", quiz_name)
    await client.send_text("/start")
    reply = await client.wait_reply()

    # @QuizBot может прислать несколько сообщений подряд — нам нужно то,
    # где есть кнопка "Create a new quiz".
    target = reply
    if not _has_button(target, BTN_CREATE_QUIZ):
        target = await client.wait_reply()
        if not _has_button(target, BTN_CREATE_QUIZ):
            raise UnexpectedBotState(
                f"No '{BTN_CREATE_QUIZ}' button found in first two replies"
            )

    await client.click(target, text=BTN_CREATE_QUIZ)
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_quiz_name"], "ask_quiz_name")

    await client.send_text(quiz_name)


async def upload_question(client: QuizBotClient, q: Question, index_in_quiz: int) -> None:
    """Заливает один вопрос. index_in_quiz нужен для пауз между вопросами."""
    log.info("--- Question %d: %s ---", index_in_quiz, q.question[:60])

    # 1. Текст вопроса
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_question_text"], "ask_question_text")
    await client.send_text(q.question)

    # 2. Варианты — отправляем по одному (точное поведение из probe)
    for opt in q.options:
        reply = await client.wait_reply()
        assert_contains(reply.text, BOT_PROMPTS["ask_option"], "ask_option")
        await client.send_text(opt)

    # 3. Команда "опции закончились" — если в probe выяснилось, что нужна
    await client.send_text(BTN_DONE_WITH_OPTIONS)

    # 4. Выбор правильного ответа — это inline-кнопки 0..N-1
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_correct"], "ask_correct")
    await client.click(reply, index=q.correct - 1)

    # 5. Пояснение
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_explanation"], "ask_explanation")
    if q.explanation:
        await client.send_text(q.explanation)
    else:
        # Если кнопка Skip есть — кликаем. Если нет — отправляем /skip.
        if _has_button(reply, BTN_SKIP_EXPLANATION):
            await client.click(reply, text=BTN_SKIP_EXPLANATION)
        else:
            await client.send_text("/skip")

    # 6. Пауза между вопросами + длинная пауза каждые N
    pause = config.rand_delay(config.DELAY_BETWEEN_QUESTIONS)
    log.info("Pausing %.1fs before next question", pause)
    await asyncio.sleep(pause)

    if index_in_quiz > 0 and index_in_quiz % config.LONG_PAUSE_EVERY_N_QUESTIONS == 0:
        long_pause = config.rand_delay(config.LONG_PAUSE_DURATION)
        log.info("Long pause: %.1fs (every %d questions)",
                 long_pause, config.LONG_PAUSE_EVERY_N_QUESTIONS)
        await asyncio.sleep(long_pause)


async def finish_quiz(client: QuizBotClient) -> str:
    """Завершает квиз и возвращает share-link."""
    log.info("=== Finishing quiz ===")
    # После последнего пояснения бот спрашивает "next or done?"
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_next_or_done"], "ask_next_or_done")

    if _has_button(reply, BTN_FINISH_QUIZ):
        await client.click(reply, text=BTN_FINISH_QUIZ)
    else:
        await client.send_text("/done")

    # Ждём финального сообщения со ссылкой
    final = await client.wait_reply()
    assert_contains(final.text, BOT_PROMPTS["finished"], "finished")

    link_match = SHARE_LINK_RE.search(final.text or "")
    if not link_match:
        raise UnexpectedBotState(
            f"No share link found in final message: {final.text!r}"
        )
    return link_match.group(0)


def _has_button(msg: Message, text: str) -> bool:
    if not msg.buttons:
        return False
    for row in msg.buttons:
        for btn in row:
            if btn.text and text.lower() in btn.text.lower():
                return True
    return False
```

- [ ] **Step 2: Smoke-check imports**

Run:
```bash
python -c "import flow; print('imports OK, BOT_PROMPTS keys:', list(flow.BOT_PROMPTS.keys()))"
```

Expected: `imports OK, BOT_PROMPTS keys: ['start_menu', 'ask_quiz_name', ...]`.

- [ ] **Step 3: Commit**

```bash
git add flow.py
git commit -m "feat: high-level quiz upload flow"
```

---

## Task 9: `main.py` — CLI entry point

**Files:**
- Create: `main.py`

- [ ] **Step 1: Create `main.py` with full content**

```python
"""CLI entry point.

Usage:
    python main.py --file questions.json --name "My Quiz" [--debug]
"""
import argparse
import asyncio
import logging
import sys
import traceback

import config
from flow import UnexpectedBotState, create_quiz, finish_quiz, upload_question
from parser import load_json
from quizbot_client import QuizBotClient
from validator import validate_all


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("quizbot_uploader.log", encoding="utf-8"),
        ],
    )
    # Telethon очень болтлив на DEBUG — приглушаем
    if not debug:
        logging.getLogger("telethon").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Upload a quiz to @QuizBot from a JSON file."
    )
    p.add_argument("--file", required=True, help="Path to questions.json")
    p.add_argument("--name", required=True, help="Quiz name shown in @QuizBot")
    p.add_argument("--debug", action="store_true", help="Verbose logging")
    return p.parse_args()


async def run(file_path: str, quiz_name: str) -> int:
    config.assert_credentials()

    log = logging.getLogger("main")
    log.info("Loading questions from %s", file_path)
    questions = load_json(file_path)
    validate_all(questions)
    log.info("Loaded and validated %d questions", len(questions))

    log.info("Connecting to Telegram as %s …", config.PHONE)
    async with QuizBotClient() as client:
        try:
            await create_quiz(client, quiz_name)
            for i, q in enumerate(questions, start=1):
                await upload_question(client, q, index_in_quiz=i)
            share_link = await finish_quiz(client)
        except UnexpectedBotState as e:
            log.error("Bot state mismatch: %s", e)
            log.error("Last steps logged above. Delete the draft quiz in @QuizBot and retry.")
            return 2
        except asyncio.TimeoutError:
            log.error("Timed out waiting for @QuizBot reply (>%.0fs)",
                      config.WAIT_REPLY_TIMEOUT)
            log.error("Bot did not respond. Possible causes: network, anti-spam throttle, bot changed.")
            return 3

    log.info("=" * 60)
    log.info("✅ Quiz uploaded: %d questions", len(questions))
    log.info("🔗 Share link: %s", share_link)
    log.info("=" * 60)
    return 0


def main() -> None:
    args = parse_args()
    setup_logging(args.debug)
    try:
        exit_code = asyncio.run(run(args.file, args.name))
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        # Validation / config errors — без traceback'а, понятное сообщение
        print(f"ERROR: {e}", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        exit_code = 130
    except Exception:
        traceback.print_exc()
        exit_code = 99
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-check CLI parsing**

Run:
```bash
python main.py --help
```

Expected: usage-сообщение с описанием флагов `--file`, `--name`, `--debug`.

- [ ] **Step 3: Smoke-check: дрянной JSON ловится до коннекта**

Создать временный `bad.json` (например, с `correct: 99`) и:
```bash
python main.py --file bad.json --name "Bad" 2>&1
```

Expected: `ERROR: Question #1 invalid: ...` и exit code 1, **без попытки соединения с Telegram**.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: main CLI entry point"
```

---

## Task 10: `README.md`

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

````markdown
# QuizBot Uploader

Telethon-userbot для автоматической заливки вопросов в Telegram-квиз через **@QuizBot**.
Работает от твоего личного аккаунта (не Bot API), пишет с консервативной скоростью,
чтобы не получить anti-spam от Telegram.

## Setup

### 1. Получить API credentials

1. Открыть https://my.telegram.org → войти по номеру → **API development tools**
2. Создать приложение (любые название/описание)
3. Скопировать `api_id` и `api_hash`

### 2. Установка

```bash
git clone <repo>
cd Quizbot
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
```

### 3. Конфигурация

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # Linux/Mac
```

Открыть `.env` и заполнить:
- `API_ID` — число из my.telegram.org
- `API_HASH` — строка оттуда же
- `PHONE` — твой номер в формате `+77001234567`

### 4. Первый запуск (probe)

```bash
python probe.py
```

При первом запуске Telegram пришлёт код подтверждения в чат с самим собой. Введи его.
Если включена 2FA — попросит пароль. После этого создастся `quizbot_session.session`.

С запущенным `probe.py` открой @QuizBot в любом Telegram-клиенте и создай тестовый квиз
руками. Все сообщения бота с подписями кнопок будут литься в терминал. Перенеси их в
`docs/probe-log.md` и обнови `BOT_PROMPTS` в `flow.py`.

После этого — `Ctrl+C` в терминале с probe.

## Использование

### Формат входного JSON

`questions.json`:
```json
[
  {
    "question": "Текст вопроса?",
    "options": ["Вариант 1", "Вариант 2", "Вариант 3", "Вариант 4"],
    "correct": 1,
    "explanation": "Пояснение, можно пустую строку"
  }
]
```

- `correct` — индекс правильного ответа, считая **с 1**
- `options` — от 2 до 10 вариантов, без дублей
- `explanation` — опциональный, до 200 символов

### Запуск

```bash
python main.py --file questions.json --name "Название квиза"
```

После успешной заливки в логе появится share-link квиза.

### Флаги

- `--debug` — подробное логирование (тексты сообщений целиком, события Telethon)

## Что делать если упало

| Exit code | Причина | Действие |
|---|---|---|
| 1 | Невалидный JSON / config | Прочитай ERROR-сообщение, исправь файл |
| 2 | Бот ответил не тем, что ждали | UI @QuizBot мог поменяться. Перезапусти `probe.py`, обнови `flow.py::BOT_PROMPTS` |
| 3 | Таймаут ответа бота | Сеть / anti-spam. Подожди 10-15 минут, перезапусти |
| 130 | Ctrl+C | Удали недозаписанный квиз в @QuizBot вручную и перезапусти |

## Скорость

По умолчанию:
- 3–6 сек между любыми сообщениями
- 20–40 сек между вопросами
- Дополнительная пауза 60–120 сек каждые 10 вопросов

Это медленно — 20 вопросов займут ~8-12 минут. Так и задумано: live-аккаунт не должен
выглядеть как бот.

Менять — в `config.py`.

## Безопасность

- `.env` и `*.session` файлы НЕ коммитить (уже в `.gitignore`)
- Session-файл = доступ к твоему Telegram-аккаунту, обращаться как с приватным ключом
- При утечке session — отозвать сессию в Telegram → Settings → Devices

## Структура

```
.
├── main.py              # CLI entry point
├── config.py            # env + константы
├── models.py            # pydantic Question
├── parser.py            # load_json
├── validator.py         # list-level проверки
├── quizbot_client.py    # Telethon-обёртка
├── flow.py              # сценарий заливки (BOT_PROMPTS здесь)
├── probe.py             # дебаг: дамп сообщений @QuizBot
├── questions.example.json
└── docs/
    ├── probe-log.md             # расшифровка UI @QuizBot
    └── superpowers/
        ├── specs/2026-05-20-quizbot-uploader-design.md
        └── plans/2026-05-20-quizbot-uploader.md
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with setup and usage"
```

---

## Task 11: End-to-end smoke run on 3 questions

⚠️ Эта задача — ручная проверка. Никакого кода, только запуск и наблюдение.

**Files:**
- Optional create: `questions.json` (можно скопировать из example)

- [ ] **Step 1: Подготовить файл**

```bash
copy questions.example.json questions.json
```

Или подсунуть свои 3 реальных вопроса в том же формате.

- [ ] **Step 2: Удалить тестовый квиз из probe, если он остался**

В Telegram открыть @QuizBot, найти тестовый квиз из probe-шага, удалить через меню квиза.

- [ ] **Step 3: Запустить заливку**

```bash
python main.py --file questions.json --name "Smoke Test 2026-05-20"
```

Ожидаемое время: ~2-4 минуты на 3 вопроса (с задержками).

- [ ] **Step 4: Проверить результаты**

В логе должно быть:
- Логи стрелок `→` (наши сообщения) и `←` (ответы бота) для каждого шага
- Финальная строка `🔗 Share link: https://t.me/QuizBot?start=...`
- exit code 0

Открыть share-link в Telegram, пройти квиз — все 3 вопроса должны быть на месте,
правильные ответы помечены верно, пояснения отображаются.

- [ ] **Step 5: Если упало**

Скорее всего что-то не сошлось с `BOT_PROMPTS`. Перечитать `docs/probe-log.md`,
сравнить с тем, что реально приходит в логах (с `--debug`), обновить тексты в
`flow.py::BOT_PROMPTS`, удалить недозаписанный черновик в @QuizBot, повторить.

- [ ] **Step 6: Final commit (если что-то правил в flow.py)**

```bash
git add flow.py
git commit -m "fix: align BOT_PROMPTS with real @QuizBot UI after smoke run"
```

---

## Self-review checklist (выполнено автором плана)

- [x] **Spec coverage:** все секции спека покрыты задачами — стек (T1), конфиг (T2), модели (T3), парсер (T4), валидатор (T5), telethon-обёртка (T6), probe (T7), flow (T8), CLI (T9), README (T10), DoD smoke-run (T11)
- [x] **Placeholder scan:** в `BOT_PROMPTS` стоят placeholder-значения, помеченные `# FROM_PROBE` — это **намеренные** плейсхолдеры, которые user обязан заменить на реальные значения из probe-log; в плане явно сказано как и где это сделать
- [x] **Type consistency:** `QuizBotClient.click(text=..., index=...)` использован одинаково в quizbot_client.py и flow.py; `Question(question, options, correct, explanation)` совпадает между models.py, parser.py, validator.py, flow.py
- [x] **No tests:** в плане нет ни одной `pytest` команды, нет `tests/` папки, нет mock-агентов — соответствует user feedback "не нужны тесты для личных скриптов"
- [x] **Conservative pacing:** DELAY_* в config.py соответствуют user feedback "не быстрее чем 3-6с/сообщение"
