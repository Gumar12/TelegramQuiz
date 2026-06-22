"""Filesystem-backed upload/probe run ledger.

Run state is private runtime data. Public snapshots intentionally expose only
operational progress fields and never account/session secrets.
"""
from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping
from uuid import uuid4

from backend import config

RUNS_DIRNAME = "runs"
STATE_FILENAME = "state.json"
ACTIVE_RUN_FILENAME = "active-run.json"

UPLOAD_STATUSES = {
    "queued",
    "review_required",
    "running",
    "paused",
    "rollback",
    "skipped_forward",
    "failed",
    "cancelled",
    "cancelled_replaced",
    "completed",
}
PROBE_STATUSES = {
    "running",
    "cooldown",
    "paused",
    "completed",
    "failed",
    "cancelled_replaced",
}
PROTECTED_UPLOAD_STATUSES = {
    "running",
    "paused",
    "rollback",
    "skipped_forward",
}
SECRET_KEY_PARTS = (
    "access_key",
    "api_hash",
    "apihash",
    "api_key",
    "apikey",
    "credential",
    "password",
    "phone",
    "secret",
    "session",
    "token",
)

class RunStoreError(ValueError):
    """Base run store error."""


class RunNotFoundError(RunStoreError):
    """Raised when a run state file cannot be found."""


class ActiveRunNotFoundError(RunStoreError):
    """Raised when --run-id is omitted but no active run exists."""


class ActiveRunExistsError(RunStoreError):
    """Raised when a new active run would silently replace another run."""


class QuizHashMismatchError(RunStoreError):
    """Raised when the quiz file changed since the run was created."""


class ProtectedActiveRunError(RunStoreError):
    """Raised when protected progress would be overwritten."""


@dataclass(slots=True)
class UploadRun:
    run_id: str
    quiz_file: str
    quiz_file_hash: str
    quiz_name: str
    account_profile_id: str
    speed: str = "normal"
    start_question_index: int = 1
    next_question_index: int = 1
    source_question_count: int = 0
    status: str = "queued"
    kind: str = "upload"
    draft_question_offset: int = 0
    context_send_mode: str = "per-question"
    shuffle_options: bool = False
    started_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
    uploaded_questions: list[int] = field(default_factory=list)
    skipped_questions: list[int] = field(default_factory=list)
    skip_events: list[dict[str, Any]] = field(default_factory=list)
    cooldown_events: list[dict[str, Any]] = field(default_factory=list)
    cleanup_events: list[dict[str, Any]] = field(default_factory=list)
    last_error: dict[str, Any] | None = None
    last_bot_state: dict[str, Any] | None = None
    share_link: str | None = None
    replaced_by_run_id: str | None = None
    auto_resume_enabled: bool = False
    auto_resume_delay_seconds: int = 300
    auto_resume_next_at: str | None = None
    auto_resume_attempts: int = 0
    auto_resume_last_job_id: str | None = None
    auto_resume_last_scheduled_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> dict[str, Any]:
        return self.to_dict()

    def dict(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UploadRun":
        if not isinstance(data, Mapping):
            raise RunStoreError("Upload run state must be an object")
        values = _known_field_values(cls, data)
        values.setdefault("kind", "upload")
        values["run_id"] = str(values["run_id"])
        values["quiz_file"] = str(values["quiz_file"])
        values["quiz_file_hash"] = str(values["quiz_file_hash"])
        values["quiz_name"] = str(values["quiz_name"])
        values["account_profile_id"] = str(values["account_profile_id"])
        values["speed"] = str(values.get("speed") or "normal")
        values["status"] = str(values.get("status") or "queued")
        if values["status"] not in UPLOAD_STATUSES:
            raise RunStoreError(f"Unsupported upload run status: {values['status']!r}")
        values["start_question_index"] = int(values.get("start_question_index") or 1)
        values["next_question_index"] = int(
            values.get("next_question_index") or values["start_question_index"]
        )
        values["source_question_count"] = int(values.get("source_question_count") or 0)
        values["draft_question_offset"] = int(
            values.get("draft_question_offset")
            if values.get("draft_question_offset") is not None
            else max(0, values["start_question_index"] - 1)
        )
        values["shuffle_options"] = bool(values.get("shuffle_options", False))
        values["auto_resume_enabled"] = bool(values.get("auto_resume_enabled", False))
        values["auto_resume_delay_seconds"] = max(
            30,
            int(values.get("auto_resume_delay_seconds") or 300),
        )
        values["auto_resume_attempts"] = max(
            0,
            int(values.get("auto_resume_attempts") or 0),
        )
        values["uploaded_questions"] = _int_list(values.get("uploaded_questions"))
        values["skipped_questions"] = _int_list(values.get("skipped_questions"))
        values["skip_events"] = _dict_list(values.get("skip_events"))
        values["cooldown_events"] = _dict_list(values.get("cooldown_events"))
        values["cleanup_events"] = _dict_list(values.get("cleanup_events"))
        if values.get("last_error") is not None and not isinstance(
            values["last_error"], dict
        ):
            raise RunStoreError("last_error must be an object or null")
        if values.get("last_bot_state") is not None and not isinstance(
            values["last_bot_state"], dict
        ):
            raise RunStoreError("last_bot_state must be an object or null")
        return cls(**values)

    model_validate = from_dict


@dataclass(slots=True)
class SpeedProbeRun:
    probe_id: str
    account_profile_id: str
    quiz_name: str
    source_quiz_file: str
    source_quiz_file_hash: str
    delay_policy: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    kind: str = "speed_probe"
    first_limit_at_question: int | None = None
    limit_events: list[dict[str, Any]] = field(default_factory=list)
    disposable: bool = True
    cleanup_status: str = "not_started"
    created_at: str = ""
    updated_at: str = ""
    cleanup_events: list[dict[str, Any]] = field(default_factory=list)
    last_error: dict[str, Any] | None = None
    replaced_by_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def model_dump(self) -> dict[str, Any]:
        return self.to_dict()

    def dict(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpeedProbeRun":
        if not isinstance(data, Mapping):
            raise RunStoreError("Speed probe run state must be an object")
        values = _known_field_values(cls, data)
        values.setdefault("kind", "speed_probe")
        values["probe_id"] = str(values["probe_id"])
        values["account_profile_id"] = str(values["account_profile_id"])
        values["quiz_name"] = str(values["quiz_name"])
        values["source_quiz_file"] = str(values["source_quiz_file"])
        values["source_quiz_file_hash"] = str(values["source_quiz_file_hash"])
        values["status"] = str(values.get("status") or "running")
        if values["status"] not in PROBE_STATUSES:
            raise RunStoreError(f"Unsupported speed probe status: {values['status']!r}")
        values["delay_policy"] = _dict_value(values.get("delay_policy"))
        values["limit_events"] = _dict_list(values.get("limit_events"))
        values["cleanup_events"] = _dict_list(values.get("cleanup_events"))
        values["disposable"] = bool(values.get("disposable", True))
        if values.get("first_limit_at_question") is not None:
            values["first_limit_at_question"] = int(values["first_limit_at_question"])
        if values.get("last_error") is not None and not isinstance(
            values["last_error"], dict
        ):
            raise RunStoreError("last_error must be an object or null")
        return cls(**values)

    model_validate = from_dict


RunState = UploadRun | SpeedProbeRun


class RunStore:
    """Local JSON store for upload and probe runs."""

    def __init__(self, root: str | Path | None = None):
        self.root = _runtime_root(root)

    def create_upload_run(
        self,
        *,
        quiz_file: str | Path,
        quiz_name: str,
        account_profile_id: str,
        speed: str = "normal",
        start_question_index: int = 1,
        next_question_index: int | None = None,
        source_question_count: int = 0,
        context_send_mode: str = "per-question",
        shuffle_options: bool = False,
        status: str = "queued",
        run_id: str | None = None,
        make_active: bool = True,
        replace_active: bool = False,
    ) -> UploadRun:
        if start_question_index < 1:
            raise RunStoreError("start_question_index must be >= 1")
        if status not in UPLOAD_STATUSES:
            raise RunStoreError(f"Unsupported upload run status: {status!r}")

        now = _utc_now()
        resolved_run_id = run_id or _new_id("upload")
        if make_active:
            self._ensure_can_activate(resolved_run_id, replace_existing=replace_active)
        skipped_questions = list(range(1, start_question_index))
        run = UploadRun(
            run_id=resolved_run_id,
            quiz_file=str(Path(quiz_file)),
            quiz_file_hash=compute_file_sha256(quiz_file),
            quiz_name=quiz_name,
            account_profile_id=account_profile_id,
            speed=speed,
            start_question_index=start_question_index,
            next_question_index=next_question_index or start_question_index,
            source_question_count=source_question_count,
            status=status,
            draft_question_offset=max(0, start_question_index - 1),
            context_send_mode=context_send_mode,
            shuffle_options=shuffle_options,
            created_at=now,
            updated_at=now,
            skipped_questions=skipped_questions,
            skip_events=[
                _skip_event(index, reason="start_from", skipped_by="system", when=now)
                for index in skipped_questions
            ],
        )
        self.save_run(run, touch_updated_at=False)
        if make_active:
            self.activate_run(
                run.run_id,
                kind=run.kind,
                replace_existing=replace_active,
                reason="create_upload_run",
            )
        return run

    def create_speed_probe_run(
        self,
        *,
        source_quiz_file: str | Path,
        quiz_name: str,
        account_profile_id: str,
        delay_policy: Mapping[str, Any] | None = None,
        probe_id: str | None = None,
        make_active: bool = True,
        replace_active: bool = False,
    ) -> SpeedProbeRun:
        now = _utc_now()
        resolved_probe_id = probe_id or _new_id("probe")
        if make_active:
            self._ensure_can_activate(
                resolved_probe_id,
                replace_existing=replace_active,
            )
        run = SpeedProbeRun(
            probe_id=resolved_probe_id,
            account_profile_id=account_profile_id,
            quiz_name=quiz_name,
            source_quiz_file=str(Path(source_quiz_file)),
            source_quiz_file_hash=compute_file_sha256(source_quiz_file),
            delay_policy=dict(delay_policy or {}),
            created_at=now,
            updated_at=now,
        )
        self.save_run(run, touch_updated_at=False)
        if make_active:
            self.activate_run(
                run.probe_id,
                kind=run.kind,
                replace_existing=replace_active,
                reason="create_speed_probe_run",
            )
        return run

    def load_run(self, run_id: str) -> RunState:
        path = self.state_path(run_id)
        if not path.exists():
            raise RunNotFoundError(f"Run {run_id!r} was not found")
        data = _read_json(path)
        kind = data.get("kind", "upload")
        if kind == "speed_probe":
            return SpeedProbeRun.from_dict(data)
        return UploadRun.from_dict(data)

    def save_run(self, run: RunState, *, touch_updated_at: bool = True) -> RunState:
        if touch_updated_at:
            run.updated_at = _utc_now()
        if run.last_error is not None:
            run.last_error = _safe_error(run.last_error)
        _atomic_write_json(self.state_path(_run_id(run)), run.to_dict())
        return run

    def record_question_uploaded(
        self,
        run_id: str,
        source_question_index: int | None = None,
        *,
        bot_message_id: int | str | None = None,
        last_bot_state: Mapping[str, Any] | None = None,
    ) -> UploadRun:
        run = self._load_upload_run(run_id)
        question_index = source_question_index or run.next_question_index
        if question_index < 1:
            raise RunStoreError("source_question_index must be >= 1")
        if question_index not in run.uploaded_questions:
            run.uploaded_questions.append(question_index)
            run.uploaded_questions.sort()
        run.next_question_index = max(run.next_question_index, question_index + 1)
        if last_bot_state is not None:
            run.last_bot_state = dict(last_bot_state)
        elif bot_message_id is not None:
            run.last_bot_state = {"bot_message_id": bot_message_id}
        return self.save_run(run)

    def record_skip(
        self,
        run_id: str,
        source_question_index: int,
        *,
        reason: str,
        skipped_by: str = "cli",
    ) -> UploadRun:
        run = self._load_upload_run(run_id)
        if source_question_index < 1:
            raise RunStoreError("source_question_index must be >= 1")
        if source_question_index not in run.skipped_questions:
            run.skipped_questions.append(source_question_index)
            run.skipped_questions.sort()
        run.skip_events.append(
            _skip_event(
                source_question_index,
                reason=reason,
                skipped_by=skipped_by,
                when=_utc_now(),
            )
        )
        run.next_question_index = max(run.next_question_index, source_question_index + 1)
        return self.save_run(run)

    def update_status(
        self,
        run_id: str,
        status: str,
        *,
        last_error: Mapping[str, Any] | None = None,
    ) -> RunState:
        run = self.load_run(run_id)
        if isinstance(run, UploadRun) and status not in UPLOAD_STATUSES:
            raise RunStoreError(f"Unsupported upload run status: {status!r}")
        if isinstance(run, SpeedProbeRun) and status not in PROBE_STATUSES:
            raise RunStoreError(f"Unsupported speed probe status: {status!r}")
        run.status = status
        if last_error is not None:
            run.last_error = dict(last_error)
        return self.save_run(run)

    def update_auto_resume(
        self,
        run_id: str,
        *,
        enabled: bool | None = None,
        delay_seconds: int | None = None,
        next_at: str | None = None,
        clear_next_at: bool = False,
        last_job_id: str | None = None,
        increment_attempts: bool = False,
    ) -> UploadRun:
        run = self._load_upload_run(run_id)
        if enabled is not None:
            run.auto_resume_enabled = bool(enabled)
            if not enabled:
                run.auto_resume_next_at = None
        if delay_seconds is not None:
            run.auto_resume_delay_seconds = max(30, int(delay_seconds))
        if clear_next_at:
            run.auto_resume_next_at = None
        elif next_at is not None:
            run.auto_resume_next_at = next_at
        if last_job_id is not None:
            run.auto_resume_last_job_id = last_job_id
        if increment_attempts:
            run.auto_resume_attempts += 1
            run.auto_resume_last_scheduled_at = _utc_now()
        return self.save_run(run)

    def activate_run(
        self,
        run_id: str,
        *,
        kind: str | None = None,
        replace_existing: bool = False,
        reason: str = "set_active",
    ) -> None:
        run = self.load_run(run_id)
        active_run_id = self.get_active_run_id(required=False)
        if active_run_id and active_run_id != run_id:
            if not replace_existing:
                active_run = self.load_run(active_run_id)
                if has_protected_progress(active_run):
                    raise ProtectedActiveRunError(
                        f"Active run {active_run_id!r} has protected progress"
                    )
                raise ActiveRunExistsError(
                    f"Active run {active_run_id!r} must be replaced explicitly"
                )
            self.replace_active_run(run_id, reason=reason)
            return
        self._write_active_pointer(run_id, kind=kind or _run_kind(run))

    def replace_active_run(
        self,
        new_run_id: str,
        *,
        reason: str = "start_new_with_cleanup",
        cleanup_result: str = "replaced",
    ) -> RunState | None:
        new_run = self.load_run(new_run_id)
        old_run_id = self.get_active_run_id(required=False)
        if old_run_id and old_run_id != new_run_id:
            old_run = self.load_run(old_run_id)
            old_run.status = "cancelled_replaced"
            old_run.replaced_by_run_id = new_run_id
            if hasattr(old_run, "cleanup_events"):
                old_run.cleanup_events.append(
                    {
                        "reason": reason,
                        "old_run_id": old_run_id,
                        "new_run_id": new_run_id,
                        "result": cleanup_result,
                        "cleaned_at": _utc_now(),
                    }
                )
            self.save_run(old_run)
            replaced: RunState | None = old_run
        else:
            replaced = None
        self._write_active_pointer(new_run_id, kind=_run_kind(new_run))
        return replaced

    def get_active_run_id(self, *, required: bool = True) -> str | None:
        path = self.active_run_path()
        if not path.exists():
            if required:
                raise ActiveRunNotFoundError("No active run is set")
            return None
        data = _read_json(path)
        run_id = str(data.get("run_id") or "")
        if not run_id:
            if required:
                raise ActiveRunNotFoundError("active-run.json has no run_id")
            return None
        return run_id

    def resolve_run_id(self, run_id: str | None = None) -> str:
        if run_id:
            return run_id
        active_run_id = self.get_active_run_id(required=True)
        assert active_run_id is not None
        return active_run_id

    def resolve_run(self, run_id: str | None = None) -> RunState:
        return self.load_run(self.resolve_run_id(run_id))

    def assert_quiz_hash_matches(
        self,
        run_id: str,
        *,
        quiz_file: str | Path | None = None,
    ) -> UploadRun:
        run = self._load_upload_run(run_id)
        current_hash = compute_file_sha256(quiz_file or run.quiz_file)
        if current_hash != run.quiz_file_hash:
            raise QuizHashMismatchError(
                f"Quiz file hash mismatch for run {run_id!r}; refusing resume"
            )
        return run

    def safe_status_snapshot(self, run_id: str | None = None) -> dict[str, Any]:
        return safe_status_snapshot(self.resolve_run(run_id), store_root=self.root)

    def state_path(self, run_id: str) -> Path:
        return self.root / RUNS_DIRNAME / run_id / STATE_FILENAME

    def active_run_path(self) -> Path:
        return self.root / ACTIVE_RUN_FILENAME

    def _write_active_pointer(self, run_id: str, *, kind: str) -> None:
        _atomic_write_json(
            self.active_run_path(),
            {
                "run_id": run_id,
                "kind": kind,
                "changed_at": _utc_now(),
                "changed_by": "cli",
            },
        )

    def _load_upload_run(self, run_id: str) -> UploadRun:
        run = self.load_run(run_id)
        if not isinstance(run, UploadRun):
            raise RunStoreError(f"Run {run_id!r} is not an upload run")
        return run

    def _ensure_can_activate(
        self,
        run_id: str,
        *,
        replace_existing: bool,
    ) -> None:
        active_run_id = self.get_active_run_id(required=False)
        if not active_run_id or active_run_id == run_id or replace_existing:
            return
        active_run = self.load_run(active_run_id)
        if has_protected_progress(active_run):
            raise ProtectedActiveRunError(
                f"Active run {active_run_id!r} has protected progress"
            )
        raise ActiveRunExistsError(
            f"Active run {active_run_id!r} must be replaced explicitly"
        )


def compute_file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_upload_run(**kwargs: Any) -> UploadRun:
    store_root = kwargs.pop("store_root", None)
    return RunStore(store_root).create_upload_run(**kwargs)


def create_speed_probe_run(**kwargs: Any) -> SpeedProbeRun:
    store_root = kwargs.pop("store_root", None)
    return RunStore(store_root).create_speed_probe_run(**kwargs)


def load_run(run_id: str, *, store_root: str | Path | None = None) -> RunState:
    return RunStore(store_root).load_run(run_id)


def save_run(
    run: RunState,
    *,
    store_root: str | Path | None = None,
    touch_updated_at: bool = True,
) -> RunState:
    return RunStore(store_root).save_run(run, touch_updated_at=touch_updated_at)


def resolve_run_id(
    run_id: str | None = None,
    *,
    store_root: str | Path | None = None,
) -> str:
    return RunStore(store_root).resolve_run_id(run_id)


def resolve_run(
    run_id: str | None = None,
    *,
    store_root: str | Path | None = None,
) -> RunState:
    return RunStore(store_root).resolve_run(run_id)


def has_protected_progress(run: RunState) -> bool:
    if isinstance(run, UploadRun):
        return (
            bool(run.uploaded_questions)
            or bool(run.skip_events)
            or bool(run.cooldown_events)
            or run.next_question_index > run.start_question_index
            or run.status in PROTECTED_UPLOAD_STATUSES
        )
    return (
        bool(run.limit_events)
        or run.first_limit_at_question is not None
        or run.status in {"running", "cooldown", "paused"}
    )


def safe_status_snapshot(run: RunState, *, store_root: str | Path | None = None) -> dict[str, Any]:
    if isinstance(run, UploadRun):
        return {
            "kind": run.kind,
            "run_id": run.run_id,
            "status": run.status,
            "quiz_name": run.quiz_name,
            "quiz_file_basename": Path(run.quiz_file).name,
            "account_profile_id": run.account_profile_id,
            "speed": run.speed,
            "start_question_index": run.start_question_index,
            "next_question_index": run.next_question_index,
            "source_question_count": run.source_question_count,
            "uploaded_count": len(run.uploaded_questions),
            "skipped_count": len(run.skipped_questions),
            "cooldown_count": len(run.cooldown_events),
            "estimated_remaining_seconds": estimate_upload_remaining_seconds(run, store_root=store_root),
            "has_protected_progress": has_protected_progress(run),
            "last_error": _safe_error(run.last_error),
            "share_link": run.share_link,
            "auto_resume_enabled": run.auto_resume_enabled,
            "auto_resume_delay_seconds": run.auto_resume_delay_seconds,
            "auto_resume_next_at": run.auto_resume_next_at,
            "auto_resume_attempts": run.auto_resume_attempts,
            "auto_resume_last_job_id": run.auto_resume_last_job_id,
            "auto_resume_last_scheduled_at": run.auto_resume_last_scheduled_at,
            "updated_at": run.updated_at,
        }
    return {
        "kind": run.kind,
        "probe_id": run.probe_id,
        "status": run.status,
        "quiz_name": run.quiz_name,
        "source_quiz_file_basename": Path(run.source_quiz_file).name,
        "account_profile_id": run.account_profile_id,
        "first_limit_at_question": run.first_limit_at_question,
        "limit_event_count": len(run.limit_events),
        "cleanup_status": run.cleanup_status,
        "has_protected_progress": has_protected_progress(run),
        "last_error": _safe_error(run.last_error),
        "updated_at": run.updated_at,
    }


def estimate_upload_remaining_seconds(run: UploadRun, *, store_root: str | Path | None = None) -> int:
    if run.status in {"completed", "cancelled", "cancelled_replaced"}:
        return 0

    uploaded_count = len(run.uploaded_questions)
    skipped_count = len(run.skipped_questions)
    done_count = min(run.source_question_count, uploaded_count + skipped_count)
    remaining_questions = max(0, run.source_question_count - done_count)
    if remaining_questions <= 0:
        return 0

    profile = config.estimate_timing_profile(run.speed, runtime_dir=store_root)
    seconds = remaining_questions * float(profile["seconds_per_question"])
    long_pause_every = int(profile.get("long_pause_every") or 0)
    if long_pause_every > 0:
        seconds += (
            _future_pause_count(
                start_after_count=uploaded_count,
                total_count=run.source_question_count,
                every=long_pause_every,
            )
            * float(profile.get("long_pause_seconds") or 0)
        )

    cooldown_every = int(profile.get("cooldown_every_uploaded") or 0)
    if cooldown_every > 0:
        completed_cooldowns = {
            int(event.get("threshold_uploaded_count"))
            for event in run.cooldown_events
            if event.get("threshold_uploaded_count") is not None
        }
        seconds += (
            _future_pause_count(
                start_after_count=max(0, uploaded_count - 1),
                total_count=run.source_question_count - 1,
                every=cooldown_every,
                completed_thresholds=completed_cooldowns,
            )
            * float(profile.get("cooldown_seconds") or 0)
        )

    return max(0, int(seconds))


def _future_pause_count(
    *,
    start_after_count: int,
    total_count: int,
    every: int,
    completed_thresholds: set[int] | None = None,
) -> int:
    if every <= 0 or total_count <= 0:
        return 0
    completed_thresholds = completed_thresholds or set()
    count = 0
    first_threshold = ((max(0, start_after_count) // every) + 1) * every
    for threshold in range(first_threshold, total_count + 1, every):
        if threshold not in completed_thresholds:
            count += 1
    return count


def _runtime_root(root: str | Path | None) -> Path:
    if root is not None:
        return Path(root)
    from backend import config

    return Path(config.RUNTIME_DIR)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _run_id(run: RunState) -> str:
    if isinstance(run, UploadRun):
        return run.run_id
    return run.probe_id


def _run_kind(run: RunState) -> str:
    if isinstance(run, UploadRun):
        return run.kind
    return run.kind


def _known_field_values(model: type[RunState], data: Mapping[str, Any]) -> dict[str, Any]:
    names = {item.name for item in fields(model)}
    values = {name: data[name] for name in names if name in data}
    missing_required = [
        item.name
        for item in fields(model)
        if item.default is MISSING
        and item.default_factory is MISSING
        and item.name not in values
    ]
    if missing_required:
        required = ", ".join(missing_required)
        raise RunStoreError(f"Run state is missing required fields: {required}")
    return values


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RunStoreError(f"{path} must contain a JSON object")
    return data


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RunStoreError("Expected a list of integers")
    return [int(item) for item in value]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RunStoreError("Expected a list of objects")
    if not all(isinstance(item, dict) for item in value):
        raise RunStoreError("Expected a list of objects")
    return [dict(item) for item in value]


def _dict_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RunStoreError("Expected an object")
    return dict(value)


def _skip_event(
    source_question_index: int,
    *,
    reason: str,
    skipped_by: str,
    when: str,
) -> dict[str, Any]:
    return {
        "source_question_index": source_question_index,
        "reason": reason,
        "skipped_at": when,
        "skipped_by": skipped_by,
    }


def _safe_error(error: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if error is None:
        return None
    safe: dict[str, Any] = {}
    for key, value in error.items():
        lowered = str(key).lower()
        if any(part in lowered for part in SECRET_KEY_PARTS):
            continue
        if isinstance(value, Mapping):
            safe[str(key)] = _safe_error(value)
        elif isinstance(value, list):
            safe[str(key)] = [
                _safe_error(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            safe[str(key)] = value
    return safe
