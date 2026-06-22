# QuizBot Studio API

Актуальная документация по локальному FastAPI backend для веб-платформы QuizBot.

- Backend: `backend/studio_api.py`
- Frontend API client: `frontend/src/api.ts`
- Автоматическая документация при запущенном backend:
  - Swagger: `http://127.0.0.1:8000/docs`
  - ReDoc: `http://127.0.0.1:8000/redoc`
  - OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

Дата сверки: 2026-06-20.

## Сводка

Всего backend endpoint'ов: **37**.

Покрыто API-клиентом frontend: **37 из 37**.

Доступно из текущего UI: **34 из 37**.

Не выведены в UI напрямую:

- `GET /api/health`
- `GET /api/auth/telegram/{login_id}`
- `GET /api/runs/{run_id}`

Удалены как устаревшие/дублирующие endpoint'ы:

- `GET /api/workspace` - заменен на `GET /api/settings`.
- `DELETE /api/groups/{group_id}` - заменен на `POST /api/groups/{group_id}/delete`.
- `POST /api/jobs/parse-docx` - заменен на `POST /api/jobs/create-from-docx`.
- `POST /api/jobs/upload-queue` - очередь запусков не выведена в текущий UI и не является отдельным основным сценарием.

## Общие правила

Base URL:

- Backend-served frontend: открыть `http://127.0.0.1:8000`; frontend использует пустой base URL, запросы идут на текущий origin и CORS не нужен.
- Vite dev frontend: открыть `http://127.0.0.1:3000` или `http://localhost:3000`; frontend вызывает backend `http://127.0.0.1:8000` через явный local CORS allowlist.
- Для нестандартного dev host/port backend принимает `STUDIO_CORS_ORIGINS` как comma-separated allowlist, например `http://127.0.0.1:3000,http://localhost:3000`. Wildcard не используется.
- Локальные API-клиенты без browser `Origin` (`curl`, Python scripts, Swagger/ReDoc same-origin) продолжают работать.

Ошибки:

- Backend возвращает обычные FastAPI ошибки с `detail`.
- Frontend API client сейчас бросает `Error(text || "Request failed: <status>")`.

Фоновые задачи:

- Endpoint'ы `POST /api/jobs/*` обычно возвращают `{ "job_id": "..." }`.
- Статус читается через `GET /api/jobs/{job_id}`.
- Live-события идут через SSE `GET /api/jobs/{job_id}/events`.

## Endpoint'ы

| Endpoint | Назначение | Request | Response | Frontend client | UI |
| --- | --- | --- | --- | --- | --- |
| `GET /api/health` | Проверка, что backend живой. | Нет. | `{ ok, time }` | `api.health()` | Нет |
| `GET /api/groups` | Список quiz group summary из активной папки квизов. | Нет. | `{ groups }` | `api.getGroupSummaries()`; внутри `api.getGroups()` | Да |
| `POST /api/groups/manual` | Создать пустой квиз вручную. | JSON `CreateManualQuizRequest` | `{ group }` | `api.createManualQuiz()` | Да |
| `POST /api/groups/import-json` | Импортировать готовый quiz JSON через drag/drop или выбор файла. | `multipart/form-data`: `file`, `title`, `description`, `workspace_dir` | `{ group }` | `api.importQuizJson()` | Да |
| `GET /api/accounts` | Получить список Telegram account profiles. | Нет. | `{ accounts }` | `api.getAccounts()` | Да |
| `POST /api/accounts` | Создание профилей через browser UI отключено. | Любой body отклоняется. | `405` | `api.createAccount()` бросает локальную ошибку без network request | Нет |
| `PATCH /api/accounts/{profile_id}` | Редактирование профилей через browser UI отключено. | Любой body отклоняется. | `405` | `api.updateAccount()` бросает локальную ошибку без network request | Нет |
| `POST /api/accounts/{profile_id}/delete` | Удалить Telegram account profile и локальные session-файлы. `default` защищён от удаления. | Path `profile_id` | `{ id, deleted, active_account }` | `api.deleteAccount()` | Да |
| `POST /api/accounts/{profile_id}/enable` | Включить Telegram account profile. | Path `profile_id` | `{ account }` | `api.enableAccount()` | Да |
| `POST /api/accounts/{profile_id}/disable` | Отключить Telegram account profile; если он активный, backend выбирает следующий доступный профиль. | Path `profile_id` | `{ account }` | `api.disableAccount()` | Да |
| `GET /api/accounts/current` | Получить активный account profile. | Нет. | `{ account }` | `api.getCurrentAccount()` | Да |
| `POST /api/accounts/current` | Переключить активный account profile. | JSON `{ profile_id }` | `{ account }` | `api.setCurrentAccount()` | Да |
| `POST /api/auth/telegram/start` | Начать подключение Telegram-аккаунта. | JSON `{ profile_id }` | Telegram login state | `api.startTelegramLogin()` | Да |
| `POST /api/auth/telegram/code` | Отправить Telegram login code. | JSON `{ login_id, code }` | Telegram login state | `api.submitTelegramCode()` | Да |
| `POST /api/auth/telegram/password` | Отправить 2FA password. | JSON `{ login_id, password }` | Authorized login state | `api.submitTelegramPassword()` | Да |
| `GET /api/auth/telegram/{login_id}` | Получить статус Telegram login flow. | Path `login_id` | Telegram login state | `api.getTelegramLoginStatus()` | Нет |
| `DELETE /api/auth/telegram/{login_id}` | Отменить Telegram login flow. | Path `login_id` | `{ ok }` | `api.cancelTelegramLogin()` | Да |
| `GET /api/runs` | Список запусков и последняя история. | Нет. | `{ runs }` | `api.getRuns()` | Да |
| `GET /api/runs/active` | Текущий активный запуск. | Нет. | `{ active: false }` или run snapshot | `api.getActiveRun()` | Да |
| `GET /api/runs/{run_id}` | Получить конкретный запуск. | Path `run_id` | run snapshot | `api.getRun()` | Нет |
| `POST /api/runs/{run_id}/pause` | Поставить запуск на паузу. | Path `run_id` | run snapshot | `api.pauseRun()` | Да |
| `POST /api/runs/{run_id}/resume` | Возобновить сохранённый upload run через background job. | Path `run_id` | `{ job_id }` | `api.resumeRun()` | Да |
| `POST /api/runs/{run_id}/continue` | Продолжить upload run с указанного вопроса, включая остановленный пользователем run. | Path `run_id`; JSON `{ question_index }` | `{ job_id }` | `api.continueRun()` | Да |
| `POST /api/runs/{run_id}/stop` | Остановить сохранённый run, пометив его `cancelled`. | Path `run_id` | run snapshot | `api.stopRun()` | Да |
| `GET /api/settings` | Настройки путей backend для UI настроек. | Нет. | settings payload with `paths` | `api.getSettings()` | Да |
| `GET /api/media/{media_path:path}` | Отдать картинку/медиа только из активной media-папки. | Path `media_path` | File response | `mediaUrl()` | Да |
| `POST /api/media/upload` | Загрузить медиафайл для вопроса. | `multipart/form-data`: `file` | `{ path, filename, saved_path }` | `api.uploadMedia()` | Да |
| `GET /api/groups/{group_id}` | Загрузить полный quiz group. | Path `group_id` | `QuizGroup` | `api.getGroup()`; внутри `api.getGroups()` | Да |
| `PUT /api/groups/{group_id}` | Сохранить измененный quiz group. | Path `group_id`; body `QuizGroup` | `QuizGroup` | `api.saveGroup()` | Да |
| `POST /api/groups/{group_id}/archive` | Архивировать квиз. | Path `group_id` | `{ id, archived, path }` | `api.archiveGroup()` | Да |
| `POST /api/groups/{group_id}/delete` | Удалить квиз через POST, используется модальным окном удаления. | Path `group_id` | `{ id, deleted }` | `api.deleteGroup()` | Да |
| `POST /api/jobs/create-from-docx` | Создать готовый quiz group из DOCX. При `use_ai=true` запускает AI-разметку. | `multipart/form-data`: `file`, `title`, `description`, `workspace_dir`, `use_ai` | `{ job_id }` | `api.createQuizFromDocx()` | Да |
| `POST /api/jobs/validate` | Проверить quiz group валидатором. | JSON `ValidateRequest` | `{ job_id }` | `api.validateGroup()` | Да |
| `POST /api/jobs/upload` | Запустить один квиз в Telegram/QuizBot. | JSON `UploadRequest` | `{ job_id }` | `api.uploadGroup()` | Да |
| `POST /api/jobs/{job_id}/cancel` | Отменить текущую фоновую задачу, включая upload job из UI. | Path `job_id` | `{ ok }` | `api.cancelJob()` | Да |
| `GET /api/jobs/{job_id}` | Получить snapshot фоновой задачи. | Path `job_id` | `JobSnapshot` | `api.getJob()`; внутри `api.waitForJob()` | Да |
| `GET /api/jobs/{job_id}/events` | SSE-поток событий фоновой задачи. | Path `job_id` | `text/event-stream` | `api.subscribeJob()` | Да |

## Request Models

### `CreateManualQuizRequest`

```json
{
  "title": "Новый квиз",
  "description": "",
  "workspace_dir": "."
}
```

### `ValidateRequest`

```json
{
  "group_id": "quiz-id",
  "strict": false
}
```

### `UploadRequest`

```json
{
  "group_id": "quiz-id",
  "name": "Название для запуска",
  "speed": "normal",
  "context_send_mode": "once",
  "shuffle_options": true,
  "start_from": 1
}
```

`speed`: сейчас frontend использует `normal` или `fast`.

`context_send_mode`: сейчас frontend использует `once` или `per-question`.

`start_from`: номер исходного вопроса, с которого начинать новый запуск. UI ограничивает поле диапазоном `1..questions_count`.

### Telegram Account Profiles

Browser-клиенты не создают и не редактируют Telegram account profiles. Web UI работает только с публичным списком профилей, выбором активного профиля, включением/отключением, удалением по id и Telegram login flow для уже существующего профиля.

Ответы account endpoint'ов остаются публичными: без Telegram credentials, полного телефона и полного пути session-файла.

### Telegram Login

Start:

```json
{
  "profile_id": "default"
}
```

Code:

```json
{
  "login_id": "login-id",
  "code": "12345"
}
```

Password:

```json
{
  "login_id": "login-id",
  "password": "2fa-password"
}
```

## Create Pipeline

### DOCX без AI

1. UI вызывает `POST /api/jobs/create-from-docx` с `use_ai=false`.
2. Backend сохраняет DOCX во временную upload-папку workspace.
3. Запускается job `create-from-docx`.
4. Backend создает готовый quiz group JSON в папке квизов.
5. UI ждет завершение через `GET /api/jobs/{job_id}` и/или SSE.
6. UI обновляет список квизов через `GET /api/groups` + `GET /api/groups/{group_id}`.

### DOCX с AI

1. UI вызывает `POST /api/jobs/create-from-docx` с `use_ai=true`.
2. Backend запускает job `create-from-docx-ai`.
3. AI-разметка должна только классифицировать блоки и собрать готовый quiz JSON, без изменения текста вопросов/ответов.
4. Результат сохраняется как готовый quiz group.
5. UI открывает его в редакторе для проверки.

### JSON импорт

1. UI отправляет `.json` в `POST /api/groups/import-json`.
2. Backend валидирует UTF-8 и JSON.
3. Payload приводится к quiz group через `studio_storage.import_group_payload`.
4. UI получает `{ group }` сразу, без фоновой задачи.

## Launch Pipeline

1. UI выбирает quiz group, стартовый вопрос и вызывает `POST /api/jobs/upload`.
2. Backend создает background job `upload` и временный clean JSON для resumable `UploadService`.
3. `UploadService` создает `RunStore` upload run, поэтому прогресс можно читать через `GET /api/runs` и `GET /api/runs/active`.
4. Статус job читается через `GET /api/jobs/{job_id}`.
5. Live-прогресс приходит через `GET /api/jobs/{job_id}/events`; события содержат `upload_progress.done/total` и snapshot `run`.
6. Пауза/остановка сохраненного run идут через `POST /api/runs/{run_id}/pause` и `POST /api/runs/{run_id}/stop`; продолжение через `POST /api/runs/{run_id}/resume`.

## Где смотреть фактическую реализацию

- Route definitions: `backend/studio_api.py`
- Job manager and SSE events: `backend/studio_jobs.py`
- Quiz group load/save/import/delete/archive: `backend/studio_storage.py`
- Runs store: `backend/runs.py`
- Account profiles: `backend/accounts.py`
- Telegram login flow: `backend/telegram_login.py`
- Frontend client methods: `frontend/src/api.ts`
- API tests: `tests/test_studio_api.py`
