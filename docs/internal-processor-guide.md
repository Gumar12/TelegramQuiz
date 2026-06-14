# Внутренний процессор QuizBot

Этот документ описывает рабочий пайплайн проекта: какие команды есть, какие флаги доступны, какой JSON ожидается, где находится промпт нормализатора и что реально делает валидатор.

## 0. Основные функции

Если нужно просто пользоваться проектом, начинай с этого раздела. Остальные разделы ниже - подробный справочник.

### Главный рабочий сценарий

1. DOCX превращается в большой технический JSON:

```powershell
python -m backend.docx_to_quiz_json_v2 --input data/11111_dedup.docx --output data/questions_v2.json --media-dir data/media --show-groups
```

Результат: `data/questions_v2.json` и папка `media/`. Это еще не файл для загрузки. Это сырой v2-источник, где видно все найденные группы, вопросы, контексты и картинки.

2. Из v2 JSON создаются отдельные готовые квизы по всем группам:

```powershell
python -m backend.generate_editable_quiz --source data/questions_v2.json --all-groups --output-dir data/quizzes --model gpt-4.1-mini --media-root data --style-examples 5
```

Результат: папка `quizzes/`, где каждая дата/секция лежит отдельным JSON:

```text
quizzes/
  10_мая.json
  11_мая_УТРО.json
  11_мая_ОБЕД.json
```

3. Перед загрузкой проверяется нужный файл:

```powershell
python -m backend.validate_quiz_json --file data\quizzes\19_мая_УТРО.json --strict
```

4. Потом этот файл загружается в `@QuizBot`:

```powershell
python -m backend.main --speed fast --file data\quizzes\19_мая_УТРО.json --name "19 мая УТРО"
```

По умолчанию контекст и фото отправляются один раз для подряд идущих вопросов с одинаковым контекстом. Повторять контекст перед каждым вопросом не нужно.

### Если нужна только одна группа

```powershell
python -m backend.generate_editable_quiz --source data/questions_v2.json --group "19 мая УТРО" --output 19_morning_openai_v2.json --model gpt-4.1-mini --media-root data --style-examples 5
```

После этого:

```powershell
python -m backend.validate_quiz_json --file 19_morning_openai_v2.json --strict
python -m backend.main --speed fast --file 19_morning_openai_v2.json --name "19 мая УТРО"
```

### Если нужно сразу из DOCX без отдельного ручного v2-шага

```powershell
python -m backend.generate_editable_quiz --docx data/11111_dedup.docx --all-groups --output-dir data/quizzes --model gpt-4.1-mini --media-root data --style-examples 5
```

Это удобно, но для контроля лучше сначала делать `data/questions_v2.json` отдельной командой и смотреть `--show-groups`.

### Что за файлы создаются

| Файл | Для чего нужен | Загружать в QuizBot |
|---|---|---|
| `data/questions_v2.json` | Сырой результат DOCX-парсера. Нужен для просмотра и нормализации. | Нет |
| `data/quizzes\<group>.json` | Готовый clean/upload JSON для конкретной группы. | Да |
| `data/quizzes\<group>_review.json` | Вопросы, которые GPT или локальная проверка не смогли надежно привести в порядок. | Нет |
| `data/quizzes\<group>_report.json` | Отчет: сколько вопросов обработано, сколько ушло в review, какие ошибки. | Нет |
| `.normalizer_tmp\groups\<group>_source.json` | Временный v2-кусок одной группы для отладки. | Нет |

### Настройки, которые чаще всего трогать

| Настройка | Где | Что делает |
|---|---|---|
| `--all-groups` | `generate_editable_quiz.py` | Создать отдельный JSON для каждой найденной группы. |
| `--group "19 мая УТРО"` | `generate_editable_quiz.py` | Создать JSON только для одной группы. |
| `--output-dir data/quizzes` | `generate_editable_quiz.py` | Папка, куда складывать все готовые квизы. |
| `--model gpt-4.1-mini` | `generate_editable_quiz.py`, `gpt_normalizer.py` | OpenAI-модель для нормализации. |
| `--media-root data` | `generate_editable_quiz.py`, `gpt_normalizer.py` | Откуда искать картинки из `media`. |
| `--style-examples 5` | `generate_editable_quiz.py`, `gpt_normalizer.py` | Сколько хороших примеров вариантов ответа давать GPT как стиль. |
| `--max-retries 3` | `generate_editable_quiz.py`, `gpt_normalizer.py` | Сколько раз GPT пробует исправить один вопрос. |
| `--strict` | `validate_quiz_json.py` | Считать warnings ошибкой проверки. |
| `--speed fast` | `main.py` | Быстрее грузить в Telegram для демо/рабочих прогонов. |
| `--context-send-mode once` | `main.py` | Отправлять одинаковый контекст/фото один раз. Это default. |
| `--context-send-mode per-question` | `main.py` | Повторять контекст/фото перед каждым вопросом. Обычно не нужно. |
| `--no-shuffle-options` | `main.py` | Не перемешивать варианты перед загрузкой. |

### Как оформлять DOCX

Минимально надежная структура:

```text
19 мая
УТРО

Контекст Nº1
Текст контекста. Он будет относиться к следующим вопросам до нового контекста, даты или секции.

Кто возглавил восстание?
Сырым Датов

Какой документ был принят в 1822 году?
Устав о сибирских киргизах
```

Вопрос с готовыми вариантами:

```text
Кто возглавил восстание?
A) Сырым Датов
B) Кенесары Касымов
C) Абылай хан
D) Тауке хан
```

Правильный вариант в DOCX выделяй жирным. Парсер не определяет правильный вариант семантически, он смотрит на bold.

Картинка относится к контексту, если вставлена после строки `Контекст...` и до вопросов. Картинка относится к одному вопросу, если вставлена сразу после этого вопроса.

## 1. Общая схема

Есть четыре основных этапа:

1. `docx_to_quiz_json_v2.py` - превращает DOCX в расширенный `data/questions_v2.json`.
2. `gpt_normalizer.py` или `generate_editable_quiz.py` - приводит сырой v2 JSON к редактируемому QuizBot JSON. Здесь используется OpenAI.
3. `validate_quiz_json.py` - локально проверяет готовый JSON перед загрузкой. Это обычный Python-скрипт, не нейросеть.
4. `main.py` - загружает готовые вопросы в Telegram через `@QuizBot`.

Быстрый типовой поток для одной группы:

```powershell
python -m backend.docx_to_quiz_json_v2 --input data/11111_dedup.docx --output data/questions_v2.json --media-dir data/media --show-groups

python -m backend.generate_editable_quiz --source data/questions_v2.json --group "19 мая УТРО" --output 19_morning_openai_v2.json --model gpt-4.1-mini --media-root data --style-examples 5

python -m backend.validate_quiz_json --file 19_morning_openai_v2.json --strict

python -m backend.main --speed fast --file 19_morning_openai_v2.json --name "19 мая УТРО"
```

Быстрый поток для всех групп сразу:

```powershell
python -m backend.docx_to_quiz_json_v2 --input data/11111_dedup.docx --output data/questions_v2.json --media-dir data/media --show-groups

python -m backend.generate_editable_quiz --source data/questions_v2.json --all-groups --output-dir data/quizzes --model gpt-4.1-mini --media-root data --style-examples 5
```

После этого в папке `quizzes/` будут отдельные файлы по группам, например:

```text
quizzes/
  10_мая.json
  11_мая_УТРО.json
  11_мая_ОБЕД.json
  19_мая_УТРО.json
```

## 2. Что делает валидатор

Валидатор состоит из нескольких слоев.

`parser.py` читает файл. Он принимает два варианта верхнего уровня:

```json
[
  { "question": "...", "options": ["..."], "correct": 1 }
]
```

или:

```json
{
  "questions": [
    { "question": "...", "options": ["..."], "correct": 1 }
  ]
}
```

`models.py` проверяет один вопрос через Pydantic:

- `question`: 1-300 символов.
- `options`: 2-10 вариантов.
- каждый option: 1-100 символов.
- варианты должны быть уникальными.
- `correct`: индекс правильного ответа с 1, либо список индексов для multi-answer.
- `explanation`: до 200 символов.
- `context_title`, `context`, `media`: необязательные поля.

`validator.py` проверяет список целиком:

- нет полностью одинакового текста вопроса после `strip().lower()`;
- максимум 100 вопросов в одном квизе.

`validate_quiz_json.py` добавляет quality report:

- считает количество вопросов, вопросов с контекстом, вопросов с media, multi-answer;
- считает распределение правильных ответов по позициям;
- предупреждает о слишком коротком контексте;
- предупреждает об обрезанных вариантах с `...` или `…`;
- предупреждает о похожих вариантах ответа через `difflib.SequenceMatcher`;
- если похожесть двух вариантов `>= 0.9`, появляется warning `similar_options`.

Важно: `validate_quiz_json.py` не использует OpenAI и не понимает смысл вопроса. Он не ищет семантические дубли вроде "Кто основал..." и "Основателем был кто...". Дубли вопросов проверяются только как одинаковый текст. Похожие ответы проверяются эвристикой по строкам, не нейросетью.

Запуск:

```powershell
python -m backend.validate_quiz_json --file quiz.json
```

Строгий режим:

```powershell
python -m backend.validate_quiz_json --file quiz.json --strict
```

`--strict` возвращает exit code `2`, если есть warnings.

## 3. Где используется нейросеть

Нейросеть используется в `gpt_normalizer.py` и через обертку `generate_editable_quiz.py`.

Главные места:

- `gpt_normalizer.py::SYSTEM_PROMPT` - системный промпт.
- `gpt_normalizer.py::build_messages()` - user payload, правила генерации вариантов, style examples, input item, repair instructions.
- `gpt_normalizer.py::build_response_schema()` - строгая JSON-схема ответа модели.
- `gpt_normalizer.py::call_openai_normalizer()` - вызов OpenAI Responses API.

Нормализатор отправляет модели:

- исходный `RawQuestion`;
- текстовый контекст;
- пути media, подготовленные как `input_image`, если это локальная картинка или URL;
- style examples, если включены;
- предыдущую ошибку, если это retry.

Если у вопроса `distractors_source = "heuristic_same_document"`, исходные неправильные варианты считаются недоверенными. В retry при `weak_distractors` промпт говорит модели не использовать старые неправильные варианты и сгенерировать три новых правдоподобных, но неверных варианта.

Если исходный вопрос уже имеет надежные варианты из документа (`source_document_bold` или `source_document_answer_indexes`), нормализатор может вообще не вызывать GPT для этого вопроса: он валидирует и перемешивает варианты локально.

## 4. Как генерируются похожие неправильные ответы

Есть два механизма.

Первый - локальный эвристический генератор в `docx_to_quiz_json_v2.py`. Функция `contextual_distractors()` работает как обычный код:

- для веков генерирует соседние века;
- для годов генерирует соседние годы;
- для известных ключевых слов использует захардкоженные наборы вариантов;
- для портретов подставляет похожие типы ответов: исторические личности;
- если не смогла сделать 3 варианта, ставит `type = "needs_distractor_review"` и `distractors_source = "needs_contextual_distractors"`.

Второй - GPT-нормализация в `gpt_normalizer.py`. Там модель получает правило:

- делать неправильные варианты того же смыслового типа: человек/человек, дата/дата, место/место, событие/событие;
- держать варианты близкими по длине, грамматической форме и конкретности;
- не использовать многоточия;
- не добавлять факты вне исходного элемента;
- если ответ нельзя вывести из контекста или картинки, вернуть `quality_flags = ["needs_visual_review"]`.

## 5. JSON для загрузки в QuizBot

Это формат, который можно подавать в `main.py` и `validate_quiz_json.py`.

Минимальный вариант:

```json
[
  {
    "question": "Кто возглавил национально-освободительное движение казахов Младшего жуза?",
    "options": [
      "Сырым Датов",
      "Кенесары Касымов",
      "Жанкожа Нурмухамедулы",
      "Есет Котибарулы"
    ],
    "correct": 1,
    "explanation": "Движение против колониальной политики возглавил батыр Сырым Датов."
  }
]
```

С текстовым контекстом:

```json
{
  "quiz_title": "19 мая УТРО",
  "format_version": "2.1-clean",
  "questions": [
    {
      "source_item_id": 17,
      "date": "19 мая",
      "section": "УТРО",
      "context_title": "Контекст Nº2",
      "context": "На иллюстрации и в описании говорится о правителе XIV века.",
      "media": [],
      "question": "О ком идет речь?",
      "options": ["Эмир Тимур", "Абылай хан", "Тауке хан", "Кенесары хан"],
      "correct": 1,
      "explanation": "В контексте описан Эмир Тимур."
    }
  ]
}
```

С фото:

```json
{
  "quiz_title": "11 мая УТРО",
  "questions": [
    {
      "context_title": "Контекст Nº2",
      "context": "Посмотри на портрет и используй описание рядом с ним.",
      "media": ["media/image_001.jpg"],
      "question": "На портрете изображен:",
      "options": ["Эмир Тимур", "Чингисхан", "Абылай хан", "Тауке хан"],
      "correct": 1,
      "explanation": "На портрете изображен Эмир Тимур."
    }
  ]
}
```

Правила для upload JSON:

- `correct` всегда считается с 1, не с 0.
- Для нескольких правильных ответов можно указать список: `"correct": [1, 4]`.
- `media` - список путей к локальным файлам. При загрузке сейчас реально используется первый файл из списка.
- `context_title` и `context` отправляются перед poll-сообщением, а не внутрь самого poll.
- Если есть media, контекст идет caption к медиа. Длинный caption обрезается до лимита Telegram.
- Лишние поля вроде `source_item_id`, `date`, `section`, `type`, `source`, `quality_flags` не нужны для загрузки, но обычно не мешают.

## 6. Расширенный v2 JSON

Это промежуточный формат после DOCX-парсера и до GPT-нормализации. Он богаче, чем upload JSON.

```json
{
  "quiz_title": "История Казахстана",
  "quiz_description": "Тест по истории Казахстана",
  "format_version": "2.0",
  "telegram_limits": {
    "poll_question_max_chars": 300,
    "option_max_chars": 100,
    "explanation_max_chars": 200,
    "note": "Long context/images should be sent before the poll or stored in explanation_full."
  },
  "report": {
    "blocks_total": 648,
    "items_total": 229,
    "items_with_media": 38,
    "items_needs_review": 88,
    "items_with_long_explanation": 1
  },
  "questions": [
    {
      "id": 1,
      "date": "10 мая",
      "section": "УТРО",
      "context_title": "",
      "context": "",
      "media": [],
      "question": "Текст вопроса?",
      "correct_answer": "Правильный ответ",
      "correct_answers": [],
      "options": ["Правильный ответ", "Вариант 2", "Вариант 3", "Вариант 4"],
      "correct": 1,
      "explanation": "Короткое объяснение до 200 символов.",
      "explanation_full": "Полное объяснение, может быть длиннее.",
      "type": "simple_quiz",
      "source": "docx_v2",
      "distractors_source": "heuristic_same_document"
    }
  ]
}
```

Значения `type`, которые встречаются в пайплайне:

- `simple_quiz` - обычный вопрос.
- `multiple_choice` - вопрос с готовыми вариантами.
- `media_context_quiz` - вопрос зависит от картинки.
- `short_answer_with_explanation` - вопрос с коротким ответом и объяснением.
- `needs_distractor_review` - не удалось надежно сделать варианты ответов.

`distractors_source` показывает происхождение вариантов:

- `heuristic_same_document` - варианты сгенерированы локальной эвристикой из документа.
- `needs_contextual_distractors` - вариантов не хватает, нужен GPT или ручная правка.
- `source_document_bold` / `source_document_answer_indexes` - варианты считаются надежными, потому что пришли из документа.

## 7. Команды и флаги

### `main.py` - загрузка в Telegram

```powershell
python -m backend.main --file quiz.json --name "Название квиза"
```

Флаги:

- `--file` - путь к готовому upload JSON. Обязательный.
- `--name` - название квиза в `@QuizBot`. Обязательный.
- `--context-send-mode once` - если подряд идут вопросы с одинаковым контекстом/фото, отправить контекст только один раз. Это default.
- `--context-send-mode per-question` - принудительно отправлять контекст/фото перед каждым вопросом. Используй только если специально нужен повтор.
- `--no-shuffle-options` - не перемешивать варианты перед загрузкой.
- `--speed normal` - обычные безопасные задержки.
- `--speed fast` - ускоренный режим для демо/видео.
- `--debug` - подробный лог.

### `validate_quiz_json.py` - проверка готового JSON

```powershell
python -m backend.validate_quiz_json --file quiz.json --strict
```

Флаги:

- `--file` - проверяемый JSON. Обязательный.
- `--strict` - вернуть exit code `2`, если есть warnings.

### `gpt_normalizer.py` - GPT-нормализация v2 JSON

```powershell
python -m backend.gpt_normalizer --input data/questions_v2.json --output clean.json --review review.json --report report.json --model gpt-4.1-mini
```

Флаги:

- `--input` - исходный v2 JSON. Обязательный.
- `--output` - clean JSON для ручной правки и загрузки. Обязательный.
- `--review` - JSON с вопросами, которые надо проверить вручную. Обязательный.
- `--report` - отчет нормализации. Обязательный.
- `--model` - модель OpenAI. Если не указан, берется `OPENAI_MODEL`.
- `--limit` - обработать только N вопросов.
- `--start-id` - начать с source item id.
- `--max-retries` - максимум попыток GPT на вопрос. Default `3`.
- `--seed` - seed для детерминированного перемешивания вариантов. Default `42`.
- `--image-detail low|auto|high` - детализация картинок для OpenAI. Default `high`.
- `--ffmpeg-path` - путь к ffmpeg.
- `--media-max-side` - уменьшать картинки, если длинная сторона больше этого значения. Default `1024`.
- `--media-jpeg-quality` - ffmpeg `q:v` для JPEG. Default `3`.
- `--media-root` - корень для поиска media по относительным путям.
- `--style-source` - отдельный v2 JSON, откуда брать style examples.
- `--style-examples` - сколько style examples класть в prompt. Default `5`.
- `--dry-run` - напечатать report, не писать output/review/report.

Нужны env-переменные:

```powershell
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
```

### `generate_editable_quiz.py` - удобная генерация одного блока или всех групп

```powershell
python -m backend.generate_editable_quiz --source data/questions_v2.json --group "19 мая УТРО" --output 19_morning_openai_v2.json --model gpt-4.1-mini --media-root data
```

Все группы сразу:

```powershell
python -m backend.generate_editable_quiz --source data/questions_v2.json --all-groups --output-dir data/quizzes --model gpt-4.1-mini --media-root data
```

Можно сразу из DOCX:

```powershell
python -m backend.generate_editable_quiz --docx data/11111_dedup.docx --all-groups --output-dir data/quizzes --model gpt-4.1-mini --media-root data
```

Флаги:

- `--source` - готовый полный v2 JSON.
- `--docx` - DOCX, который надо сначала распарсить.
- `--group` - группа вида `"19 мая УТРО"`. Используется для режима одной группы.
- `--all-groups` - найти все группы в source/DOCX и создать отдельный editable JSON на каждую.
- `--output` - итоговый editable clean JSON. Обязательный только вместе с `--group`.
- `--output-dir` - папка для JSON-файлов при `--all-groups`. Default `data/quizzes`.
- `--review` - путь review JSON. Если не указан, создается рядом с output.
- `--report` - путь report JSON. Если не указан, создается рядом с output.
- `--workdir` - рабочая папка. Default `.normalizer_tmp`.
- `--model` - модель OpenAI.
- `--max-retries` - максимум GPT-попыток на вопрос. Default `3`.
- `--seed` - seed перемешивания. Default `42`.
- `--media-root` - корень media. Default `data`.
- `--style-source` - источник style examples.
- `--style-examples` - количество style examples. Default `5`.
- `--image-detail low|auto|high` - детализация картинок. Default `high`.
- `--dry-run` - прогон без записи файлов.

`--source` и `--docx` взаимоисключающие: нужно выбрать одно.

`--group` и `--all-groups` тоже взаимоисключающие: либо делаешь один файл, либо всю папку.

В `--all-groups` имена файлов строятся из названия группы:

- `"10 мая"` -> `10_мая.json`
- `"11 мая УТРО"` -> `11_мая_УТРО.json`
- `"19 мая ОБЕД"` -> `19_мая_ОБЕД.json`

Для каждой группы рядом создаются sidecar-файлы:

- `<group>_review.json` - вопросы, которые GPT не смог надежно привести к clean-виду;
- `<group>_report.json` - отчет нормализации;
- в `workdir/groups/` - временный `<group>_source.json`, то есть v2-кусок только этой группы.

### `docx_to_quiz_json_v2.py` - DOCX в v2 JSON

```powershell
python -m backend.docx_to_quiz_json_v2 --input source.docx --output data/questions_v2.json --media-dir data/media --show-groups
```

Флаги:

- `--input` - входной DOCX. Обязательный.
- `--output` - output JSON. Default `data/questions_v2.json`.
- `--media-dir` - куда сохранить извлеченные картинки. Default `data/media`.
- `--title` - `quiz_title`. Default `История Казахстана`.
- `--description` - `quiz_description`. Default `Тест по истории Казахстана`.
- `--show-groups` - вывести найденные группы и количество вопросов.

### `export_quiz_group.py` - выгрузка одной группы

```powershell
python -m backend.export_quiz_group --source data/questions_v2.json --group "19 мая ОБЕД" --output lunch.json
```

Флаги:

- `--source` - расширенный v2 JSON.
- `--group` - группа по `date + section`.
- `--output` - файл для выгрузки.

### `prepare_context_source.py` - ручное наследование context/media

```powershell
python -m backend.prepare_context_source --source data/questions_v2.json --group "19 мая ОБЕД" --output focused.json --inherit-media-after-id 17 --inherit-media-until-id 25 --context "Общий контекст..."
```

Флаги:

- `--source` - исходный v2 JSON.
- `--group` - группа.
- `--output` - output JSON.
- `--inherit-media-after-id` - начало диапазона наследования media.
- `--inherit-media-until-id` - конец диапазона наследования media.
- `--context` - текст контекста, который подставить в диапазоне, если его нет.

## 8. Как upload реально работает внутри

`main.py` делает:

1. читает JSON через `parser.load_json()`;
2. валидирует через `validate_all()`;
3. проверяет `backend/.env` с Telegram credentials;
4. создает квиз в `@QuizBot`;
5. по одному загружает вопросы;
6. завершает квиз и достает share link.

Для каждого вопроса:

1. Если есть `context_title`, `context` или `media`, сначала отправляется prelude-сообщение.
2. Если есть `media`, отправляется первый файл из `media` с caption из `context_title + context`.
3. Если media нет, но есть context, отправляется текстовое сообщение.
4. Потом отправляется Telegram quiz poll с `question`, `options`, `correct`, `explanation`.
5. Если `@QuizBot` просит проголосовать за правильный ответ, скрипт сам голосует через Telegram API.
6. Между вопросами ставятся задержки из `config.py`.

По умолчанию `main.py` перемешивает варианты перед загрузкой и пересчитывает правильные индексы. Если нужно сохранить порядок из JSON, используй:

```powershell
python -m backend.main --file quiz.json --name "Название" --no-shuffle-options
```

## 9. Что смотреть при ручной правке

Перед загрузкой проверь:

- нет `needs_distractor_review` в clean-файле;
- `review.json` пустой или все вопросы оттуда вручную перенесены/исправлены;
- `correct` указывает на правильный вариант после всех ручных правок;
- варианты не повторяются и не содержат обрезанные куски с `...`;
- у фото-вопросов `media` реально указывает на существующий файл;
- если несколько вопросов используют один и тот же контекст, default `--context-send-mode once` отправит его один раз перед первым вопросом этого блока.
