# GPT-нормализатор вопросов v2

**Дата:** 2026-05-20
**Статус:** одобрено для планирования
**Область:** только этап `questions_v2.json -> gpt_normalizer.py -> clean_questions.json`. DOCX-парсер v2 и загрузчик в Telegram в этой фазе не меняются.

## Цель

Добавить отдельный CLI-скрипт `gpt_normalizer.py`, который берёт уже готовый расширенный JSON из `questions_v2.json`, очищает каждый вопрос через GPT, проверяет результат локальным валидатором и пишет три выходных файла:

```text
questions_v2.json
↓
gpt_normalizer.py
↓
local validator
↓
clean_questions.json
review_questions.json
normalizer_report.json
```

Главная задача фазы — превратить грязные длинные ответы и эвристические ложные варианты из v2-архива в стабильные quiz-ready вопросы.

## Что не входит в задачу

- Не трогаем `docx_to_quiz_json_v2.py`.
- Не перепарсиваем DOCX.
- Не распаковываем `quizbot_pipeline_v2.zip` в рабочий проект как часть design-фазы.
- Не делаем автоматическую загрузку в @QuizBot.
- Не решаем полноценное распознавание изображений. Media-пути сохраняются как метаданные, но сами изображения не отправляются в GPT на этом этапе.
- Не гарантируем историческую истинность сверх предоставленного контекста. GPT должен работать только с входными данными item.

## Архитектура

`gpt_normalizer.py` — отдельный CLI-скрипт. Он не импортирует Telethon, не пишет в Telegram и не меняет исходный `questions_v2.json`.

Основной поток:

1. Прочитать `questions_v2.json`.
2. Для каждого `questions[]` item собрать GPT-запрос.
3. Получить строго JSON-ответ.
4. Прогнать результат через локальный валидатор.
5. Валидный результат записать в `clean_questions.json`.
6. Невалидный или спорный результат записать в `review_questions.json`.
7. Записать агрегированную статистику в `normalizer_report.json`.

Рекомендованный подход: один GPT-запрос на один item. Batch-обработка быстрее, но хуже для MVP: выше риск сломанного JSON, сложнее retry и сложнее понять, какой конкретно вопрос испортился.

## Входной Формат

Вход — объект v2 из `questions_v2.json`:

```json
{
  "quiz_title": "История Казахстана",
  "quiz_description": "Тест по истории Казахстана",
  "format_version": "2.0",
  "telegram_limits": {},
  "report": {},
  "questions": []
}
```

Каждый item может содержать:

```json
{
  "id": 17,
  "date": "11 мая",
  "section": "УТРО",
  "context_title": "Контекст Nº2",
  "context": "текст контекста",
  "media": ["media/image_003.png"],
  "question": "сырой вопрос",
  "correct_answer": "сырой или обрезанный правильный ответ",
  "options": ["сырой вариант 1", "сырой вариант 2", "сырой вариант 3", "сырой вариант 4"],
  "correct": 1,
  "explanation": "короткое пояснение",
  "explanation_full": "полное пояснение",
  "type": "media_context_quiz",
  "source": "docx_v2"
}
```

## Выходной Формат Clean

`clean_questions.json` сохраняет верхнеуровневые метаданные квиза и массив очищенных вопросов. Каждый clean item обязательно содержит `source_item_id`, чтобы можно было вернуться к исходному вопросу в `questions_v2.json`.

```json
{
  "quiz_title": "История Казахстана",
  "quiz_description": "Тест по истории Казахстана",
  "format_version": "2.1-clean",
  "questions": [
    {
      "source_item_id": 17,
      "date": "11 мая",
      "section": "УТРО",
      "context_title": "Контекст Nº2",
      "context": "текст контекста",
      "media": ["media/image_003.png"],
      "question": "короткий вопрос до 300 символов",
      "correct_answer": "короткий правильный ответ до 100 символов",
      "options": ["правильный", "ложный 1", "ложный 2", "ложный 3"],
      "correct": 1,
      "explanation": "короткое пояснение до 200 символов",
      "explanation_full": "полное пояснение",
      "type": "media_context_quiz",
      "source": "gpt_normalized",
      "quality_flags": []
    }
  ]
}
```

`context`, `media`, `date`, `section`, `context_title`, `type` сохраняются как метаданные для будущей загрузки или ручной проверки. Poll-ready поля — это `question`, `options`, `correct`, `explanation`.

## Выходной Формат Review

`review_questions.json` содержит всё, что не прошло локальную проверку или требует ручной оценки.

Каждый review item содержит:

```json
{
  "source_item_id": 17,
  "error_reason": "duplicate_options",
  "raw_item": {},
  "last_gpt_output": {},
  "attempts": 3,
  "notes": "Краткое техническое объяснение"
}
```

Разрешённые `error_reason`:

```text
bad_json
too_long_question
too_long_option
too_long_explanation
duplicate_options
correct_not_in_options
weak_distractors
missing_required_field
gpt_request_failed
max_retries_exceeded
needs_visual_review
```

`needs_visual_review` используется, если вопрос невозможно надёжно нормализовать без просмотра изображения. На этом этапе media передаются GPT только как пути/имена файлов, не как визуальный input.

## GPT-Нормализация

Для каждого item нормализатор отправляет в GPT:

- `question`
- `correct_answer`
- `options`
- `explanation`
- `explanation_full`
- `context`
- `context_title`
- `media`
- `type`

GPT должен вернуть строго один JSON-объект:

```json
{
  "question": "короткий вопрос до 300 символов",
  "correct_answer": "короткий правильный ответ до 100 символов",
  "options": ["правильный", "ложный 1", "ложный 2", "ложный 3"],
  "correct": 1,
  "explanation": "до 200 символов",
  "explanation_full": "полное пояснение",
  "quality_flags": []
}
```

Промпт задаёт жёсткие правила:

- Не добавлять факты вне предоставленного item.
- Не делать ложные варианты частично правильными.
- Не использовать варианты вроде "все ответы верны" или "нет правильного ответа".
- Не обрезать ответы многоточием.
- Сохранять историческую точность в рамках предоставленного контекста.
- Делать варианты одного типа и похожей длины.
- Если вопрос зависит от изображения и текстового контекста недостаточно, вернуть флаг `needs_visual_review`.

После ответа GPT локальный код может перемешать `options`, но обязан обновить `correct`. Для воспроизводимости нужен `--seed`.

## Локальный Валидатор

Локальный валидатор принимает только clean item, который проходит все правила:

```text
1 <= len(question) <= 300
len(options) == 4
каждый option: 1..100 символов
options уникальны после нормализации пробелов и регистра
correct в диапазоне 1..4
correct_answer совпадает с options[correct - 1]
len(explanation) <= 200
```

Дополнительная эвристика `weak_distractors`:

- ложный вариант равен правильному после нормализации;
- ложный вариант содержит правильный ответ как подстроку;
- правильный ответ содержит ложный вариант как подстроку, и ложный вариант не является самостоятельной датой/именем;
- вариант содержит многоточие после GPT-нормализации;
- вариант выглядит как технический fallback: `Вариант 1`, `Другое`, `Нет правильного варианта`.

Эта эвристика не доказывает историческую корректность, но ловит самые грубые ошибки.

## CLI

Базовая команда:

```bash
python gpt_normalizer.py --input questions_v2.json --output clean_questions.json --review review_questions.json --report normalizer_report.json --model "$OPENAI_MODEL" --seed 42
```

Полезные флаги:

```text
--limit 5              обработать первые 5 вопросов для smoke-test
--start-id 20          начать с исходного item id
--max-retries 3        сколько раз чинить плохой GPT-output
--seed 42              детерминированное перемешивание вариантов
--model MODEL          модель задаётся явно или через env
--dry-run              не писать итоговые файлы, только вывести report
```

API-ключ не передаётся через аргумент командной строки. Он читается из переменной окружения.

## Ошибки И Retry

Поведение:

1. Если GPT вернул битый JSON, повторить запрос с причиной `bad_json`.
2. Если JSON валиден, но не проходит локальные лимиты, повторить запрос с конкретной причиной.
3. Если после `--max-retries` результат всё ещё плохой, записать item в `review_questions.json`.
4. Если API недоступен, сохранить уже обработанный прогресс и завершиться с ненулевым exit code.
5. Уже принятые items не теряются.

Нормализатор должен писать выходные файлы атомарно: сначала во временный файл рядом с целевым, затем переименовать. Это снижает риск потерять результат при обрыве процесса.

## Отчёт

`normalizer_report.json` содержит:

```json
{
  "input": "questions_v2.json",
  "output": "clean_questions.json",
  "review": "review_questions.json",
  "model": "configured-model-name",
  "started_at": "2026-05-20T00:00:00Z",
  "finished_at": "2026-05-20T00:00:00Z",
  "items_total": 158,
  "items_clean": 140,
  "items_review": 18,
  "max_retries": 3,
  "error_reason_counts": {
    "weak_distractors": 10,
    "needs_visual_review": 8
  }
}
```

## Проверка MVP

Минимальная проверка перед продолжением:

1. Прогнать первые 5 вопросов через `--limit 5`.
2. Убедиться, что `clean_questions.json` проходит локальный валидатор.
3. Убедиться, что в clean options нет многоточий.
4. Убедиться, что каждый clean/review item содержит `source_item_id`.
5. Убедиться, что каждый review item содержит `error_reason`.
6. Вручную открыть 5 clean-вопросов и оценить качество ложных вариантов.

Telegram smoke-test не входит в эту фазу. Он начинается только после появления стабильного `clean_questions.json`.

## Telegram Limits

Локальные лимиты берутся из текущих ограничений Telegram `sendPoll`:

- question: 1-300 символов;
- option: 1-100 символов;
- explanation: 0-200 символов.

Источник: https://core.telegram.org/bots/api#sendpoll

На 2026-05-20 Bot API уже описывает media в polls/options/explanation, но текущий проект работает через Telethon-userbot и @QuizBot/native poll flow. Поэтому media в этой фазе сохраняются как метаданные и не считаются гарантированно загружаемыми в poll.

## Границы Реализации

Реализация должна сохранить существующие пользовательские изменения в `main.py` и `quizbot_client.py`. Изменения этой фазы должны быть ограничены новым нормализатором, локальной схемой/валидатором для clean output, зависимостями для GPT-клиента и документацией по запуску.
