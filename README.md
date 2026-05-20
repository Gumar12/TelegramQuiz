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

## GPT normalizer

`gpt_normalizer.py` takes extended v2 pipeline output and produces QuizBot-ready clean questions plus a manual review file.

Input:
- `questions_v2.json`

Outputs:
- `clean_questions.json`
- `review_questions.json`
- `normalizer_report.json`

Environment:

```bash
OPENAI_API_KEY=sk-your_openai_key_here
OPENAI_MODEL=gpt-4.1-mini
```

Smoke run:

```bash
python gpt_normalizer.py --input questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json --limit 5
```

Full run:

```bash
python gpt_normalizer.py --input questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json
```

The normalizer does not upload anything to Telegram. Review `review_questions.json` before using clean output for upload.
