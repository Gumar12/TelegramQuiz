# Agent Rules

## Priority
- Follow direct user instructions first, then `AGENTS.md`, then this file.
- If instructions conflict, stop and ask only when a safe assumption is not possible.
- Keep repository-level rules concise; put personal or experimental behavior in `.codex/`.

## Editing
- Make small focused changes that match the surrounding style.
- Prefer existing helpers, schemas, models, and command patterns.
- Do not rename, move, or delete files unless the task requires it.
- Do not touch unrelated dirty work in the git tree.
- Do not edit generated/private outputs in `data/`, `media/`, `quizzes/`, or `artifacts/` unless explicitly requested.
- Use clear markdown and comments only where they help future maintenance.

## Dependencies
- Do not add Python or npm dependencies without a concrete need.
- If a dependency is needed, update the correct manifest and explain why.
- Backend dependencies live in `backend/requirements.txt`.
- Frontend dependencies live in `frontend/package.json`.

## Backend
- Backend code is Python and uses FastAPI for Studio endpoints.
- CLI entry points are run with `python -m backend.<module>`.
- Prefer Pydantic models and existing validators over ad hoc validation.
- Upload code talks to Telegram through a live user account; keep pacing conservative.

## Frontend
- Frontend source is in `frontend/` and uses React, TypeScript, Vite, and Tailwind.
- Use existing components and styling patterns before adding new abstractions.
- Run `npm run lint` or `npm run build` for meaningful frontend code changes.

## Secrets And Data
- Never expose `backend/.env`, `.env`, Telegram session files, or `OPENAI_API_KEY`.
- Treat real DOCX files, quiz JSON, media files, and upload logs as private data.
- Do not commit runtime sessions, generated quiz outputs, or normalized private datasets.
- If a command would send data to OpenAI or Telegram, make that explicit before running it.

## Testing
- For backend code changes, run the smallest useful `python -m pytest ...` command.
- For shared backend behavior, run `python -m pytest -q` when feasible.
- For frontend code changes, run `npm run lint` and `npm run build` from `frontend/`.
- For documentation-only changes, verify file presence/format and report that project tests were not run.

## Final Response
- List changed files.
- Report exact checks run.
- Call out skipped checks, data risks, or manual follow-up.
