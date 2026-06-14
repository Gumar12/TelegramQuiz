# QuizBot Studio Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the provided React QuizBot Studio frontend to the existing Python QuizBot pipeline with real local jobs, live progress, validation, editing, and upload.

**Architecture:** Add a FastAPI backend around the existing scripts and keep the React app in `studio/`. The backend owns file IO and job execution; the frontend calls APIs and subscribes to job events.

**Tech Stack:** Python, FastAPI, Uvicorn, Pydantic, React, Vite, TypeScript, Server-Sent Events.

---

### Task 1: Extract Frontend

**Files:**
- Create: `studio/` from `quizbot-studio.zip`

- [ ] Extract `quizbot-studio.zip` into `studio/`.
- [ ] Verify `studio/package.json` exists.
- [ ] Keep generated `node_modules/` and `dist/` out of git.

### Task 2: Backend Storage Boundary

**Files:**
- Create: `studio_storage.py`
- Test: `tests/test_studio_storage.py`

- [ ] Write failing tests for listing quiz groups from `quizzes/*.json`.
- [ ] Write failing tests for converting backend `correct=1` to UI `correct=0`.
- [ ] Implement `group_id_from_path`, `list_groups`, `load_group`, and `save_group`.
- [ ] Run `python -m pytest tests/test_studio_storage.py -q`.

### Task 3: Job Manager

**Files:**
- Create: `studio_jobs.py`
- Test: `tests/test_studio_jobs.py`

- [ ] Write failing tests for job creation, event append, progress snapshots, and failed terminal state.
- [ ] Implement `JobManager`, `JobState`, `JobEvent`, and `run_in_thread`.
- [ ] Run `python -m pytest tests/test_studio_jobs.py -q`.

### Task 4: FastAPI Backend

**Files:**
- Create: `studio_api.py`
- Modify: `requirements.txt`
- Test: `tests/test_studio_api.py`

- [ ] Add dependencies: `fastapi`, `uvicorn`, `python-multipart`.
- [ ] Write failing API tests for `/api/health`, `/api/groups`, and `/api/jobs/validate`.
- [ ] Implement API endpoints for health, groups, save group, parse DOCX, generate all groups, validate, upload, cancel, job status, and SSE events.
- [ ] Run `python -m pytest tests/test_studio_api.py -q`.

### Task 5: Frontend API Client

**Files:**
- Create: `studio/src/api.ts`
- Modify: `studio/src/types.ts`

- [ ] Add TypeScript types for backend groups, validation report, job snapshot, and job event.
- [ ] Implement `api.getGroups`, `api.getGroup`, `api.saveGroup`, `api.parseDocx`, `api.generateAllGroups`, `api.validateGroup`, `api.uploadGroup`, `api.cancelJob`, and `api.subscribeJob`.
- [ ] Run `npm run lint` from `studio/`.

### Task 6: Wire React Screens

**Files:**
- Modify: `studio/src/App.tsx`
- Modify: `studio/src/components/ImportScreen.tsx`
- Modify: `studio/src/components/MonitorScreen.tsx`
- Modify: `studio/src/components/EditorScreen.tsx`
- Modify: `studio/src/components/DeployScreen.tsx`

- [ ] Replace mock timer pipeline with backend job subscription.
- [ ] Make Import upload DOCX and start parse/generate jobs.
- [ ] Make Editor load and save real group JSON.
- [ ] Make Deploy call real validation and upload endpoints.
- [ ] Keep `context-send-mode=once` as default and map UI `per_question` to CLI `per-question`.
- [ ] Run `npm run build` from `studio/`.

### Task 7: Verification

**Files:**
- Modify only if needed based on failures.

- [ ] Run `python -m pytest -q`.
- [ ] Run `npm run build` from `studio/`.
- [ ] Start `python studio_api.py`.
- [ ] Open the local URL and smoke-test loading groups, starting a validation job, and seeing live monitor logs.

