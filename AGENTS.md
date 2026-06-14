# AGENTS.md

## Project
Quizbot is a local pipeline for building Telegram @QuizBot quizzes:
DOCX/JSON source -> parsing/normalization/editing -> validation -> upload.

Read the detailed docs before non-trivial work:
- Rules: [docs/agent-rules.md](docs/agent-rules.md)
- Structure: [docs/project-structure.md](docs/project-structure.md)

## Quick Commands
Backend setup:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

Frontend setup:
```powershell
cd frontend
npm install
```

Run Studio:
```powershell
python -m backend.studio_api
```

Test:
```powershell
python -m pytest -q
cd frontend
npm run lint
npm run build
```

Validate and upload:
```powershell
python -m backend.validate_quiz_json --file quiz.json --strict
python -m backend.main --file quiz.json --name "Название"
```

## Working Rules
- Follow existing style and keep changes small.
- Do not add dependencies without a clear reason.
- Do not rewrite unrelated code or generated data.
- Treat `backend/.env`, `*.session`, API keys, media, DOCX, and real quiz data as private.
- Avoid changing upload pacing, Telegram behavior, or production-like settings unless asked.
- Prefer scoped tests for code changes; docs-only changes do not require project tests.

## Before Final Answer
- Summarize changed files.
- Say what was tested.
- Mention risks, skipped checks, or TODOs.
