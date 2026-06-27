"""Local FastAPI backend for QuizBot Studio."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import accounts
from backend import config
from backend import deepseek_markup
from backend import deepseek_markup_builder
from backend import runs
from backend import studio_storage
from backend import telegram_login
from backend import upload_service
from backend import validate_quiz_json
from backend.docx_to_quiz_json_v2 import build_output, format_group_summary
from backend.generate_editable_quiz import (
    group_label,
    group_labels,
    output_path_for_group,
    safe_stem,
)
from backend.pipeline.review import build_review_artifact
from backend.pipeline.validation import validate_clean_quiz_file
from backend.studio_jobs import JobManager

log = logging.getLogger(__name__)


SOURCE_FILENAME = Path("questions_v2.json")
MEDIA_DIRNAME = Path("media")
OUTPUT_DIRNAME = Path("quizzes")
UPLOAD_DIRNAME = Path(".studio_data") / "uploads"

DEFAULT_SOURCE_PATH = config.DATA_DIR / SOURCE_FILENAME
DEFAULT_MEDIA_DIR = config.DATA_DIR / MEDIA_DIRNAME
DEFAULT_OUTPUT_DIR = config.DATA_DIR / OUTPUT_DIRNAME
MEDIA_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}

# Max wall-clock lifetime of a single job-events (SSE) stream. The stream only
# observes the job; hitting this bound closes the stream without cancelling the
# underlying job thread, so a stale/forgotten client cannot loop forever.
JOB_EVENTS_STREAM_MAX_AGE_SECONDS = 30 * 60


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_dir: Path
    source_path: Path
    media_dir: Path
    quizzes_dir: Path


def _setup_logging() -> None:
    if getattr(_setup_logging, "_configured", False):
        return
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config.LOG_PATH, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)
    _setup_logging._configured = True


def _resolve_path(value: str | Path | None, default: str | Path = ".") -> Path:
    raw = str(value if value not in {None, ""} else default).strip() or str(default)
    return Path(raw).expanduser()


def _invalid_workspace_dir() -> HTTPException:
    return HTTPException(
        status_code=400,
        detail="workspace_dir must be a relative path inside the server data directory",
    )


def _resolve_workspace_dir(workspace_dir: str | Path, default_workspace_dir: str | Path) -> Path:
    raw = str(workspace_dir).strip()
    normalized = raw.replace("\\", "/")
    candidate_input = Path(normalized)
    windows_input = PureWindowsPath(raw)
    if (
        not normalized
        or candidate_input.is_absolute()
        or windows_input.is_absolute()
        or windows_input.drive
        or any(part == ".." for part in candidate_input.parts)
    ):
        raise _invalid_workspace_dir()

    root = _resolve_path(default_workspace_dir, config.DATA_DIR).resolve(strict=False)
    candidate = (root / candidate_input).resolve(strict=False)
    if not _is_relative_to(candidate, root):
        raise _invalid_workspace_dir()
    return candidate


def _workspace_context(
    workspace_dir: str | Path | None,
    *,
    default_workspace_dir: str | Path = config.DATA_DIR,
    default_source_path: str | Path | None = None,
    default_media_dir: str | Path | None = None,
    default_quizzes_dir: str | Path | None = None,
) -> WorkspaceContext:
    if workspace_dir is None or str(workspace_dir).strip() == "":
        workspace = _resolve_path(default_workspace_dir, config.DATA_DIR)
        return WorkspaceContext(
            workspace_dir=workspace,
            source_path=Path(default_source_path) if default_source_path is not None else workspace / SOURCE_FILENAME,
            media_dir=Path(default_media_dir) if default_media_dir is not None else workspace / MEDIA_DIRNAME,
            quizzes_dir=Path(default_quizzes_dir) if default_quizzes_dir is not None else workspace / OUTPUT_DIRNAME,
        )

    workspace = _resolve_workspace_dir(workspace_dir, default_workspace_dir)
    return WorkspaceContext(
        workspace_dir=workspace,
        source_path=workspace / SOURCE_FILENAME,
        media_dir=workspace / MEDIA_DIRNAME,
        quizzes_dir=workspace / OUTPUT_DIRNAME,
    )


def _safe_media_filename(filename: str | None) -> str:
    source_name = Path(filename or "image").name
    suffix = Path(source_name).suffix.lower()
    if suffix not in MEDIA_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only image files are supported")
    stem = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", Path(source_name).stem, flags=re.U).strip("_") or "image"
    return f"{int(time.time() * 1000)}_{stem}{suffix}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_media_file(media_path: str, media_dir: Path) -> Path | None:
    raw_path = media_path.replace("\\", "/")
    if Path(raw_path).is_absolute():
        return None
    normalized = raw_path.lstrip("/")
    if normalized.startswith("media/"):
        normalized = normalized.split("/", 1)[1]
    if not normalized:
        return None

    root = media_dir.resolve()
    candidate = (root / Path(normalized)).resolve()
    if not _is_relative_to(candidate, root):
        return None
    if candidate.suffix.lower() not in MEDIA_SUFFIXES:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


class ValidateRequest(BaseModel):
    group_id: str
    strict: bool = False


class UploadRequest(BaseModel):
    group_id: str
    name: str | None = None
    speed: str = "normal"
    context_send_mode: str = "per-question"
    shuffle_options: bool = False
    start_from: int = 1
    confirm_replace_active: bool = False


class CreateManualQuizRequest(BaseModel):
    title: str = "Новый квиз"
    description: str = ""
    workspace_dir: str | None = None


class UseAccountProfileRequest(BaseModel):
    profile_id: str


class CreateAccountProfileRequest(BaseModel):
    display_name: str
    api_id: int
    api_hash: str
    phone: str


class ContinueRunRequest(BaseModel):
    question_index: int
    confirm_rollback: bool = False
    confirm_skip_forward: bool = False
    speed: str | None = None
    context_send_mode: str | None = None
    shuffle_options: bool | None = None


class AutoResumeRequest(BaseModel):
    enabled: bool
    delay_seconds: int = 300


class EtaSettingsRequest(BaseModel):
    bot_response_seconds: float | None = None


class DeepSeekKeyRequest(BaseModel):
    api_key: str


class TelegramLoginStartRequest(BaseModel):
    profile_id: str
    force_sms: bool = False


class TelegramLoginQrStartRequest(BaseModel):
    profile_id: str


class TelegramLoginCodeRequest(BaseModel):
    login_id: str
    code: str


class TelegramLoginPasswordRequest(BaseModel):
    login_id: str
    password: str


def _account_profile_payload(profile: accounts.AccountProfilePublic) -> dict[str, Any]:
    return profile.to_dict()


def _raise_account_http_error(exc: accounts.AccountProfileError) -> None:
    if isinstance(exc, accounts.ProfileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, accounts.ProfileDisabledError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, accounts.ProfileDeletionForbiddenError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _raise_run_http_error(exc: runs.RunStoreError) -> None:
    if isinstance(exc, (runs.RunNotFoundError, runs.ActiveRunNotFoundError)):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _raise_telegram_login_http_error(exc: Exception) -> None:
    if isinstance(exc, accounts.ProfileNotFoundError):
        raise HTTPException(status_code=404, detail="Account profile was not found") from exc
    if isinstance(exc, accounts.ProfileDisabledError):
        raise HTTPException(status_code=409, detail="Account profile is disabled") from exc
    if isinstance(exc, accounts.AccountProfileError):
        raise HTTPException(status_code=400, detail="Account profile is invalid") from exc
    if isinstance(exc, telegram_login.UnknownLoginError):
        raise HTTPException(status_code=404, detail="Telegram login flow was not found") from exc
    if isinstance(exc, telegram_login.LoginExpiredError):
        raise HTTPException(status_code=410, detail="Telegram login flow expired") from exc
    if isinstance(exc, telegram_login.LoginCredentialsMissingError):
        raise HTTPException(status_code=409, detail="Telegram credentials are incomplete") from exc
    if isinstance(
        exc,
        (
            telegram_login.InvalidTelegramCodeError,
            telegram_login.InvalidTelegramPasswordError,
            telegram_login.LoginStepError,
        ),
    ):
        raise HTTPException(status_code=400, detail=str(exc) or "Telegram login input was rejected") from exc
    if isinstance(exc, telegram_login.TelegramLoginAuthError):
        raise HTTPException(status_code=502, detail=str(exc) or "Telegram login failed") from exc
    if isinstance(exc, telegram_login.TelegramLoginError):
        raise HTTPException(status_code=400, detail="Telegram login request is invalid") from exc
    raise HTTPException(status_code=502, detail="Telegram login service failed") from exc


def _is_terminal_run(run: runs.RunState) -> bool:
    if isinstance(run, runs.UploadRun):
        return run.status in {"completed", "failed", "cancelled", "cancelled_replaced"}
    return run.status in {"completed", "failed", "cancelled_replaced"}


def _run_snapshots(store: runs.RunStore) -> list[dict[str, Any]]:
    runs_dir = store.root / runs.RUNS_DIRNAME
    if not runs_dir.exists():
        return []
    snapshots: list[dict[str, Any]] = []
    for state_path in sorted(runs_dir.glob(f"*/{runs.STATE_FILENAME}")):
        snapshots.append(store.safe_status_snapshot(state_path.parent.name))
    return snapshots


def _upload_snapshot_progress(snapshot: dict[str, Any]) -> int:
    if snapshot.get("kind") != "upload":
        return 100 if snapshot.get("status") == "completed" else 0
    total = int(snapshot.get("source_question_count") or 0)
    done = int(snapshot.get("uploaded_count") or 0) + int(snapshot.get("skipped_count") or 0)
    if total <= 0:
        return 100 if snapshot.get("status") == "completed" else 0
    return max(0, min(100, round((done / total) * 100)))


def _require_job(manager: JobManager, job_id: str) -> dict[str, Any]:
    try:
        return manager.snapshot(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}") from exc


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_now_iso() -> str:
    return _utc_now_dt().isoformat()


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_manual_stop_for_auto_resume(run: runs.UploadRun) -> bool:
    error = run.last_error or {}
    code = str(error.get("code") or "")
    return code in {"paused_by_user", "stopped_by_user"}


AUTO_RESUMABLE_ERROR_CODES = {
    "telegram_timeout",
    "telegram_too_many_incoming_messages",
    "telegram_too_many_requests",
    "telegram_flood_wait",
    "telegram_retry_exhausted",
}


def _run_needs_auto_resume(run: runs.UploadRun) -> bool:
    error_code = str((run.last_error or {}).get("code") or "")
    return (
        run.auto_resume_enabled
        and run.status in {"paused", "failed"}
        and not _is_manual_stop_for_auto_resume(run)
        and (run.status == "paused" or error_code in AUTO_RESUMABLE_ERROR_CODES)
    )


class AutoResumeScheduler:
    """Schedules delayed resume jobs for upload runs after technical stops."""

    def __init__(
        self,
        *,
        runtime_dir: Path,
        account_store_root: Path,
        manager: JobManager,
    ):
        self.runtime_dir = runtime_dir
        self.account_store_root = account_store_root
        self.manager = manager
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()

    def wrap_job(
        self,
        target: Callable[[str, JobManager], dict[str, Any] | None],
        *,
        run_id_getter: Callable[[dict[str, Any] | None], str | None],
    ) -> Callable[[str, JobManager], dict[str, Any] | None]:
        def run(job_id: str, manager: JobManager) -> dict[str, Any] | None:
            result = target(job_id, manager)
            run_id = run_id_getter(result)
            if run_id:
                self.schedule_if_needed(run_id)
            return result

        return run

    def schedule_if_needed(self, run_id: str) -> runs.UploadRun | None:
        store = runs.RunStore(self.runtime_dir)
        try:
            run = store.load_run(run_id)
        except runs.RunStoreError:
            self.cancel(run_id)
            return None
        if not isinstance(run, runs.UploadRun):
            self.cancel(run_id)
            return None
        if not _run_needs_auto_resume(run):
            self.cancel(run_id)
            if run.auto_resume_next_at:
                run = store.update_auto_resume(run_id, clear_next_at=True)
            return run

        now = _utc_now_dt()
        next_at = _parse_utc(run.auto_resume_next_at)
        if next_at is None:
            next_at = now + timedelta(seconds=max(30, run.auto_resume_delay_seconds))
            run = store.update_auto_resume(run_id, next_at=next_at.isoformat())

        delay = max(0.0, (next_at - now).total_seconds())
        with self._lock:
            existing = self._timers.pop(run_id, None)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(delay, self._resume_due_run, args=(run_id,))
            timer.daemon = True
            self._timers[run_id] = timer
            timer.start()
        return run

    def cancel(self, run_id: str) -> None:
        with self._lock:
            timer = self._timers.pop(run_id, None)
            if timer is not None:
                timer.cancel()

    def restore_pending(self) -> None:
        store = runs.RunStore(self.runtime_dir)
        runs_dir = store.root / runs.RUNS_DIRNAME
        if not runs_dir.exists():
            return
        for state_path in runs_dir.glob(f"*/{runs.STATE_FILENAME}"):
            self.schedule_if_needed(state_path.parent.name)

    def _resume_due_run(self, run_id: str) -> None:
        with self._lock:
            self._timers.pop(run_id, None)

        store = runs.RunStore(self.runtime_dir)
        try:
            run = store.load_run(run_id)
        except runs.RunStoreError:
            return
        if not isinstance(run, runs.UploadRun) or not _run_needs_auto_resume(run):
            return

        run = store.update_auto_resume(
            run_id,
            clear_next_at=True,
            increment_attempts=True,
        )
        job = self.manager.run_in_thread(
            "auto-resume-run",
            self.wrap_job(
                _resume_run_job(
                    run_id=run_id,
                    runtime_dir=self.runtime_dir,
                    account_store_root=self.account_store_root,
                ),
                run_id_getter=lambda _result: run_id,
            ),
        )
        store.update_auto_resume(run.run_id, last_job_id=job.id)


def _result_run_id(result: dict[str, Any] | None) -> str | None:
    if not isinstance(result, dict):
        return None
    run = result.get("run")
    if isinstance(run, dict):
        run_id = run.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    return None


def _studio_upload_replace_active(runtime_dir: Path, *, confirm_replace_active: bool) -> bool:
    store = runs.RunStore(runtime_dir)
    active_run_id = store.get_active_run_id(required=False)
    if not active_run_id:
        return False
    try:
        active_run = store.load_run(active_run_id)
    except (runs.RunNotFoundError, runs.ActiveRunNotFoundError):
        # The pointer references a run that no longer exists: genuinely no
        # active run to protect.
        return False
    except (runs.RunStoreError, json.JSONDecodeError, OSError, ValueError) as exc:
        # An unreadable/corrupt active run must BLOCK the replace, never be
        # silently treated as "no protection" — that would bypass the
        # protected-run gate.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_run_unreadable",
                "message": (
                    "Active upload run state is unreadable or corrupt; "
                    "resolve it before replacing the active run."
                ),
                "required_action": "inspect_active_run",
                "active_run_id": active_run_id,
            },
        ) from exc
    if _is_terminal_run(active_run):
        return True
    if not runs.has_protected_progress(active_run):
        return True
    if confirm_replace_active:
        return True
    raise HTTPException(
        status_code=409,
        detail={
            "code": "protected_active_run",
            "message": "Active upload run has protected progress and requires explicit replacement confirmation.",
            "required_action": "confirm_replace_active",
            "active_run": store.safe_status_snapshot(active_run_id),
        },
    )


def _unique_flags(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalized_options(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(option).strip() for option in value if str(option).strip()]


def _normalized_correct(value: Any) -> int | list[int] | None:
    if isinstance(value, list):
        correct_values = [item for item in value if isinstance(item, int)]
        return correct_values or None
    if isinstance(value, int):
        return value
    return None


def _one_based_answers(value: Any, option_count: int) -> list[int]:
    raw_values = value if isinstance(value, list) else [value] if isinstance(value, int) else []
    answers: list[int] = []
    for raw in raw_values:
        if not isinstance(raw, int) or isinstance(raw, bool):
            continue
        if 1 <= raw <= option_count and raw not in answers:
            answers.append(raw)
    return answers


def _context_text_for_upload(item: dict[str, Any]) -> str:
    context_title = str(item.get("context_title", "")).strip()
    context = str(item.get("context", "")).strip()
    return "\n\n".join(part for part in [context_title, context] if part)


def _studio_payload_to_clean_upload(payload: dict[str, Any], request: UploadRequest) -> dict[str, Any]:
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("Quiz JSON must contain questions list")

    items: list[dict[str, Any]] = []
    active_context_key: tuple[str, tuple[str, ...]] | None = None
    for index, raw_item in enumerate(questions, start=1):
        if not isinstance(raw_item, dict):
            continue
        options = [str(option).strip() for option in raw_item.get("options", []) if str(option).strip()]
        answers = _one_based_answers(raw_item.get("correct"), len(options))
        media = [str(item) for item in raw_item.get("media", []) if str(item).strip()] if isinstance(raw_item.get("media"), list) else []
        context_text = _context_text_for_upload(raw_item)
        context_key = (context_text, tuple(media)) if context_text or media else None

        if context_key != active_context_key:
            if context_key is None:
                items.append({"type": "reset_context"})
            else:
                items.append({"type": "context", "text": context_text, "media": media})
            active_context_key = context_key

        items.append(
            {
                "type": "question",
                "source_item_id": raw_item.get("source_item_id") or raw_item.get("id") or index,
                "question": str(raw_item.get("question", "")),
                "options": [{"text": option} for option in options],
                "answers": answers,
                "mode": "multiple" if len(answers) > 1 else "single",
                "explanation": str(raw_item.get("explanation", "")),
            }
        )

    title = request.name or str(payload.get("quiz_title", "")).strip() or request.group_id.replace("_", " ")
    return {
        "title": title,
        "description": str(payload.get("quiz_description", "")),
        "settings": {
            "context_send_mode": request.context_send_mode,
            "shuffle_options": request.shuffle_options,
        },
        "items": items,
    }


def _prepare_clean_upload_files(
    *,
    source_path: Path,
    request: UploadRequest,
    work_dir: Path,
    media_base_dir: Path,
) -> tuple[Path, Any]:
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid quiz JSON in {source_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Quiz JSON must be an object")

    work_dir.mkdir(parents=True, exist_ok=True)
    clean_path = work_dir / f"{Path(request.group_id).name}.clean.json"
    clean_payload = _studio_payload_to_clean_upload(payload, request)
    clean_path.write_text(
        json.dumps(clean_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = validate_clean_quiz_file(clean_path, media_base_dir=media_base_dir)
    return clean_path, report


def _studio_review_artifact_path(runtime_dir: Path, group_id: str) -> Path:
    return runtime_dir / "studio-review" / f"{Path(group_id).name}.review-decisions.json"


def _write_studio_review_artifact(runtime_dir: Path, group_id: str, quiz_file_hash: str) -> Path:
    review_path = _studio_review_artifact_path(runtime_dir, group_id)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = build_review_artifact(quiz_file_hash=quiz_file_hash)
    review_path.write_text(
        json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return review_path


def _issue_codes(report: Any) -> list[str]:
    return [str(issue.code) for issue in report.issues]


def _direct_quality_flags(item: dict[str, Any], options: list[str], correct: int | list[int] | None) -> list[str]:
    flags = [str(flag) for flag in item.get("quality_flags", []) if isinstance(flag, str)]
    item_type = str(item.get("type", ""))
    question_text = str(item.get("question", ""))
    explanation_text = str(item.get("explanation", ""))
    if item_type.startswith("needs_"):
        flags.append(item_type)
    if len(question_text) > 255:
        flags.append("Вопрос длиннее лимита Telegram 255 символов.")
    if len(options) < 3:
        flags.append("Меньше 3 вариантов ответа.")
    for option_index, option in enumerate(options, start=1):
        if len(option) > 100:
            flags.append(f"Вариант {option_index} длиннее лимита Telegram 100 символов.")
    if len(explanation_text) > 200:
        flags.append("Объяснение длиннее лимита Telegram 200 символов.")

    correct_values = correct if isinstance(correct, list) else [correct] if isinstance(correct, int) else []
    if not correct_values:
        flags.append("Парсер не нашёл правильный ответ.")
    elif any(index < 1 or index > len(options) for index in correct_values):
        flags.append("Индекс правильного ответа выходит за список вариантов.")
    if len(correct_values) > 1:
        flags.append("Несколько правильных ответов: проверь вручную перед запуском.")
    return _unique_flags(flags)


def _direct_export_question(item: dict[str, Any]) -> dict[str, Any]:
    options = _normalized_options(item.get("options"))
    correct = _normalized_correct(item.get("correct"))
    flags = _direct_quality_flags(item, options, correct)
    item_type = str(item.get("type", ""))

    question: dict[str, Any] = {
        "source_item_id": item.get("id"),
        "date": item.get("date", ""),
        "section": item.get("section", ""),
        "context_title": item.get("context_title", ""),
        "context": item.get("context", ""),
        "media": item.get("media", []) if isinstance(item.get("media"), list) else [],
        "question": item.get("question", ""),
        "options": options,
        "correct": correct,
        "explanation": item.get("explanation", ""),
        "explanation_full": item.get("explanation_full", ""),
        "type": item_type,
        "source": item.get("source", "docx_v2"),
    }
    if flags:
        question["quality_flags"] = flags
    if item_type == "needs_distractor_review" or "needs_distractor_review" in flags:
        question["needs_distractor_review"] = True
    return question


def _direct_group_title(title: str, label: str, total_groups: int) -> str:
    clean_title = title.strip() or "Новый квиз"
    clean_label = label.strip()
    if not clean_label:
        return clean_title
    if total_groups == 1:
        return clean_title
    if clean_label in clean_title:
        return clean_label
    return f"{clean_title} · {clean_label}"


def _manual_quiz_id(title: str) -> str:
    stem = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", title, flags=re.U).strip("_")
    return f"{stem or 'Новый_квиз'}_{int(time.time())}"


def _json_import_title(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("quiz_title", "title", "name", "document_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback.strip() or "Импортированный квиз"


def _direct_export_groups(
    source_data: dict[str, Any],
    *,
    output_dir: Path,
    title: str,
    description: str,
) -> list[dict[str, Any]]:
    labels = group_labels(source_data)
    if not labels:
        labels = [""]

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for label in labels:
        items = [
            item
            for item in source_data.get("questions", [])
            if isinstance(item, dict) and group_label(item) == label
        ]
        if not items:
            continue

        output_label = label or title or "Без группы"
        output_path = output_path_for_group(output_dir, output_label)
        questions = [_direct_export_question(item) for item in items]
        flags_count = sum(len(question.get("quality_flags", [])) for question in questions)
        payload = {
            "quiz_title": _direct_group_title(title, label, len(labels)),
            "quiz_description": description,
            "allow_duplicate_questions": False,
            "format_version": "2.0-direct",
            "questions": questions,
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        results.append(
            {
                "id": output_path.stem,
                "group": label or payload["quiz_title"],
                "output": str(output_path),
                "questions": len(questions),
                "warnings": flags_count,
            }
        )
    return results


def _create_from_docx_job(
    *,
    docx_path: Path,
    source_path: Path,
    media_dir: Path,
    output_dir: Path,
    title: str,
    description: str,
):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        manager.emit(job_id, stage="parsing", progress=5, message=f"Reading DOCX: {docx_path.name}")
        source_path.parent.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)
        source_data = build_output(docx_path, source_path, media_dir, title=title, description=description)
        source_groups = format_group_summary(source_data)
        manager.emit(
            job_id,
            stage="exporting",
            progress=70,
            message="Exporting editor JSON",
            result={"source_path": str(source_path), "source_groups": source_groups},
        )
        groups = _direct_export_groups(
            source_data,
            output_dir=output_dir,
            title=title,
            description=description,
        )
        manager.emit(
            job_id,
            stage="exporting",
            progress=100,
            message=f"Created {len(groups)} JSON file(s)",
            log_type="success",
            result={
                "source_path": str(source_path),
                "groups": groups,
                "report": source_data["report"],
                "output_dir": str(output_dir),
            },
        )
        return {
            "source_path": str(source_path),
            "groups": groups,
            "report": source_data["report"],
            "output_dir": str(output_dir),
        }

    return run


def _create_from_docx_ai_job(
    *,
    docx_path: Path,
    source_path: Path,
    media_dir: Path,
    output_dir: Path,
    workspace_dir: Path,
    runtime_dir: Path,
    title: str,
    description: str,
):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        api_key = config.resolve_deepseek_api_key(runtime_dir)
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY не задан. Укажите ключ в разделе «Аккаунты → DeepSeek API» "
                "или в backend/.env."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)
        source_path.parent.mkdir(parents=True, exist_ok=True)

        debug_name = f"{safe_stem(title or docx_path.stem)}_{int(time.time())}_{job_id}"
        debug_dir = workspace_dir / UPLOAD_DIRNAME / "ai" / debug_name
        source_media_dir = debug_dir / "source_media"
        debug_dir.mkdir(parents=True, exist_ok=True)

        manager.emit(
            job_id,
            stage="ai-markup",
            progress=8,
            message=f"Reading DOCX blocks: {docx_path.name}",
        )
        blocks_md = deepseek_markup.blocks_markdown_from_docx(docx_path, media_dir=source_media_dir)
        blocks_path = debug_dir / f"{safe_stem(title or docx_path.stem)}.blocks.md"
        blocks_path.write_text(blocks_md, encoding="utf-8")

        manager.emit(
            job_id,
            stage="ai-markup",
            progress=30,
            message=f"Sending block stream to DeepSeek: {config.DEEPSEEK_MODEL}",
            result={"blocks_path": str(blocks_path)},
        )
        markup, raw_response = deepseek_markup.request_markup(
            blocks_md,
            api_key=api_key,
            model=config.DEEPSEEK_MODEL,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout_seconds=config.DEEPSEEK_TIMEOUT_SECONDS,
            max_tokens=config.DEEPSEEK_MAX_TOKENS,
        )
        markup_path = debug_dir / f"{safe_stem(title or docx_path.stem)}.markup.json"
        raw_response_path = debug_dir / f"{safe_stem(title or docx_path.stem)}.raw_response.json"
        markup_path.write_text(json.dumps(markup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raw_response_path.write_text(json.dumps(raw_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        manager.emit(
            job_id,
            stage="exporting",
            progress=78,
            message="Building final quiz JSON",
            result={"markup_path": str(markup_path), "raw_response_path": str(raw_response_path)},
        )
        source_blocks = deepseek_markup_builder.parse_blocks_markdown(blocks_md, media_base_dir=source_media_dir)
        quiz_payload = deepseek_markup_builder.build_quiz_from_markup(
            markup,
            source_blocks,
            title=title,
            description=description or "Собрано из DeepSeek-разметки",
            media_output_dir=media_dir,
            media_prefix="media",
        )
        usage = raw_response.get("usage") if isinstance(raw_response.get("usage"), dict) else {}
        quiz_payload["ai_markup"] = {
            "provider": "deepseek",
            "model": raw_response.get("model") or config.DEEPSEEK_MODEL,
            "blocks_path": str(blocks_path),
            "markup_path": str(markup_path),
            "raw_response_path": str(raw_response_path),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }

        output_path = output_path_for_group(output_dir, quiz_payload.get("quiz_title") or title or docx_path.stem)
        output_path.write_text(
            json.dumps(quiz_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report = {
            "items_total": len(quiz_payload.get("questions", [])),
            "global_warnings": markup.get("global_warnings", []),
            "debug_dir": str(debug_dir),
            "model": raw_response.get("model") or config.DEEPSEEK_MODEL,
        }
        source_snapshot = {
            "quiz_title": quiz_payload.get("quiz_title", title),
            "quiz_description": quiz_payload.get("quiz_description", description),
            "format_version": "2.1-deepseek-source",
            "report": report,
            "questions": quiz_payload.get("questions", []),
            "ai_markup": quiz_payload["ai_markup"],
        }
        source_path.write_text(
            json.dumps(source_snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        questions = quiz_payload.get("questions", [])
        warnings_count = sum(
            len(question.get("quality_flags", [])) + len(question.get("warnings", []))
            for question in questions
            if isinstance(question, dict)
        )
        groups = [
            {
                "id": output_path.stem,
                "group": quiz_payload.get("quiz_title") or title or output_path.stem,
                "output": str(output_path),
                "questions": len(questions),
                "warnings": warnings_count,
                "ai": True,
            }
        ]
        result = {
            "source_path": str(source_path),
            "groups": groups,
            "report": report,
            "output_dir": str(output_dir),
            "debug_dir": str(debug_dir),
        }
        manager.emit(
            job_id,
            stage="exporting",
            progress=100,
            message=f"Created AI JSON: {len(questions)} questions",
            log_type="success",
            result=result,
        )
        return result

    return run


def _validate_job(
    group_id: str,
    strict: bool,
    quizzes_dir: Path,
    *,
    runtime_dir: Path,
    media_dir: Path,
):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        path = quizzes_dir / f"{Path(group_id).name}.json"
        manager.emit(job_id, stage="validating", progress=25, group=group_id, message=f"Validating {path.name}")
        try:
            questions, raw_items = validate_quiz_json.load_questions_with_raw(path)
            validate_quiz_json.validate_all(
                questions,
                allow_duplicate_questions=validate_quiz_json.allow_duplicate_questions(path),
            )
            report = validate_quiz_json.build_quality_report(questions, raw_items)
            report.setdefault("errors", [])
        except ValueError as exc:
            report = _build_validation_error_report(path, exc)

        errors = report.get("errors", [])
        warnings = report.get("warnings", [])
        exit_code = 1 if errors else 2 if strict and warnings else 0
        result = {"report": report, "exit_code": exit_code, "strict": strict}
        if not errors:
            upload_request = UploadRequest(group_id=group_id)
            clean_path, upload_report = _prepare_clean_upload_files(
                source_path=path,
                request=upload_request,
                work_dir=runtime_dir / "studio-validation" / Path(group_id).name,
                media_base_dir=media_dir,
            )
            result["upload_validation"] = upload_report.to_dict()
            if upload_report.has_hard_errors:
                exit_code = 1
                result["exit_code"] = exit_code
            elif not upload_report.warnings:
                review_path = _write_studio_review_artifact(
                    runtime_dir,
                    group_id,
                    upload_report.quiz_file_hash,
                )
                result["review_artifact"] = {
                    "path": str(review_path),
                    "quiz_file_hash": upload_report.quiz_file_hash,
                    "clean_path": str(clean_path),
                }
        log_type = "error" if errors else "warn" if warnings else "success"
        message = (
            f"Validation completed with {len(errors)} errors"
            if errors
            else f"Validation completed with {len(warnings)} warnings"
        )
        manager.emit(
            job_id,
            stage="validating",
            progress=100,
            group=group_id,
            message=message,
            log_type=log_type,
            result=result,
        )
        return result

    return run


def _build_validation_error_report(path: Path, exc: ValueError) -> dict[str, Any]:
    try:
        raw_items = validate_quiz_json.load_raw_items(path)
    except ValueError:
        raw_items = []

    errors: list[dict[str, Any]] = []
    for question_index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        question_text = str(item.get("question", ""))
        options = item.get("options", [])
        if not isinstance(options, list):
            continue
        for option_index, option in enumerate(options, start=1):
            if not isinstance(option, str):
                continue
            option_text = " ".join(option.split())
            if len(option_text) > 100:
                errors.append(
                    {
                        "index": question_index,
                        "source_item_id": item.get("source_item_id"),
                        "question": question_text,
                        "code": "too_long_option",
                        "message": f"Вариант #{option_index} длиннее 100 символов. Сократите вариант перед запуском.",
                        "option": {
                            "index": option_index,
                            "text": option_text,
                            "length": len(option_text),
                            "max_length": 100,
                        },
                    }
                )

    if not errors:
        message = str(exc).split("\n", 1)[0]
        match = re.search(r"Question #(\d+) invalid", str(exc))
        question_index = int(match.group(1)) if match else 1
        raw = raw_items[question_index - 1] if 0 <= question_index - 1 < len(raw_items) else {}
        raw_question = raw.get("question", "") if isinstance(raw, dict) else ""
        errors.append(
            {
                "index": question_index,
                "question": str(raw_question),
                "code": "invalid_question",
                "message": f"Вопрос не прошел проверку JSON: {message}",
            }
        )

    return {
        "questions_total": len(raw_items),
        "multi_answer_count": 0,
        "context_count": 0,
        "media_count": 0,
        "correct_position_counts": {},
        "warnings": [],
        "errors": errors,
    }


def _upload_job(
    request: UploadRequest,
    *,
    quizzes_dir: Path,
    media_dir: Path,
    runtime_dir: Path,
    account_store_root: Path,
    replace_active: bool,
):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        path = quizzes_dir / f"{Path(request.group_id).name}.json"
        name = request.name or request.group_id.replace("_", " ")
        manager.emit(
            job_id,
            stage="uploading",
            progress=0,
            group=name,
            message="Готовим квиз к отправке в Telegram",
        )
        work_dir = runtime_dir / "studio-upload-jobs" / job_id
        clean_path, upload_report = _prepare_clean_upload_files(
            source_path=path,
            request=request,
            work_dir=work_dir,
            media_base_dir=media_dir,
        )
        if upload_report.has_hard_errors:
            raise upload_service.UploadGateBlockedError(
                "Upload blocked by validation: " + ", ".join(_issue_codes(upload_report))
            )
        review_path = _studio_review_artifact_path(runtime_dir, request.group_id)

        def checkpoint(upload_run: runs.UploadRun) -> None:
            snapshot = runs.safe_status_snapshot(upload_run, store_root=runtime_dir)
            total = int(snapshot.get("source_question_count") or 0)
            done = int(snapshot.get("uploaded_count") or 0) + int(snapshot.get("skipped_count") or 0)
            progress = _upload_snapshot_progress(snapshot)
            eta = int(snapshot.get("estimated_remaining_seconds") or 0)
            manager.emit(
                job_id,
                stage="uploading",
                progress=progress,
                group=upload_run.quiz_name,
                message=f"Загружено {done} из {total}; следующий вопрос {snapshot.get('next_question_index')}",
                eta=eta,
                result={
                    "run": snapshot,
                    "upload_progress": {
                        "stage": snapshot.get("status"),
                        "done": done,
                        "total": total,
                    },
                },
            )

        service = upload_service.UploadService(
            runtime_root=runtime_dir,
            account_store_root=account_store_root,
            checkpoint_callback=checkpoint,
        )
        upload_run = asyncio.run(
            service.start_upload(
                quiz_file=clean_path,
                review_artifact_file=review_path,
                quiz_name=name,
                speed=request.speed,
                start_from=max(1, int(request.start_from or 1)),
                replace_active=replace_active,
            )
        )
        snapshot = runs.safe_status_snapshot(upload_run, store_root=runtime_dir)
        total = int(snapshot.get("source_question_count") or 0)
        done = int(snapshot.get("uploaded_count") or 0) + int(snapshot.get("skipped_count") or 0)
        result = {
            "run": snapshot,
            "upload_progress": {
                "stage": snapshot.get("status"),
                "done": done,
                "total": total,
            },
        }
        manager.emit(
            job_id,
            stage="uploading",
            progress=_upload_snapshot_progress(snapshot),
            group=name,
            message=f"Upload {snapshot.get('status')}: {done} из {total}",
            log_type="success" if snapshot.get("status") == "completed" else "info",
            result=result,
        )
        return result

    return run


def _resume_run_job(
    *,
    run_id: str,
    runtime_dir: Path,
    account_store_root: Path,
):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        store = runs.RunStore(runtime_dir)

        def checkpoint(upload_run: runs.UploadRun) -> None:
            snapshot = runs.safe_status_snapshot(upload_run, store_root=runtime_dir)
            progress = _upload_snapshot_progress(snapshot)
            next_question = snapshot.get("next_question_index")
            total = snapshot.get("source_question_count")
            manager.emit(
                job_id,
                stage="uploading",
                progress=progress,
                group=str(snapshot.get("quiz_name") or run_id),
                message=f"Загружено {snapshot.get('uploaded_count', 0)} из {total}; следующий вопрос {next_question}",
                result={"run": snapshot},
            )

        service = upload_service.UploadService(
            run_store=store,
            account_store_root=account_store_root,
            checkpoint_callback=checkpoint,
        )
        resumed = asyncio.run(service.resume_upload_run(run_id))
        snapshot = runs.safe_status_snapshot(resumed, store_root=runtime_dir)
        progress = _upload_snapshot_progress(snapshot)
        manager.emit(
            job_id,
            stage="uploading",
            progress=progress,
            group=str(snapshot.get("quiz_name") or run_id),
            message=f"Запуск {run_id} обновлен: {snapshot.get('status')}",
            log_type="success" if snapshot.get("status") == "completed" else "info",
            result={"run": snapshot},
        )
        return {"run": snapshot}

    return run


def _continue_run_job(
    *,
    run_id: str,
    question_index: int,
    runtime_dir: Path,
    account_store_root: Path,
    confirm_rollback: bool = False,
    confirm_skip_forward: bool = False,
    speed: str | None = None,
    context_send_mode: str | None = None,
    shuffle_options: bool | None = None,
):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        store = runs.RunStore(runtime_dir)

        def checkpoint(upload_run: runs.UploadRun) -> None:
            snapshot = runs.safe_status_snapshot(upload_run, store_root=runtime_dir)
            progress = _upload_snapshot_progress(snapshot)
            next_question = snapshot.get("next_question_index")
            total = snapshot.get("source_question_count")
            manager.emit(
                job_id,
                stage="uploading",
                progress=progress,
                group=str(snapshot.get("quiz_name") or run_id),
                message=f"Загружено {snapshot.get('uploaded_count', 0)} из {total}; следующий вопрос {next_question}",
                result={"run": snapshot},
            )

        service = upload_service.UploadService(
            run_store=store,
            account_store_root=account_store_root,
            checkpoint_callback=checkpoint,
        )
        continued = asyncio.run(
            service.continue_upload_run_from(
                run_id,
                question_index,
                confirm_rollback=confirm_rollback,
                confirm_skip_forward=confirm_skip_forward,
                speed=speed,
                context_send_mode=context_send_mode,
                shuffle_options=shuffle_options,
            )
        )
        snapshot = runs.safe_status_snapshot(continued, store_root=runtime_dir)
        progress = _upload_snapshot_progress(snapshot)
        manager.emit(
            job_id,
            stage="uploading",
            progress=progress,
            group=str(snapshot.get("quiz_name") or run_id),
            message=f"Запуск {run_id} продолжен с вопроса {question_index}: {snapshot.get('status')}",
            log_type="success" if snapshot.get("status") == "completed" else "info",
            result={"run": snapshot},
        )
        return {"run": snapshot}

    return run


def create_app(
    *,
    quizzes_dir: str | Path = DEFAULT_OUTPUT_DIR,
    source_path: str | Path = DEFAULT_SOURCE_PATH,
    media_dir: str | Path = DEFAULT_MEDIA_DIR,
    runtime_dir: str | Path | None = None,
    account_store_root: str | Path | None = None,
    manager: JobManager | None = None,
    telegram_login_manager: telegram_login.TelegramLoginManager | None = None,
) -> FastAPI:
    _setup_logging()
    app = FastAPI(title="QuizBot Studio API")
    app.state.workspace_dir = config.DATA_DIR
    app.state.source_path = Path(source_path)
    app.state.media_dir = Path(media_dir)
    app.state.quizzes_dir = Path(quizzes_dir)
    app.state.runtime_dir = Path(runtime_dir) if runtime_dir is not None else config.RUNTIME_DIR
    app.state.account_store_root = (
        Path(account_store_root)
        if account_store_root is not None
        else app.state.runtime_dir / "accounts"
    )
    app.state.manager = manager or JobManager()
    app.state.telegram_login_manager = telegram_login_manager or telegram_login.TelegramLoginManager(
        store_root=app.state.account_store_root,
    )
    app.state.auto_resume_scheduler = AutoResumeScheduler(
        runtime_dir=app.state.runtime_dir,
        account_store_root=app.state.account_store_root,
        manager=app.state.manager,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.studio_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.on_event("startup")
    def restore_auto_resume_jobs() -> None:
        app.state.auto_resume_scheduler.restore_pending()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "time": int(time.time())}

    @app.get("/api/groups")
    def groups() -> dict[str, Any]:
        return {"groups": studio_storage.list_groups(app.state.quizzes_dir)}

    @app.post("/api/groups/manual")
    def create_manual_group(request: CreateManualQuizRequest) -> dict[str, Any]:
        ctx = _workspace_context(
            request.workspace_dir,
            default_workspace_dir=app.state.workspace_dir,
            default_source_path=app.state.source_path,
            default_media_dir=app.state.media_dir,
            default_quizzes_dir=app.state.quizzes_dir,
        )

        title = request.title.strip() or "Новый квиз"
        group_id = _manual_quiz_id(title)
        group = studio_storage.save_group(
            group_id,
            {
                "id": group_id,
                "name": title,
                "description": request.description,
                "date": "",
                "status": "draft",
                "questions": [],
            },
            ctx.quizzes_dir,
        )
        return {"group": group}

    @app.post("/api/groups/import-json")
    async def import_json_group(
        file: UploadFile = File(...),
        title: str = Form(""),
        description: str = Form("Импортировано из JSON"),
        workspace_dir: str | None = Form(None),
    ) -> dict[str, Any]:
        suffix = Path(file.filename or "upload.json").suffix.lower()
        if suffix != ".json":
            raise HTTPException(status_code=400, detail="Only JSON files are supported")

        raw_payload = await file.read()
        try:
            payload = json.loads(raw_payload.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="JSON file must be UTF-8 encoded") from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc.msg}") from exc

        ctx = _workspace_context(
            workspace_dir,
            default_workspace_dir=app.state.workspace_dir,
            default_source_path=app.state.source_path,
            default_media_dir=app.state.media_dir,
            default_quizzes_dir=app.state.quizzes_dir,
        )

        fallback_title = Path(file.filename or "imported_quiz").stem
        quiz_title = title.strip() or _json_import_title(payload, fallback_title)
        group_id = _manual_quiz_id(quiz_title)
        try:
            group = studio_storage.import_group_payload(
                group_id,
                payload,
                ctx.quizzes_dir,
                title=quiz_title,
                description=description,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"group": group}

    @app.get("/api/accounts")
    def account_profiles() -> dict[str, Any]:
        try:
            profiles = accounts.list_profiles(store_root=app.state.account_store_root)
        except accounts.AccountProfileError as exc:
            _raise_account_http_error(exc)
        return {"accounts": [_account_profile_payload(profile) for profile in profiles]}

    @app.post("/api/accounts")
    def create_account_profile(request: CreateAccountProfileRequest) -> dict[str, Any]:
        try:
            profile = accounts.create_profile(
                display_name=request.display_name,
                api_id=request.api_id,
                api_hash=request.api_hash,
                phone=request.phone,
                changed_by="ui",
                store_root=app.state.account_store_root,
            )
        except accounts.AccountProfileError as exc:
            _raise_account_http_error(exc)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"account": _account_profile_payload(profile)}

    @app.patch("/api/accounts/{profile_id}")
    def update_account_profile_disabled(profile_id: str) -> dict[str, Any]:
        raise HTTPException(
            status_code=405,
            detail="Account profile editing is not available in the web UI",
        )

    @app.post("/api/accounts/{profile_id}/delete")
    def delete_account_profile(profile_id: str) -> dict[str, Any]:
        try:
            active_profile = accounts.delete_profile(
                profile_id,
                changed_by="ui",
                store_root=app.state.account_store_root,
            )
        except accounts.AccountProfileError as exc:
            _raise_account_http_error(exc)
        return {
            "active_account": (
                _account_profile_payload(active_profile)
                if active_profile is not None
                else None
            ),
            "deleted": True,
            "id": profile_id,
        }

    @app.post("/api/accounts/{profile_id}/enable")
    def enable_account_profile(profile_id: str) -> dict[str, Any]:
        try:
            profile = accounts.enable_profile(
                profile_id,
                store_root=app.state.account_store_root,
            )
        except accounts.AccountProfileError as exc:
            _raise_account_http_error(exc)
        return {"account": _account_profile_payload(profile)}

    @app.post("/api/accounts/{profile_id}/disable")
    def disable_account_profile(profile_id: str) -> dict[str, Any]:
        try:
            profile = accounts.disable_profile(
                profile_id,
                store_root=app.state.account_store_root,
            )
        except accounts.AccountProfileError as exc:
            _raise_account_http_error(exc)
        return {"account": _account_profile_payload(profile)}

    @app.get("/api/accounts/current")
    def current_account_profile() -> dict[str, Any]:
        try:
            profile = accounts.current_profile(store_root=app.state.account_store_root)
        except accounts.AccountProfileError as exc:
            _raise_account_http_error(exc)
        return {"account": _account_profile_payload(profile)}

    @app.post("/api/accounts/current")
    def use_account_profile(request: UseAccountProfileRequest) -> dict[str, Any]:
        try:
            profile = accounts.use_profile(
                request.profile_id,
                changed_by="ui",
                store_root=app.state.account_store_root,
            )
        except accounts.AccountProfileError as exc:
            _raise_account_http_error(exc)
        return {"account": _account_profile_payload(profile)}

    @app.post("/api/auth/telegram/start")
    async def start_telegram_login(request: TelegramLoginStartRequest) -> dict[str, Any]:
        try:
            return await app.state.telegram_login_manager.start(
                request.profile_id,
                force_sms=request.force_sms,
            )
        except Exception as exc:
            _raise_telegram_login_http_error(exc)

    @app.post("/api/auth/telegram/qr/start")
    async def start_telegram_qr_login(request: TelegramLoginQrStartRequest) -> dict[str, Any]:
        try:
            return await app.state.telegram_login_manager.start_qr(request.profile_id)
        except Exception as exc:
            _raise_telegram_login_http_error(exc)

    @app.post("/api/auth/telegram/code")
    async def submit_telegram_login_code(request: TelegramLoginCodeRequest) -> dict[str, Any]:
        try:
            return await app.state.telegram_login_manager.submit_code(
                request.login_id,
                request.code,
            )
        except Exception as exc:
            _raise_telegram_login_http_error(exc)

    @app.post("/api/auth/telegram/password")
    async def submit_telegram_login_password(request: TelegramLoginPasswordRequest) -> dict[str, Any]:
        try:
            return await app.state.telegram_login_manager.submit_password(
                request.login_id,
                request.password,
            )
        except Exception as exc:
            _raise_telegram_login_http_error(exc)

    @app.get("/api/auth/telegram/{login_id}")
    async def telegram_login_status(login_id: str) -> dict[str, Any]:
        try:
            return await app.state.telegram_login_manager.status(login_id)
        except Exception as exc:
            _raise_telegram_login_http_error(exc)

    @app.delete("/api/auth/telegram/{login_id}")
    async def cancel_telegram_login(login_id: str) -> dict[str, bool]:
        try:
            return await app.state.telegram_login_manager.cancel(login_id)
        except Exception as exc:
            _raise_telegram_login_http_error(exc)

    @app.get("/api/runs")
    def run_list() -> dict[str, Any]:
        store = runs.RunStore(app.state.runtime_dir)
        try:
            return {"runs": _run_snapshots(store)}
        except runs.RunStoreError as exc:
            _raise_run_http_error(exc)

    @app.get("/api/runs/active")
    def active_run() -> dict[str, Any]:
        store = runs.RunStore(app.state.runtime_dir)
        try:
            snapshot = store.safe_status_snapshot()
        except (runs.ActiveRunNotFoundError, runs.RunNotFoundError):
            return {"active": False}
        except runs.RunStoreError as exc:
            _raise_run_http_error(exc)
        snapshot["active"] = True
        return snapshot

    @app.get("/api/runs/{run_id}")
    def run_status(run_id: str) -> dict[str, Any]:
        store = runs.RunStore(app.state.runtime_dir)
        try:
            return store.safe_status_snapshot(run_id)
        except runs.RunStoreError as exc:
            _raise_run_http_error(exc)

    @app.post("/api/runs/{run_id}/pause")
    def pause_run(run_id: str) -> dict[str, Any]:
        store = runs.RunStore(app.state.runtime_dir)
        try:
            run = store.load_run(run_id)
            if _is_terminal_run(run):
                raise HTTPException(
                    status_code=409,
                    detail=f"Run {run_id!r} is already terminal and cannot be paused",
                )
            paused = store.update_status(
                run_id,
                "paused",
                last_error={
                    "code": "paused_by_user",
                    "message": "Запуск поставлен на паузу пользователем.",
                },
            )
            app.state.auto_resume_scheduler.cancel(run_id)
        except HTTPException:
            raise
        except runs.RunStoreError as exc:
            _raise_run_http_error(exc)
        return runs.safe_status_snapshot(paused, store_root=app.state.runtime_dir)

    @app.patch("/api/runs/{run_id}/auto-resume")
    def update_run_auto_resume(run_id: str, request: AutoResumeRequest) -> dict[str, Any]:
        store = runs.RunStore(app.state.runtime_dir)
        try:
            run = store.load_run(run_id)
            if not isinstance(run, runs.UploadRun):
                raise HTTPException(status_code=400, detail=f"Run {run_id!r} is not an upload run")
            updated = store.update_auto_resume(
                run_id,
                enabled=request.enabled,
                delay_seconds=request.delay_seconds,
                clear_next_at=not request.enabled,
            )
            if request.enabled:
                app.state.auto_resume_scheduler.schedule_if_needed(run_id)
            else:
                app.state.auto_resume_scheduler.cancel(run_id)
        except HTTPException:
            raise
        except runs.RunStoreError as exc:
            _raise_run_http_error(exc)
        return store.safe_status_snapshot(updated.run_id)

    @app.post("/api/runs/{run_id}/resume")
    def resume_run(run_id: str) -> dict[str, Any]:
        store = runs.RunStore(app.state.runtime_dir)
        try:
            run = store.load_run(run_id)
            if not isinstance(run, runs.UploadRun):
                raise HTTPException(status_code=400, detail=f"Run {run_id!r} is not an upload run")
            if _is_terminal_run(run):
                raise HTTPException(
                    status_code=409,
                    detail=f"Run {run_id!r} is already terminal and cannot be resumed",
                )
        except HTTPException:
            raise
        except runs.RunStoreError as exc:
            _raise_run_http_error(exc)
        app.state.auto_resume_scheduler.cancel(run_id)
        store.update_auto_resume(run_id, clear_next_at=True)
        job = app.state.manager.run_in_thread(
            "resume-run",
            app.state.auto_resume_scheduler.wrap_job(
                _resume_run_job(
                    run_id=run_id,
                    runtime_dir=app.state.runtime_dir,
                    account_store_root=app.state.account_store_root,
                ),
                run_id_getter=lambda _result: run_id,
            ),
        )
        return {"job_id": job.id}

    @app.post("/api/runs/{run_id}/continue")
    def continue_run(run_id: str, request: ContinueRunRequest) -> dict[str, Any]:
        store = runs.RunStore(app.state.runtime_dir)
        try:
            run = store.load_run(run_id)
            if not isinstance(run, runs.UploadRun):
                raise HTTPException(status_code=400, detail=f"Run {run_id!r} is not an upload run")
            if run.status in {"completed", "cancelled_replaced"}:
                raise HTTPException(
                    status_code=409,
                    detail=f"Run {run_id!r} cannot be continued from status {run.status!r}",
                )
            if request.question_index < run.start_question_index or request.question_index > run.source_question_count + 1:
                raise HTTPException(status_code=400, detail="question_index is outside resumable range")
        except HTTPException:
            raise
        except runs.RunStoreError as exc:
            _raise_run_http_error(exc)
        app.state.auto_resume_scheduler.cancel(run_id)
        store.update_auto_resume(run_id, clear_next_at=True)
        job = app.state.manager.run_in_thread(
            "continue-run",
            app.state.auto_resume_scheduler.wrap_job(
                _continue_run_job(
                    run_id=run_id,
                    question_index=request.question_index,
                    runtime_dir=app.state.runtime_dir,
                    account_store_root=app.state.account_store_root,
                    confirm_rollback=request.confirm_rollback,
                    confirm_skip_forward=request.confirm_skip_forward,
                    speed=request.speed,
                    context_send_mode=request.context_send_mode,
                    shuffle_options=request.shuffle_options,
                ),
                run_id_getter=lambda _result: run_id,
            ),
        )
        return {"job_id": job.id}

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(run_id: str) -> dict[str, Any]:
        store = runs.RunStore(app.state.runtime_dir)
        try:
            run = store.load_run(run_id)
            if _is_terminal_run(run):
                raise HTTPException(
                    status_code=409,
                    detail=f"Run {run_id!r} is already terminal and cannot be stopped",
                )
            stopped = store.update_status(
                run_id,
                "cancelled",
                last_error={
                    "code": "stopped_by_user",
                    "message": "Запуск остановлен пользователем.",
                },
            )
            app.state.auto_resume_scheduler.cancel(run_id)
        except HTTPException:
            raise
        except runs.RunStoreError as exc:
            _raise_run_http_error(exc)
        return runs.safe_status_snapshot(stopped, store_root=app.state.runtime_dir)

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        eta_settings = config.load_eta_settings(app.state.runtime_dir)
        return {
            "workspace_dir": str(app.state.workspace_dir),
            "source_path": str(app.state.source_path),
            "media_dir": str(app.state.media_dir),
            "quizzes_dir": str(app.state.quizzes_dir),
            "eta": {
                "bot_response_seconds": eta_settings["bot_response_seconds"],
                "speed_profiles": {
                    speed: config.estimate_timing_profile(speed, runtime_dir=app.state.runtime_dir)
                    for speed in config.SPEED_PRESETS
                },
            },
            "paths": {
                "workspace": str(app.state.workspace_dir),
                "source": str(app.state.source_path),
                "media": str(app.state.media_dir),
                "quizzes": str(app.state.quizzes_dir),
            },
        }

    @app.patch("/api/settings/eta")
    def update_eta_settings(request: EtaSettingsRequest) -> dict[str, Any]:
        updates: dict[str, float] = {}
        if request.bot_response_seconds is not None:
            updates["bot_response_seconds"] = request.bot_response_seconds
        eta_settings = config.save_eta_settings(updates, app.state.runtime_dir)
        return {"eta": eta_settings}

    @app.get("/api/settings/deepseek")
    def deepseek_settings() -> dict[str, Any]:
        return config.deepseek_key_status(app.state.runtime_dir)

    @app.put("/api/settings/deepseek")
    def update_deepseek_settings(request: DeepSeekKeyRequest) -> dict[str, Any]:
        try:
            config.save_deepseek_api_key(request.api_key, app.state.runtime_dir)
        except ValueError:
            raise HTTPException(status_code=400, detail="API-ключ не может быть пустым")
        return config.deepseek_key_status(app.state.runtime_dir)

    @app.delete("/api/settings/deepseek")
    def delete_deepseek_settings() -> dict[str, Any]:
        config.delete_deepseek_api_key(app.state.runtime_dir)
        return config.deepseek_key_status(app.state.runtime_dir)

    @app.get("/api/media/{media_path:path}")
    def media(media_path: str) -> FileResponse:
        media_dir = Path(app.state.media_dir).resolve()
        resolved = _resolve_media_file(media_path, media_dir)
        if resolved is not None:
            return FileResponse(resolved)
        raise HTTPException(status_code=404, detail=f"Media file not found: {media_path}")

    @app.post("/api/media/upload")
    async def upload_media(file: UploadFile = File(...)) -> dict[str, Any]:
        media_dir = Path(app.state.media_dir)
        media_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_media_filename(file.filename)
        target = media_dir / filename
        with target.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        return {
            "path": f"media/{filename}",
            "filename": filename,
            "saved_path": str(target),
        }

    @app.get("/api/groups/{group_id}")
    def group(group_id: str) -> dict[str, Any]:
        try:
            return studio_storage.load_group(group_id, app.state.quizzes_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/groups/{group_id}")
    def save_group(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return studio_storage.save_group(group_id, payload, app.state.quizzes_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/groups/{group_id}/archive")
    def archive_group(group_id: str) -> dict[str, Any]:
        try:
            return studio_storage.archive_group(group_id, app.state.quizzes_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/groups/{group_id}/delete")
    def delete_group_post(group_id: str) -> dict[str, Any]:
        try:
            return studio_storage.delete_group(group_id, app.state.quizzes_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/jobs/create-from-docx")
    async def create_from_docx(
        file: UploadFile = File(...),
        title: str = Form("Новый квиз"),
        description: str = Form("Создано из DOCX локальным парсером"),
        workspace_dir: str | None = Form(None),
        use_ai: bool = Form(False),
    ) -> dict[str, Any]:
        suffix = Path(file.filename or "upload.docx").suffix or ".docx"
        if suffix.lower() != ".docx":
            raise HTTPException(status_code=400, detail="Only DOCX files are supported")

        ctx = _workspace_context(
            workspace_dir,
            default_workspace_dir=app.state.workspace_dir,
            default_source_path=app.state.source_path,
            default_media_dir=app.state.media_dir,
            default_quizzes_dir=app.state.quizzes_dir,
        )

        upload_dir = ctx.workspace_dir / UPLOAD_DIRNAME
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / f"{int(time.time())}{suffix}"
        with target.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)

        if use_ai:
            job = app.state.manager.run_in_thread(
                "create-from-docx-ai",
                _create_from_docx_ai_job(
                    docx_path=target,
                    source_path=ctx.source_path,
                    media_dir=ctx.media_dir,
                    output_dir=ctx.quizzes_dir,
                    workspace_dir=ctx.workspace_dir,
                    runtime_dir=app.state.runtime_dir,
                    title=title,
                    description=description,
                ),
            )
            return {"job_id": job.id}

        job = app.state.manager.run_in_thread(
            "create-from-docx",
            _create_from_docx_job(
                docx_path=target,
                source_path=ctx.source_path,
                media_dir=ctx.media_dir,
                output_dir=ctx.quizzes_dir,
                title=title,
                description=description,
            ),
        )
        return {"job_id": job.id}

    @app.post("/api/jobs/validate")
    def validate(request: ValidateRequest) -> dict[str, Any]:
        job = app.state.manager.create_job("validate")
        try:
            result = _validate_job(
                request.group_id,
                request.strict,
                app.state.quizzes_dir,
                runtime_dir=app.state.runtime_dir,
                media_dir=app.state.media_dir,
            )(job.id, app.state.manager)
            app.state.manager.complete(job.id, result)
        except BaseException as exc:  # noqa: BLE001 - API job boundary
            app.state.manager.fail(job.id, exc)
        return {"job_id": job.id}

    @app.post("/api/jobs/upload")
    def upload(request: UploadRequest) -> dict[str, Any]:
        replace_active = _studio_upload_replace_active(
            app.state.runtime_dir,
            confirm_replace_active=request.confirm_replace_active,
        )
        job = app.state.manager.run_in_thread(
            "upload",
            app.state.auto_resume_scheduler.wrap_job(
                _upload_job(
                    request,
                    quizzes_dir=app.state.quizzes_dir,
                    media_dir=app.state.media_dir,
                    runtime_dir=app.state.runtime_dir,
                    account_store_root=app.state.account_store_root,
                    replace_active=replace_active,
                ),
                run_id_getter=_result_run_id,
            ),
        )
        return {"job_id": job.id}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, Any]:
        try:
            app.state.manager.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}") from exc
        return {"ok": True}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        return _require_job(app.state.manager, job_id)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request) -> StreamingResponse:
        _require_job(app.state.manager, job_id)

        async def event_stream():
            index = 0
            deadline = time.monotonic() + JOB_EVENTS_STREAM_MAX_AGE_SECONDS
            while True:
                # The stream only observes the job; closing it (disconnect or
                # max-age timeout) never cancels the underlying job thread.
                if await request.is_disconnected():
                    break
                events = app.state.manager.events_since(job_id, index)
                for event in events:
                    index = event["index"] + 1
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                snapshot = app.state.manager.snapshot(job_id)
                if snapshot["status"] in {"completed", "failed", "cancelled"} and not events:
                    break
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    if DEFAULT_MEDIA_DIR.exists():
        app.mount("/media", StaticFiles(directory=DEFAULT_MEDIA_DIR), name="media")

    studio_dist = config.PROJECT_ROOT / "frontend" / "dist"
    if studio_dist.exists():
        app.mount("/", StaticFiles(directory=studio_dist, html=True), name="studio")

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("backend.studio_api:app", host="127.0.0.1", port=8000, reload=False)
