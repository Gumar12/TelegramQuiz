# QuizBot Studio Integration Design

## Goal

Connect the provided React/Vite QuizBot Studio frontend to the existing Python QuizBot pipeline so local users can run DOCX parsing, GPT normalization, validation, editing, and Telegram upload from a browser UI.

## Scope

The first integrated version runs locally only. It does not add authentication, cloud deployment, multi-user collaboration, or remote file storage.

## Architecture

The app is split into:

- `studio/`: React frontend from `quizbot-studio.zip`.
- `studio_api.py`: FastAPI app that exposes local API endpoints.
- `studio_jobs.py`: in-process job manager, status store, live events, logs, cancel flag.
- `studio_storage.py`: JSON group discovery, conversion between backend JSON and frontend models, safe writes.

Existing scripts remain the source of truth:

- `docx_to_quiz_json_v2.py` parses DOCX to `questions_v2.json`.
- `generate_editable_quiz.py` creates one clean JSON per group.
- `validate_quiz_json.py` validates clean/upload JSON.
- `main.py` uploads to `@QuizBot`.

## Frontend Screens

`ImportScreen` must call backend APIs instead of simulating parse results. It supports uploading a DOCX and starting parse/generate jobs.

`MonitorScreen` subscribes to real server-sent events for the active job. It shows progress, current group, current step, ETA, logs, warnings, and cancellation state.

`EditorScreen` loads real quiz groups from `quizzes/*.json`, edits them in the browser, and saves them back through the backend.

`DeployScreen` runs real validation and real Telegram upload. It keeps `context-send-mode=once` as the default.

## API Shape

- `GET /api/health`
- `GET /api/groups`
- `GET /api/groups/{group_id}`
- `PUT /api/groups/{group_id}`
- `POST /api/jobs/parse-docx`
- `POST /api/jobs/generate-all-groups`
- `POST /api/jobs/validate`
- `POST /api/jobs/upload`
- `POST /api/jobs/{job_id}/cancel`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/events`

## Progress Model

Jobs publish structured events:

```json
{
  "job_id": "abc",
  "status": "running",
  "stage": "normalizing",
  "progress": 42,
  "current_group": "19 мая УТРО",
  "current_step": "Normalizing group 3 of 7",
  "eta": 120,
  "message": "Started GPT normalizer",
  "warnings": []
}
```

DOCX parsing reports coarse stage progress. GPT normalization reports group-level progress. Validation reports final report data. Upload reports start/end plus logs; per-question upload progress can be added later by instrumenting `flow.py`.

## Data Mapping

Backend JSON uses 1-based `correct`. The React UI uses 0-based `correct`. `studio_storage.py` converts at the API boundary.

Backend supports `correct` as `int | list[int]`; initial UI will edit single-answer questions. Multi-answer questions are preserved in JSON but shown as read-only warning in the first version if needed.

`context_title`, `context`, `media`, `source_item_id`, `date`, `section`, and `quality_flags` are preserved when saving.

## Error Handling

Each job records:

- `failed` status and error message on exceptions.
- stderr-like log entries for user-visible failures.
- partial outputs remain on disk for inspection.

Cancel requests set a cancel flag. Long-running GPT/upload calls may only stop between groups or after the current blocking call returns.

## Testing

Backend tests cover:

- group discovery and 1-based/0-based conversion;
- saving edited groups;
- job event creation and terminal states;
- validation job output.

Frontend is verified with TypeScript build. The local app is smoke-tested by starting backend and opening the UI.

