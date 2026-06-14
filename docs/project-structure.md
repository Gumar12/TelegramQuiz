# Project Structure

## Overview
Quizbot combines a Python backend, a local Studio web UI, and helper scripts for
turning source documents into QuizBot-ready JSON and uploading quizzes to
Telegram @QuizBot.

## Directories
- `backend/` - Python backend, FastAPI Studio API, parsers, validators, OpenAI normalizer, Telegram uploader.
- `frontend/` - React/Vite Studio UI.
- `tests/` - Pytest coverage for backend modules and Studio behavior.
- `docs/` - Project documentation, runbooks, agent docs, and historical plans/specs.
- `scripts/` - Local helper scripts for splitting, normalizing, and launching workflows.
- `data/` - Local runtime workspace for sources, generated media, quizzes, sessions, and logs.
- `media/` - Local extracted or test media files.
- `quizzes/` - Generated or reviewed quiz JSON outputs.
- `artifacts/` - Built or packaged outputs.

## Important Backend Files
- `backend/studio_api.py` - Local FastAPI app and job endpoints.
- `backend/studio_jobs.py` - In-process job state and event handling.
- `backend/studio_storage.py` - Quiz group load/save helpers.
- `backend/docx_to_quiz_json_v2.py` - DOCX to source JSON parser.
- `backend/gpt_normalizer.py` - OpenAI-backed normalizer.
- `backend/generate_editable_quiz.py` - Group-level editable quiz generation.
- `backend/validate_quiz_json.py` - Local validation and quality report.
- `backend/main.py` - Telegram @QuizBot upload CLI.
- `backend/config.py` - Environment, paths, pacing, and runtime settings.

## Common Workflows
Install backend:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

Run local Studio:
```powershell
python -m backend.studio_api
```

Parse DOCX into v2 source JSON:
```powershell
python -m backend.docx_to_quiz_json_v2 --input data/source.docx --output data/questions_v2.json --media-dir data/media --show-groups
```

Generate editable quiz JSON for all groups:
```powershell
python -m backend.generate_editable_quiz --source data/questions_v2.json --all-groups --output-dir data/quizzes --model gpt-4.1-mini --media-root data --style-examples 5
```

Validate before upload:
```powershell
python -m backend.validate_quiz_json --file data\quizzes\quiz.json --strict
```

Upload to Telegram @QuizBot:
```powershell
python -m backend.main --speed fast --file data\quizzes\quiz.json --name "Название"
```

Frontend checks:
```powershell
cd frontend
npm install
npm run lint
npm run build
```
