# QuizBot Uploader

Telethon-userbot для автоматической заливки вопросов в Telegram-квиз через **@QuizBot**.
Работает от твоего личного аккаунта (не Bot API), пишет с консервативной скоростью,
чтобы не получить anti-spam от Telegram.

## Setup

### 1. Получить API credentials

1. Открыть https://my.telegram.org → войти по номеру → **API development tools**
2. Создать приложение (любые название/описание)
3. Скопировать `api_id` и `api_hash` — они вводятся в веб-платформе при создании Telegram-профиля.

### 2. Установка

```bash
git clone <repo>
cd Quizbot
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r backend/requirements.txt
```

### 3. Конфигурация

```bash
copy backend\.env.example backend\.env          # Windows
# cp backend/.env.example backend/.env          # Linux/Mac
```

`backend/.env` нужен только для опциональных сервисов вроде DeepSeek/OpenAI.
Telegram-данные входа (`api_id`, `api_hash`, телефон) вводятся в разделе
`Аккаунты` веб-платформы и не читаются из `.env`.

### 4. Первый запуск платформы

```bash
python -m backend.studio_api
```

После запуска backend открой веб-интерфейс, перейди в `Аккаунты`, создай профиль
и введи код Telegram в форме платформы. Session-файл будет создан внутри
`data/runtime/accounts/sessions/`.

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

- `correct` — индекс правильного ответа, считая **с 1**; для multi-answer poll можно указать список, например `[1, 4]`
- `options` — от 2 до 10 вариантов, без дублей
- `explanation` — опциональный, до 200 символов

### Запуск

```bash
python -m backend.main --file questions.json --name "Название квиза"
```

После успешной заливки в логе появится share-link квиза.

### Флаги

- `--debug` — подробное логирование (тексты сообщений целиком, события Telethon)

## Что делать если упало

| Exit code | Причина | Действие |
|---|---|---|
| 1 | Невалидный JSON / config | Прочитай ERROR-сообщение, исправь файл |
| 2 | Бот ответил не тем, что ждали | UI @QuizBot мог поменяться. Перезапусти `python -m backend.probe`, обнови `backend/flow.py::BOT_PROMPTS` |
| 3 | Таймаут ответа бота | Сеть / anti-spam. Подожди 10-15 минут, перезапусти |
| 130 | Ctrl+C | Удали недозаписанный квиз в @QuizBot вручную и перезапусти |

## Скорость

По умолчанию:
- 3–6 сек между любыми сообщениями
- 20–40 сек между вопросами
- Дополнительная пауза 60–120 сек каждые 10 вопросов

Это медленно — 20 вопросов займут ~8-12 минут. Так и задумано: live-аккаунт не должен
выглядеть как бот.

Менять — в `backend/config.py`.

## Безопасность

- `backend/.env` и `*.session` файлы НЕ коммитить (уже в `.gitignore`)
- Telegram API ID/API Hash/телефон не хранить в `.env`; добавлять их через платформу.
- Session-файл = доступ к твоему Telegram-аккаунту, обращаться как с приватным ключом
- При утечке session — отозвать сессию в Telegram → Settings → Devices

## Структура

```
.
├── backend/          # Python API, CLI uploader, parsers, normalizer
├── frontend/         # React/Vite Studio UI
├── data/             # Runtime data: sources, media, quizzes, session/logs
├── scripts/          # Local launch helpers
├── tests/            # Pytest suite
├── docs/             # Project docs and runbooks
├── artifacts/        # Built zip artifacts
└── README.md
```

## GPT normalizer

`backend/gpt_normalizer.py` takes extended v2 pipeline output and produces QuizBot-ready clean questions plus a manual review file.

Input:
- `data/questions_v2.json`

Outputs:
- `clean_questions.json`
- `review_questions.json`
- `normalizer_report.json`

Environment:

```bash
OPENAI_API_KEY=replace_me
OPENAI_MODEL=gpt-4.1-mini
```

Smoke run:

```bash
python -m backend.gpt_normalizer --input data/questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json --limit 5
```

Media/vision run:

```bash
python -m backend.gpt_normalizer --input data/questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json --limit 5 --image-detail high --media-max-side 1024 --media-jpeg-quality 3
```

For media questions, local image paths from `data/media` are converted to base64 data URLs and sent to the OpenAI Responses API as `input_image`. If an image is larger than `--media-max-side`, `ffmpeg` resizes it to JPEG before sending. Remote `http`/`https` image URLs are passed through directly.

Full run:

```bash
python -m backend.gpt_normalizer --input data/questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json
```

The normalizer does not upload anything to Telegram. Review `review_questions.json` before using clean output for upload. If `weak_distractors` appears during retries, the follow-up prompt tells GPT to discard source options and regenerate short options without ellipses.

## Editable generation workflow

Generate one editable quiz JSON from an existing full v2 source:

```powershell
python -m backend.generate_editable_quiz --source data\.normalizer_tmp\quote_fix_questions_v2.json --group "19 мая УТРО" --output 19_morning_openai_v2.json --model gpt-5.4-mini --max-retries 3 --media-root data --style-examples 5
```

Generate editable JSON files for every parsed date/section group:

```powershell
python -m backend.generate_editable_quiz --source data/questions_v2.json --all-groups --output-dir data/quizzes --model gpt-5.4-mini --max-retries 3 --media-root data --style-examples 5
```

Then manually edit `19_morning_openai_v2.json`.

Validate before upload:

```powershell
python -m backend.validate_quiz_json --file 19_morning_openai_v2.json
```

Upload after edits:

```powershell
python -m backend.main --speed fast --file 19_morning_openai_v2.json --name "19 мая УТРО"
```

## QuizBot Studio

Local web UI for the same pipeline:

```powershell
cd C:\Users\Asus\Documents\Agentic\Quizbot
python -m backend.studio_api
```

Open:

```text
http://127.0.0.1:8000
```

Frontend source lives in `frontend/`. API endpoints are served by `backend/studio_api.py`; live task status comes from `backend/studio_jobs.py`; JSON group load/save comes from `backend/studio_storage.py`.
