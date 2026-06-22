"""Resumable upload orchestration for clean quiz JSON.

This module keeps Telegram I/O behind injected client and flow primitives so
tests can prove state transitions without touching live Telegram.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from backend import accounts, config, flow, runs, telegram_client_factory
from backend.flow import UnexpectedBotState
from backend.models import Question
from backend.pipeline.encoding import write_json_utf8
from backend.pipeline.review import (
    ReviewArtifact,
    UploadGateResult,
    parse_review_artifact,
    resolve_upload_gate,
)
from backend.pipeline.upload_adapter import (
    LegacyQuiz,
    clean_quiz_to_legacy_questions,
    load_clean_quiz,
)
from backend.pipeline.validation import ValidationReport, validate_clean_quiz

REVIEW_DECISIONS_FILENAME = "review-decisions.json"
UNDO_COMMAND = "/undo"


class UploadServiceError(ValueError):
    """Base upload service error."""


class UploadGateBlockedError(UploadServiceError):
    """Raised when validation/review artifacts do not allow upload."""

    def __init__(self, message: str, *, gate: UploadGateResult | None = None):
        super().__init__(message)
        self.gate = gate


class UploadConfirmationRequired(UploadServiceError):
    """Raised before rollback or skip-forward without explicit confirmation."""

    def __init__(self, action: str, **details: Any):
        super().__init__(f"{action} requires explicit confirmation")
        self.action = action
        self.details = details


class FlowPrimitives(Protocol):
    async def create_quiz(self, client: Any, quiz_name: str) -> None:
        ...

    async def upload_question(
        self,
        client: Any,
        q: Question,
        index_in_quiz: int,
        *,
        send_prelude: bool = True,
        shuffle_options: bool = False,
        shuffle_seed: int = 42,
    ) -> None:
        ...

    async def finish_quiz(self, client: Any) -> str:
        ...


@dataclass(slots=True)
class UploadPayload:
    clean_json: dict[str, Any]
    legacy_quiz: LegacyQuiz
    validation_report: ValidationReport
    review_artifact: ReviewArtifact
    gate: UploadGateResult


class UploadService:
    """Service for start/resume/continue upload flows."""

    def __init__(
        self,
        *,
        run_store: runs.RunStore | None = None,
        runtime_root: str | Path | None = None,
        account_store_root: str | Path | None = None,
        client_factory: Callable[[str], Any] | None = None,
        flow_primitives: FlowPrimitives | Any = flow,
        checkpoint_callback: Callable[[runs.UploadRun], None] | None = None,
    ):
        self.run_store = run_store or runs.RunStore(runtime_root)
        self.account_store_root = Path(account_store_root) if account_store_root is not None else None
        self.flow = flow_primitives
        self.checkpoint_callback = checkpoint_callback
        if client_factory is None:
            self.client_factory = self._default_client_factory
        else:
            self.client_factory = client_factory

    async def start_upload(
        self,
        *,
        quiz_file: str | Path,
        review_artifact_file: str | Path | None = None,
        quiz_name: str | None = None,
        account_profile_id: str | None = None,
        speed: str = "normal",
        start_from: int = 1,
        replace_active: bool = False,
    ) -> runs.UploadRun:
        payload = self._load_allowed_payload(
            quiz_file,
            review_artifact_file=review_artifact_file,
        )
        if start_from > payload.legacy_quiz.source_question_count + 1:
            raise UploadServiceError("start_from is out of range")
        settings = payload.legacy_quiz.settings
        profile_id = account_profile_id or accounts.current_profile(
            store_root=self.account_store_root,
        ).id
        title = quiz_name or payload.legacy_quiz.title
        run = self.run_store.create_upload_run(
            quiz_file=quiz_file,
            quiz_name=title,
            account_profile_id=profile_id,
            speed=speed,
            start_question_index=start_from,
            next_question_index=start_from,
            source_question_count=payload.legacy_quiz.source_question_count,
            context_send_mode=_context_send_mode(settings),
            shuffle_options=_bool_setting(settings, "shuffle_options", False),
            replace_active=replace_active,
        )
        self._store_run_review_artifact(run.run_id, payload.review_artifact)
        return await self._execute_upload_run(run.run_id, payload=payload)

    async def resume_upload_run(
        self,
        run_id: str | None = None,
        *,
        review_artifact_file: str | Path | None = None,
    ) -> runs.UploadRun:
        resolved_run_id = self.run_store.resolve_run_id(run_id)
        self.run_store.assert_quiz_hash_matches(resolved_run_id)
        payload = self._load_existing_payload(
            resolved_run_id,
            review_artifact_file=review_artifact_file,
        )
        return await self._execute_upload_run(resolved_run_id, payload=payload)

    async def continue_upload_run_from(
        self,
        run_id: str | None,
        question_index: int,
        *,
        review_artifact_file: str | Path | None = None,
        confirm_rollback: bool = False,
        confirm_skip_forward: bool = False,
        speed: str | None = None,
        context_send_mode: str | None = None,
        shuffle_options: bool | None = None,
    ) -> runs.UploadRun:
        resolved_run_id = self.run_store.resolve_run_id(run_id)
        self.run_store.assert_quiz_hash_matches(resolved_run_id)
        run = self._load_upload_run(resolved_run_id)
        run = self._apply_continue_settings(
            run,
            speed=speed,
            context_send_mode=context_send_mode,
            shuffle_options=shuffle_options,
        )
        if question_index < run.start_question_index:
            raise UploadServiceError(
                "continue_from cannot be before start_question_index for this draft"
            )
        if question_index > run.source_question_count + 1:
            raise UploadServiceError("continue_from is out of range")

        if question_index == run.next_question_index:
            return await self.resume_upload_run(
                resolved_run_id,
                review_artifact_file=review_artifact_file,
            )
        if question_index < run.next_question_index:
            return await self.rollback_upload_run(
                resolved_run_id,
                question_index,
                review_artifact_file=review_artifact_file,
                confirm_rollback=confirm_rollback,
                resume_after=True,
            )
        return await self.skip_forward_upload_run(
            resolved_run_id,
            question_index,
            review_artifact_file=review_artifact_file,
            confirm_skip_forward=confirm_skip_forward,
            resume_after=True,
            )

    def _apply_continue_settings(
        self,
        run: runs.UploadRun,
        *,
        speed: str | None = None,
        context_send_mode: str | None = None,
        shuffle_options: bool | None = None,
    ) -> runs.UploadRun:
        changed = False
        if speed is not None:
            if speed not in config.SPEED_PRESETS and speed != "auto":
                raise UploadServiceError(f"Unsupported speed mode: {speed!r}")
            if run.speed != speed:
                run.speed = speed
                changed = True
        if context_send_mode is not None:
            if context_send_mode not in {"once", "per-question"}:
                raise UploadServiceError("context_send_mode must be 'once' or 'per-question'")
            if run.context_send_mode != context_send_mode:
                run.context_send_mode = context_send_mode
                changed = True
        if shuffle_options is not None and run.shuffle_options != bool(shuffle_options):
            run.shuffle_options = bool(shuffle_options)
            changed = True
        return self.run_store.save_run(run) if changed else run

    async def rollback_upload_run(
        self,
        run_id: str | None,
        rollback_to: int,
        *,
        review_artifact_file: str | Path | None = None,
        confirm_rollback: bool = False,
        resume_after: bool = False,
    ) -> runs.UploadRun:
        resolved_run_id = self.run_store.resolve_run_id(run_id)
        self.run_store.assert_quiz_hash_matches(resolved_run_id)
        run = self._load_upload_run(resolved_run_id)
        if rollback_to < run.start_question_index or rollback_to > run.next_question_index:
            raise UploadServiceError("rollback_to is outside resumable range")
        to_undo = [
            index
            for index in sorted(run.uploaded_questions, reverse=True)
            if index >= rollback_to
        ]
        if not confirm_rollback:
            raise UploadConfirmationRequired(
                "rollback",
                run_id=resolved_run_id,
                rollback_to=rollback_to,
                undo_count=len(to_undo),
                source_question_indexes=to_undo,
            )

        run = await self._rollback_uploaded_questions(resolved_run_id, to_undo)
        if not resume_after:
            run.status = "paused"
            return self.run_store.save_run(run)
        payload = self._load_existing_payload(
            resolved_run_id,
            review_artifact_file=review_artifact_file,
        )
        return await self._execute_upload_run(resolved_run_id, payload=payload)

    async def skip_forward_upload_run(
        self,
        run_id: str | None,
        continue_from: int,
        *,
        review_artifact_file: str | Path | None = None,
        confirm_skip_forward: bool = False,
        resume_after: bool = False,
    ) -> runs.UploadRun:
        resolved_run_id = self.run_store.resolve_run_id(run_id)
        self.run_store.assert_quiz_hash_matches(resolved_run_id)
        run = self._load_upload_run(resolved_run_id)
        if continue_from <= run.next_question_index:
            raise UploadServiceError("continue_from must be greater than next_question_index")
        if continue_from > run.source_question_count + 1:
            raise UploadServiceError("continue_from is out of range")
        skipped = list(range(run.next_question_index, continue_from))
        if not confirm_skip_forward:
            raise UploadConfirmationRequired(
                "skip_forward",
                run_id=resolved_run_id,
                continue_from=continue_from,
                skipped_question_indexes=skipped,
            )

        run.status = "skipped_forward"
        self.run_store.save_run(run)
        for source_index in skipped:
            run = self.run_store.record_skip(
                resolved_run_id,
                source_index,
                reason="continue_from_skip_forward",
                skipped_by="user",
            )
            self._notify_checkpoint(run)
        if not resume_after:
            return run
        payload = self._load_existing_payload(
            resolved_run_id,
            review_artifact_file=review_artifact_file,
        )
        return await self._execute_upload_run(resolved_run_id, payload=payload)

    async def _execute_upload_run(
        self,
        run_id: str,
        *,
        payload: UploadPayload,
    ) -> runs.UploadRun:
        run = self._load_upload_run(run_id)
        questions_by_source = _questions_by_source(payload.legacy_quiz)
        speed_snapshot = _capture_speed_settings()
        _apply_upload_speed_preset(run.speed, uploaded_questions=len(run.uploaded_questions))
        run.status = "running"
        run.last_error = None
        if run.started_at is None:
            run.started_at = _utc_now()
        run = self.run_store.save_run(run)

        try:
            client_cm = await _maybe_await(self.client_factory(run.account_profile_id))
            async with client_cm as client:
                run = self._load_upload_run(run_id)
                if not _draft_created(run):
                    await self.flow.create_quiz(client, run.quiz_name)
                    run = self._load_upload_run(run_id)
                    run.last_bot_state = {
                        **(run.last_bot_state or {}),
                        "draft_created": True,
                    }
                    run = self.run_store.save_run(run)

                last_context_key: tuple[str, str, tuple[str, ...]] | None = None
                while run.next_question_index <= run.source_question_count:
                    run = self._load_upload_run(run_id)
                    if run.status in {"paused", "cancelled"}:
                        return run
                    source_index = run.next_question_index
                    if source_index in run.skipped_questions:
                        run.next_question_index = source_index + 1
                        run = self.run_store.save_run(run)
                        self._notify_checkpoint(run)
                        continue
                    if source_index in set(payload.gate.skipped_question_indexes):
                        run = self.run_store.record_skip(
                            run_id,
                            source_index,
                            reason="review_decision",
                            skipped_by="review",
                        )
                        self._notify_checkpoint(run)
                        continue

                    question = questions_by_source.get(source_index)
                    if question is None:
                        raise UploadServiceError(
                            f"No upload question for source index {source_index}"
                        )
                    run = await self._auto_cooldown_if_due(run_id, run)
                    active_speed_preset = _apply_upload_speed_preset(
                        run.speed,
                        uploaded_questions=len(run.uploaded_questions),
                    )
                    send_prelude, last_context_key = _prelude_decision(
                        question,
                        context_send_mode=run.context_send_mode,
                        last_context_key=last_context_key,
                    )
                    draft_question_index = len(run.uploaded_questions) + 1
                    await self.flow.upload_question(
                        client,
                        question,
                        index_in_quiz=draft_question_index,
                        send_prelude=send_prelude,
                        shuffle_options=run.shuffle_options,
                    )
                    run = self.run_store.record_question_uploaded(
                        run_id,
                        source_index,
                        last_bot_state={
                            "source_question_index": source_index,
                            "draft_question_index": draft_question_index,
                            "speed": run.speed,
                            "active_speed_preset": active_speed_preset,
                        },
                    )
                    self._notify_checkpoint(run)

                share_link = await self.flow.finish_quiz(client)
                run = self._load_upload_run(run_id)
                run.status = "completed"
                run.share_link = share_link
                return self.run_store.save_run(run)
        except KeyboardInterrupt as exc:
            return self._pause_for_user(run_id, exc)
        except asyncio.CancelledError as exc:
            return self._pause_for_user(run_id, exc)
        except asyncio.TimeoutError as exc:
            return self._pause_or_fail(run_id, exc)
        except UnexpectedBotState as exc:
            return self._pause_or_fail(run_id, exc)
        except (RuntimeError, ValueError) as exc:
            if _is_recoverable_runtime_error(exc):
                return self._pause_or_fail(run_id, exc)
            raise
        finally:
            _restore_speed_settings(speed_snapshot)

    async def _rollback_uploaded_questions(
        self,
        run_id: str,
        source_indexes_desc: list[int],
    ) -> runs.UploadRun:
        run = self._load_upload_run(run_id)
        run.status = "rollback"
        run = self.run_store.save_run(run)
        client_cm = await _maybe_await(self.client_factory(run.account_profile_id))
        async with client_cm as client:
            for position, source_index in enumerate(source_indexes_desc, start=1):
                await self._send_undo(client)
                run = self._load_upload_run(run_id)
                run.uploaded_questions = [
                    index for index in run.uploaded_questions if index != source_index
                ]
                run.next_question_index = min(run.next_question_index, source_index)
                run.status = "rollback"
                run.last_bot_state = {
                    "undo_source_question_index": source_index,
                    "undo_count_done": position,
                    "undo_count_total": len(source_indexes_desc),
                }
                run = self.run_store.save_run(run)
                self._notify_checkpoint(run)
        return self._load_upload_run(run_id)

    async def _send_undo(self, client: Any) -> None:
        undo = getattr(self.flow, "undo_question", None)
        if callable(undo):
            await undo(client)
            return
        await client.send_text(UNDO_COMMAND)

    def _load_allowed_payload(
        self,
        quiz_file: str | Path,
        *,
        review_artifact_file: str | Path | None,
    ) -> UploadPayload:
        clean_json = load_clean_quiz(quiz_file)
        validation_report = validate_clean_quiz(clean_json)
        review_artifact = self._load_review_artifact(
            quiz_file=quiz_file,
            run_id=None,
            review_artifact_file=review_artifact_file,
        )
        gate = resolve_upload_gate(validation_report, review_artifact)
        if not gate.allowed:
            raise UploadGateBlockedError(
                f"Upload blocked by review gate: {gate.reason}",
                gate=gate,
            )
        selected_indexes = [
            index
            for index in range(1, validation_report.question_count + 1)
            if index not in set(gate.skipped_question_indexes)
        ]
        legacy_quiz = clean_quiz_to_legacy_questions(
            clean_json,
            selected_indexes=selected_indexes,
        )
        return UploadPayload(
            clean_json=clean_json,
            legacy_quiz=legacy_quiz,
            validation_report=validation_report,
            review_artifact=review_artifact,
            gate=gate,
        )

    def _load_existing_payload(
        self,
        run_id: str,
        *,
        review_artifact_file: str | Path | None,
    ) -> UploadPayload:
        run = self._load_upload_run(run_id)
        return self._load_allowed_payload(
            run.quiz_file,
            review_artifact_file=review_artifact_file
            or self._run_review_artifact_path(run_id),
        )

    def _load_review_artifact(
        self,
        *,
        quiz_file: str | Path,
        run_id: str | None,
        review_artifact_file: str | Path | None,
    ) -> ReviewArtifact:
        artifact_path = Path(
            review_artifact_file
            or (
                self._run_review_artifact_path(run_id)
                if run_id is not None
                else Path(quiz_file).with_name(REVIEW_DECISIONS_FILENAME)
            )
        )
        if not artifact_path.exists():
            raise UploadGateBlockedError(
                f"Review artifact is required before upload: {artifact_path}"
            )
        try:
            raw = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UploadGateBlockedError(
                f"Review artifact is not valid JSON: {artifact_path}"
            ) from exc
        if not isinstance(raw, Mapping):
            raise UploadGateBlockedError("Review artifact must be a JSON object")
        return parse_review_artifact(raw)

    def _store_run_review_artifact(
        self,
        run_id: str,
        review_artifact: ReviewArtifact,
    ) -> None:
        write_json_utf8(
            self._run_review_artifact_path(run_id),
            review_artifact.to_dict(),
        )

    def _run_review_artifact_path(self, run_id: str) -> Path:
        return self.run_store.state_path(run_id).parent / REVIEW_DECISIONS_FILENAME

    def _default_client_factory(self, profile_id: str) -> Any:
        return telegram_client_factory.create_client_for_profile(
            profile_id,
            store_root=self.account_store_root,
        )

    def _load_upload_run(self, run_id: str) -> runs.UploadRun:
        run = self.run_store.load_run(run_id)
        if not isinstance(run, runs.UploadRun):
            raise UploadServiceError(f"Run {run_id!r} is not an upload run")
        return run

    def _pause_for_user(
        self,
        run_id: str,
        exc: BaseException,
    ) -> runs.UploadRun:
        return self.run_store.update_status(
            run_id,
            "paused",
            last_error={
                "code": "paused_by_user",
                "kind": exc.__class__.__name__,
                "message": str(exc),
            },
        )

    def _pause_or_fail(
        self,
        run_id: str,
        exc: BaseException,
    ) -> runs.UploadRun:
        status, error = _classified_error(exc)
        return self.run_store.update_status(run_id, status, last_error=error)

    def _notify_checkpoint(self, run: runs.UploadRun) -> None:
        if self.checkpoint_callback is not None:
            self.checkpoint_callback(run)

    async def _auto_cooldown_if_due(
        self,
        run_id: str,
        run: runs.UploadRun,
    ) -> runs.UploadRun:
        threshold = _due_auto_cooldown_threshold(run)
        if threshold is None:
            return run

        duration = config.rand_delay(config.AUTO_SPEED_POLICY["cooldown_duration"])
        started_at = _utc_now()
        run.last_bot_state = {
            **(run.last_bot_state or {}),
            "auto_cooldown": {
                "threshold_uploaded_count": threshold,
                "duration_seconds": round(duration, 3),
                "started_at": started_at,
                "speed": run.speed,
                "active_speed_preset": config.auto_speed_preset(
                    len(run.uploaded_questions)
                ),
            },
        }
        run = self.run_store.save_run(run)
        self._notify_checkpoint(run)
        await asyncio.sleep(duration)

        run = self._load_upload_run(run_id)
        run.cooldown_events.append(
            {
                "threshold_uploaded_count": threshold,
                "duration_seconds": round(duration, 3),
                "started_at": started_at,
                "finished_at": _utc_now(),
                "reason": "auto_speed_cooldown",
            }
        )
        run.last_bot_state = {
            **(run.last_bot_state or {}),
            "auto_cooldown": {
                "threshold_uploaded_count": threshold,
                "duration_seconds": round(duration, 3),
                "finished_at": _utc_now(),
                "speed": run.speed,
                "active_speed_preset": config.auto_speed_preset(
                    len(run.uploaded_questions)
                ),
            },
        }
        return self.run_store.save_run(run)


def _questions_by_source(legacy_quiz: LegacyQuiz) -> dict[int, Question]:
    return {
        int(raw["source_question_index"]): question
        for raw, question in zip(legacy_quiz.raw_questions, legacy_quiz.questions)
    }


def _context_send_mode(settings: Mapping[str, Any]) -> str:
    value = settings.get("context_send_mode")
    if value in {"once", "per-question"}:
        return str(value)
    return "per-question"


def _bool_setting(settings: Mapping[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key)
    return value if isinstance(value, bool) else default


def _draft_created(run: runs.UploadRun) -> bool:
    return bool((run.last_bot_state or {}).get("draft_created") or run.uploaded_questions)


def _prelude_decision(
    question: Question,
    *,
    context_send_mode: str,
    last_context_key: tuple[str, str, tuple[str, ...]] | None,
) -> tuple[bool, tuple[str, str, tuple[str, ...]] | None]:
    context_key = _context_key(question)
    if context_send_mode == "per-question":
        return True, context_key
    send_prelude = context_key is not None and context_key != last_context_key
    return send_prelude, context_key


def _context_key(question: Question) -> tuple[str, str, tuple[str, ...]] | None:
    context_title = question.context_title.strip()
    context = question.context.strip()
    media = tuple(question.media or [])
    if not context_title and not context and not media:
        return None
    return context_title, context, media


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _apply_upload_speed_preset(speed: str, *, uploaded_questions: int) -> str:
    preset = (
        config.auto_speed_preset(uploaded_questions)
        if speed == "auto"
        else speed
    )
    config.apply_speed_mode(preset)
    return preset


def _due_auto_cooldown_threshold(run: runs.UploadRun) -> int | None:
    if run.speed != "auto":
        return None
    interval = int(config.AUTO_SPEED_POLICY["cooldown_every_uploaded"])
    if interval < 1:
        return None
    uploaded_count = len(run.uploaded_questions)
    if uploaded_count < interval:
        return None
    threshold = (uploaded_count // interval) * interval
    completed_thresholds = {
        int(event.get("threshold_uploaded_count"))
        for event in run.cooldown_events
        if event.get("threshold_uploaded_count") is not None
    }
    if threshold in completed_thresholds:
        return None
    return threshold


def _is_recoverable_runtime_error(exc: RuntimeError | ValueError) -> bool:
    text = str(exc).lower()
    name = exc.__class__.__name__.lower()
    return (
        "floodwait" in name
        or "floodwait" in text
        or "too many requests" in text
        or "too many incoming messages" in text
        or "retry" in text and "exhaust" in text
    )


def _classified_error(exc: BaseException) -> tuple[str, dict[str, Any]]:
    if isinstance(exc, asyncio.TimeoutError):
        return "paused", {
            "code": "telegram_timeout",
            "kind": exc.__class__.__name__,
            "message": str(exc),
        }
    if isinstance(exc, UnexpectedBotState):
        return "failed", {
            "code": "unexpected_bot_state",
            "kind": exc.__class__.__name__,
            "message": str(exc),
        }
    text = str(exc)
    lowered = text.lower()
    if "too many incoming messages" in lowered:
        return "paused", {
            "code": "telegram_too_many_incoming_messages",
            "kind": exc.__class__.__name__,
            "message": text,
        }
    if "too many requests" in lowered:
        return "paused", {
            "code": "telegram_too_many_requests",
            "kind": exc.__class__.__name__,
            "message": text,
        }
    if "floodwait" in lowered or "floodwait" in exc.__class__.__name__.lower():
        error: dict[str, Any] = {
            "code": "telegram_flood_wait",
            "kind": exc.__class__.__name__,
            "message": text,
        }
        seconds = getattr(exc, "seconds", None)
        if isinstance(seconds, int):
            error["retry_after_seconds"] = seconds
        return "paused", error
    if "retry" in lowered and "exhaust" in lowered:
        return "paused", {
            "code": "telegram_retry_exhausted",
            "kind": exc.__class__.__name__,
            "message": text,
        }
    return "failed", {
        "code": "upload_failed",
        "kind": exc.__class__.__name__,
        "message": text,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _capture_speed_settings() -> dict[str, Any]:
    return {
        "DELAY_BETWEEN_MESSAGES": config.DELAY_BETWEEN_MESSAGES,
        "DELAY_BETWEEN_QUESTIONS": config.DELAY_BETWEEN_QUESTIONS,
        "LONG_PAUSE_EVERY_N_QUESTIONS": config.LONG_PAUSE_EVERY_N_QUESTIONS,
        "LONG_PAUSE_DURATION": config.LONG_PAUSE_DURATION,
    }


def _restore_speed_settings(snapshot: Mapping[str, Any]) -> None:
    for name, value in snapshot.items():
        setattr(config, name, value)
