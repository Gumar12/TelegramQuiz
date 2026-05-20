# QuizBot Uploader — Design Spec

**Date:** 2026-05-20
**Status:** Approved (with modifications)
**Author:** brainstorming session

## Goal

Полуавтоматический скрипт, который читает рабочий JSON со списком вопросов и
заливает их в Telegram-квиз через **@QuizBot**, используя **Telethon-userbot**
(не Bot API), с консервативной скоростью, безопасной для личного аккаунта.

## Non-goals (явный scope-cut)

- Excel-парсер — отложено до стабильного JSON-пути
- Авто-коррекция данных (исправление `correct` вне диапазона и т.п.) — только валидация, без правки
- Resume-from-failure — упал, исправил, перезапустил вручную
- Параллельная заливка нескольких квизов
- Reactive event handler (`@client.on`) — для линейного сценария избыточно
- Unit / mock-тесты — проверка только ручная на реальных данных
- Поддержка кастомных настроек квиза (таймер, shuffle) — создаём с дефолтами

## Stack

```text
Python 3.10+
telethon
pydantic >= 2
python-dotenv
```

`requirements.txt`:
```
telethon
pydantic
python-dotenv
```

## File layout

```text
Quizbot/
├── main.py               # CLI entry point
├── config.py             # env vars + константы (delays, timeouts, BOT_USERNAME)
├── models.py             # pydantic-модель Question
├── parser.py             # load_json(path) → list[Question]
├── validator.py          # бизнес-проверки сверх pydantic
├── quizbot_client.py     # Telethon-обёртка: connect, send, wait_reply, click_button
├── flow.py               # Высокоуровневый сценарий: create_quiz, upload_question, finish
├── questions.json        # данные (gitignored), есть questions.example.json
├── .env.example          # шаблон, .env в .gitignore
├── .gitignore
├── requirements.txt
├── README.md             # setup (api_id, .env, запуск)
└── docs/superpowers/specs/
    └── 2026-05-20-quizbot-uploader-design.md
```

Принцип: **`quizbot_client.py` не знает про вопросы**, оперирует
сообщениями и кнопками. **`flow.py` не знает про Telethon API**, оперирует
методами клиента. Когда @QuizBot поменяет UI, чинить только `flow.py`.

## JSON-формат

```json
[
  {
    "question": "Кто был одним из основателей Казахского ханства?",
    "options": ["Керей", "Абылай хан", "Тауке хан", "Кенесары хан"],
    "correct": 1,
    "explanation": "Керей и Жанибек считаются основателями Казахского ханства."
  }
]
```

| Поле | Тип | Правила |
|---|---|---|
| `question` | str | 1–300 символов |
| `options` | list[str] | 2–10 элементов, каждый 1–100 символов, без дублей |
| `correct` | int | 1..len(options) (1-индекс) |
| `explanation` | str (optional) | 0–200 символов |

## Pydantic-модель

```python
# models.py
from pydantic import BaseModel, Field, field_validator

class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)
    correct: int = Field(ge=1)
    explanation: str = Field(default="", max_length=200)

    @field_validator("options")
    @classmethod
    def options_unique_and_bounded(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("options must be unique")
        for opt in v:
            if not (1 <= len(opt) <= 100):
                raise ValueError(f"option length out of range: {opt!r}")
        return v

    @field_validator("correct")
    @classmethod
    def correct_in_range(cls, v, info):
        opts = info.data.get("options")
        if opts and not (1 <= v <= len(opts)):
            raise ValueError(f"correct={v} out of range 1..{len(opts)}")
        return v
```

## Config

```python
# config.py
import os
import random
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")
SESSION_NAME = "quizbot_session"

BOT_USERNAME = "QuizBot"

# Консервативные задержки под ЛИЧНЫЙ аккаунт.
DELAY_BETWEEN_MESSAGES = (3.0, 6.0)        # рандом сек между любыми двумя send
DELAY_BETWEEN_QUESTIONS = (20.0, 40.0)     # рандом сек между завершением одного вопроса и началом следующего
LONG_PAUSE_EVERY_N_QUESTIONS = 10           # после каждых 10 вопросов
LONG_PAUSE_DURATION = (60.0, 120.0)        # секунд

WAIT_REPLY_TIMEOUT = 15.0                   # ждём ответ бота
MAX_RETRIES_ON_FLOOD = 3

def rand_delay(rng: tuple[float, float]) -> float:
    return random.uniform(*rng)
```

## State-машина: подход

**Script-driven**, не event-driven. Каждый шаг:

```
send → wait_reply(timeout) → assert_pattern(reply) → next
```

Pattern-матчинг основан на **таблице `BOT_PROMPTS`** в `flow.py`, заполненной
по результатам ручного probe-прогона (см. секцию "Probe step").

Inline-кнопки жмём через `await reply_message.click(text=...)` или
`reply_message.click(index)`. Telethon это поддерживает нативно.

## Probe step (обязателен ДО написания `flow.py`)

Прежде чем кодить `flow.py`, нужно один раз пройти создание квиза вручную в
@QuizBot с включённым логированием Telethon на DEBUG, и записать:

1. Точный текст приветствия @QuizBot после `/start`
2. Подпись кнопки "создать квиз" (RU/EN зависит от языка аккаунта)
3. Точный prompt-текст после нажатия "создать"
4. Формат, в котором бот принимает варианты ответа (одно сообщение / по одному)
5. Точный prompt-текст и подписи кнопок выбора правильного варианта
6. Что приходит после выбора правильного (просьба объяснения? кнопка skip?)
7. Команду или кнопку завершения квиза
8. Финальное сообщение со share-link

Результат пишется в `docs/probe-log.md` и переносится в константы `BOT_PROMPTS`
в `flow.py`. Это самая хрупкая часть проекта — @QuizBot меняет UI без анонсов.

## Flow (псевдо-код, без точных текстов до probe)

```python
# flow.py (skeleton)
BOT_PROMPTS = {
    "start_menu_create": "...",          # заполнится после probe
    "ask_quiz_name": "...",
    "ask_question_text": "...",
    "ask_option": "...",
    "ask_correct": "...",
    "ask_explanation": "...",
    "ask_next_or_done": "...",
    "finished": "...",
}

async def create_quiz(client, quiz_name: str):
    await client.send_text("/start")
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["start_menu_create"])
    await client.click(reply, text="Create a new quiz")  # точный текст из probe

    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_quiz_name"])
    await client.send_text(quiz_name)

async def upload_question(client, q: Question, index: int):
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_question_text"])
    await client.send_text(q.question)

    for opt in q.options:
        reply = await client.wait_reply()
        assert_contains(reply.text, BOT_PROMPTS["ask_option"])
        await client.send_text(opt)

    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_correct"])
    await reply.click(q.correct - 1)  # 0-индексная кнопка

    reply = await client.wait_reply()
    if q.explanation:
        await client.send_text(q.explanation)
    else:
        await reply.click(text="Skip")  # точный текст из probe

    # Пауза между вопросами
    await asyncio.sleep(rand_delay(DELAY_BETWEEN_QUESTIONS))
    if index > 0 and index % LONG_PAUSE_EVERY_N_QUESTIONS == 0:
        await asyncio.sleep(rand_delay(LONG_PAUSE_DURATION))

async def finish_quiz(client) -> str:
    await client.send_text("/done")
    reply = await client.wait_reply()
    # извлечь share-link
    return extract_share_link(reply)
```

## Error handling (MVP)

| Тип | Реакция |
|---|---|
| JSON / pydantic ошибка | abort до коннекта, exit 1, печать причины |
| `FloodWaitError` | `sleep(e.seconds + 2)`, ретрай шага один раз (до MAX_RETRIES_ON_FLOOD) |
| Timeout ожидания ответа бота | dump последних 5 сообщений из чата с ботом, exit 2 |
| Неожиданный текст/кнопка | то же, что timeout — abort с указанием, какой prompt ожидался |
| Сетевая ошибка Telethon | один retry, потом abort |

**Никакого resume.** Упал → исправил → удалил черновик в @QuizBot вручную → перезапустил.

## Logging

```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("quizbot_uploader.log", encoding="utf-8"),
    ],
)
```

`--debug` флаг включает DEBUG (содержимое сообщений бота тоже).

## Security / account safety

- `.env` и `*.session` — в `.gitignore` (это фактические credentials)
- `.env.example` коммитим
- Session-файл = доступ к аккаунту, обращаться как с приватным ключом
- Все задержки рандомизированы через `random.uniform`
- Поведение: 1 сообщение каждые 3–6 сек, 1 вопрос каждые ~25–50 сек,
  длинная пауза каждые 10 вопросов

## CLI

```bash
python main.py --file questions.json --name "Test Quiz" [--debug]
```

Аргументы:
- `--file` (required) — путь к JSON
- `--name` (required) — название квиза
- `--debug` (optional) — DEBUG-логирование

На первом запуске Telethon спросит код подтверждения из Telegram → сохранит
сессию → дальше запускается без интерактива.

## Definition of Done

```
✅ python main.py --file questions.json --name "..."
   создаёт квиз в @QuizBot и печатает share-link
✅ pydantic ловит структурные ошибки JSON до коннекта
✅ probe-log.md содержит точные тексты бота и подписи кнопок
✅ задержки соответствуют DELAY_* константам
✅ при падении — осмысленная диагностика, не сырой traceback
✅ .env и .session не попадают в git
✅ README содержит инструкции по получению api_id и запуску
```

## Open risks

1. **@QuizBot может изменить UI** — митigation: probe-log + изоляция текстов в `BOT_PROMPTS`
2. **Anti-spam на личном аккаунте** — митигация: консервативные задержки + рандомизация
3. **Telethon login на новом устройстве** — может потребоваться 2FA-пароль; README должен это упомянуть
4. **@QuizBot принимает опции одним сообщением или по одному?** — узнаём на probe-шаге, на этом и строим
