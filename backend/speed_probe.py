"""Disposable speed-threshold probe service for @QuizBot uploads.

The probe reuses the existing QuizBot flow through injected primitives, so tests
can exercise all state transitions without Telegram I/O.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from backend import accounts, config, flow, runs, telegram_client_factory
from backend.flow import UnexpectedBotState
from backend.models import Question
from backend.pipeline.encoding import write_json_utf8
from backend.pipeline.upload_adapter import (
    LegacyQuiz,
    clean_quiz_to_legacy_questions,
    load_clean_quiz,
)
from backend.pipeline.validation import validate_clean_quiz

FAST_THRESHOLD_POLICY = "fast-threshold"
REPORT_FILENAME = "speed-probe-report.json"
_PROBE_SPEED_PRESET = "fast"


class SpeedProbeError(ValueError):
    """Base speed probe error."""


class SpeedProbePolicyError(SpeedProbeError):
    """Raised when an unsupported probe policy is requested."""


class SpeedProbeStateError(SpeedProbeError):
    """Raised when a stored run cannot be resumed as a speed probe."""


class SpeedProbeActiveProfileError(SpeedProbeError):
    """Raised when a probe would silently burn the active/default profile.

    A speed probe deliberately runs at the fast threshold and can trip Telegram
    limits on whatever account it touches. To avoid quietly spending the limits
    of the active production profile, the caller must either select an explicit
    profile or opt in to probing the active one.
    """


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
class SpeedProbeReport:
    probe_id: str
    quiz_name: str
    account_profile_id: str
    source_quiz_file: str
    source_quiz_file_hash: str
    question_count: int
    delay_policy: dict[str, Any]
    cleanup_status: str = "manual_required"
    status: str = "running"
    questions_attempted: int = 0
    questions_confirmed: int = 0
    next_question_index: int = 1
    first_limit_at_question: int | None = None
    limit_events: list[dict[str, Any]] = field(default_factory=list)
    question_timings: list[dict[str, Any]] = field(default_factory=list)
    last_error: dict[str, Any] | None = None
    share_link: str | None = None
    draft_created: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "quiz_name": self.quiz_name,
            "account_profile_id": self.account_profile_id,
            "source_quiz_file": self.source_quiz_file,
            "source_quiz_file_hash": self.source_quiz_file_hash,
            "question_count": self.question_count,
            "delay_policy": dict(self.delay_policy),
            "cleanup_status": self.cleanup_status,
            "status": self.status,
            "questions_attempted": self.questions_attempted,
            "questions_confirmed": self.questions_confirmed,
            "next_question_index": self.next_question_index,
            "first_limit_at_question": self.first_limit_at_question,
            "limit_events": [dict(item) for item in self.limit_events],
            "question_timings": [dict(item) for item in self.question_timings],
            "last_error": dict(self.last_error) if self.last_error else None,
            "share_link": self.share_link,
            "draft_created": self.draft_created,
            "recommended_safe_policy": _recommendation_placeholder(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SpeedProbeReport":
        if not isinstance(data, Mapping):
            raise SpeedProbeStateError("Speed probe report must be an object")
        return cls(
            probe_id=str(data["probe_id"]),
            quiz_name=str(data["quiz_name"]),
            account_profile_id=str(data["account_profile_id"]),
            source_quiz_file=str(data["source_quiz_file"]),
            source_quiz_file_hash=str(data["source_quiz_file_hash"]),
            question_count=int(data["question_count"]),
            delay_policy=dict(data.get("delay_policy") or {}),
            cleanup_status=str(data.get("cleanup_status") or "manual_required"),
            status=str(data.get("status") or "running"),
            questions_attempted=int(data.get("questions_attempted") or 0),
            questions_confirmed=int(data.get("questions_confirmed") or 0),
            next_question_index=int(data.get("next_question_index") or 1),
            first_limit_at_question=(
                int(data["first_limit_at_question"])
                if data.get("first_limit_at_question") is not None
                else None
            ),
            limit_events=_dict_list(data.get("limit_events")),
            question_timings=_dict_list(data.get("question_timings")),
            last_error=(
                dict(data["last_error"])
                if isinstance(data.get("last_error"), Mapping)
                else None
            ),
            share_link=(
                str(data["share_link"]) if data.get("share_link") is not None else None
            ),
            draft_created=bool(data.get("draft_created", False)),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


class SpeedProbeService:
    """Run and resume disposable speed probes with a persistent run ledger."""

    def __init__(
        self,
        *,
        run_store: runs.RunStore | None = None,
        runtime_root: str | Path | None = None,
        account_store_root: str | Path | None = None,
        client_factory: Callable[[str], Any] | None = None,
        flow_primitives: FlowPrimitives | Any = flow,
        monotonic: Callable[[], float] = time.perf_counter,
    ):
        self.run_store = run_store or runs.RunStore(runtime_root)
        self.account_store_root = (
            Path(account_store_root) if account_store_root is not None else None
        )
        self.flow = flow_primitives
        self.monotonic = monotonic
        if client_factory is None:
            self.client_factory = self._default_client_factory
        else:
            self.client_factory = client_factory

    async def start_probe(
        self,
        *,
        quiz_file: str | Path,
        question_count: int,
        policy: str = FAST_THRESHOLD_POLICY,
        account_profile_id: str | None = None,
        confirm_active: bool = False,
        replace_active: bool = False,
    ) -> runs.SpeedProbeRun:
        delay_policy = _delay_policy(policy)
        legacy_quiz = _load_probe_quiz(quiz_file, question_count=question_count)
        normalized_profile_id = (account_profile_id or "").strip() or None
        if normalized_profile_id is None:
            if not confirm_active:
                raise SpeedProbeActiveProfileError(
                    "Speed probe would run against the active/default account "
                    "profile and burn its limits. Select an explicit profile or "
                    "pass confirm_active=True to probe the active one."
                )
            profile_id = accounts.current_profile(
                store_root=self.account_store_root,
            ).id
        else:
            profile_id = normalized_profile_id
        quiz_name = _disposable_quiz_name()
        run = self.run_store.create_speed_probe_run(
            source_quiz_file=quiz_file,
            quiz_name=quiz_name,
            account_profile_id=profile_id,
            delay_policy=delay_policy,
            replace_active=replace_active,
        )
        run.cleanup_status = "manual_required"
        run = self.run_store.save_run(run)
        report = SpeedProbeReport(
            probe_id=run.probe_id,
            quiz_name=run.quiz_name,
            account_profile_id=run.account_profile_id,
            source_quiz_file=run.source_quiz_file,
            source_quiz_file_hash=run.source_quiz_file_hash,
            question_count=question_count,
            delay_policy=delay_policy,
            cleanup_status=run.cleanup_status,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
        self._write_report(report)
        return await self._execute_probe_run(run.probe_id, legacy_quiz=legacy_quiz)

    async def resume_probe_run(self, run_id: str | None = None) -> runs.SpeedProbeRun:
        resolved_run_id = self.run_store.resolve_run_id(run_id)
        run = self._load_probe_run(resolved_run_id)
        report = self.load_report(run.probe_id)
        current_hash = runs.compute_file_sha256(run.source_quiz_file)
        if current_hash != run.source_quiz_file_hash:
            raise runs.QuizHashMismatchError(
                f"Quiz file hash mismatch for probe {run.probe_id!r}; refusing resume"
            )
        legacy_quiz = _load_probe_quiz(
            run.source_quiz_file,
            question_count=report.question_count,
        )
        return await self._execute_probe_run(run.probe_id, legacy_quiz=legacy_quiz)

    def report_path(self, run_id: str) -> Path:
        return self.run_store.state_path(run_id).parent / REPORT_FILENAME

    def load_report(self, run_id: str) -> SpeedProbeReport:
        import json

        path = self.report_path(run_id)
        if not path.exists():
            raise SpeedProbeStateError(f"Speed probe report was not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SpeedProbeReport.from_dict(raw)

    async def _execute_probe_run(
        self,
        run_id: str,
        *,
        legacy_quiz: LegacyQuiz,
    ) -> runs.SpeedProbeRun:
        run = self._load_probe_run(run_id)
        report = self.load_report(run_id)
        run.status = "running"
        run.last_error = None
        run.cleanup_status = "manual_required"
        run = self.run_store.save_run(run)
        report.status = run.status
        report.last_error = None
        report.cleanup_status = run.cleanup_status
        self._write_report(report)

        timing_profile = config.build_timing_profile(_PROBE_SPEED_PRESET)
        try:
            async with telegram_client_factory.session_lock_for_profile(
                run.account_profile_id,
                store_root=self.account_store_root,
                config_module=config,
            ):
                client_cm = await _maybe_await(self.client_factory(run.account_profile_id))
                setattr(client_cm, "timing_profile", timing_profile)
                async with client_cm as client:
                    if not report.draft_created:
                        await self.flow.create_quiz(client, run.quiz_name)
                        report.draft_created = True
                        self._write_report(report)

                    questions_by_source = _questions_by_source(legacy_quiz)
                    while report.next_question_index <= report.question_count:
                        source_index = report.next_question_index
                        question = questions_by_source.get(source_index)
                        if question is None:
                            raise SpeedProbeStateError(
                                f"No probe question for source index {source_index}"
                            )
                        started = self.monotonic()
                        report.questions_attempted = max(
                            report.questions_attempted,
                            source_index,
                        )
                        self._write_report(report)
                        try:
                            await self.flow.upload_question(
                                client,
                                question,
                                index_in_quiz=report.questions_confirmed + 1,
                                send_prelude=True,
                                shuffle_options=False,
                            )
                        except (Exception, KeyboardInterrupt, asyncio.CancelledError) as exc:
                            duration = self.monotonic() - started
                            return self._record_probe_error(
                                run_id,
                                report,
                                exc,
                                source_question_index=source_index,
                                duration_seconds=duration,
                            )

                        duration = self.monotonic() - started
                        report.questions_confirmed += 1
                        report.next_question_index = source_index + 1
                        report.question_timings.append(
                            _timing_event(
                                source_question_index=source_index,
                                status="confirmed",
                                duration_seconds=duration,
                            )
                        )
                        self._write_report(report)

                    share_link = await self.flow.finish_quiz(client)
                    run = self._load_probe_run(run_id)
                    run.status = "completed"
                    run.cleanup_status = "manual_required"
                    run.last_error = None
                    saved = self.run_store.save_run(run)
                    report.status = saved.status
                    report.cleanup_status = saved.cleanup_status
                    report.share_link = share_link
                    report.last_error = None
                    self._write_report(report)
                    return saved
        except (Exception, KeyboardInterrupt, asyncio.CancelledError) as exc:
            report = self.load_report(run_id)
            source_index = min(
                max(1, report.next_question_index),
                max(1, report.question_count),
            )
            return self._record_probe_error(
                run_id,
                report,
                exc,
                source_question_index=source_index,
                duration_seconds=0.0,
            )

    def _record_probe_error(
        self,
        run_id: str,
        report: SpeedProbeReport,
        exc: BaseException,
        *,
        source_question_index: int,
        duration_seconds: float,
    ) -> runs.SpeedProbeRun:
        status, error, is_limit = _classified_probe_error(exc)
        report.question_timings.append(
            _timing_event(
                source_question_index=source_question_index,
                status="limit" if is_limit else "failed",
                duration_seconds=duration_seconds,
                error=error,
            )
        )
        report.last_error = error
        report.status = status
        if is_limit:
            event = {
                "source_question_index": source_question_index,
                "question_index": source_question_index,
                "kind": error["code"],
                "message": error.get("message", ""),
                "delay_policy_snapshot": dict(report.delay_policy),
                "recorded_at": _utc_now(),
            }
            report.first_limit_at_question = (
                report.first_limit_at_question or source_question_index
            )
            report.limit_events.append(event)
        self._write_report(report)

        run = self._load_probe_run(run_id)
        run.status = status
        run.last_error = error
        run.first_limit_at_question = report.first_limit_at_question
        run.limit_events = [dict(item) for item in report.limit_events]
        run.cleanup_status = "manual_required"
        return self.run_store.save_run(run)

    def _write_report(self, report: SpeedProbeReport) -> None:
        report.updated_at = _utc_now()
        write_json_utf8(self.report_path(report.probe_id), report.to_dict())

    def _load_probe_run(self, run_id: str) -> runs.SpeedProbeRun:
        run = self.run_store.load_run(run_id)
        if not isinstance(run, runs.SpeedProbeRun):
            raise SpeedProbeStateError(f"Run {run_id!r} is not a speed probe run")
        return run

    def _default_client_factory(self, profile_id: str) -> Any:
        return telegram_client_factory.create_client_for_profile(
            profile_id,
            store_root=self.account_store_root,
        )


def _load_probe_quiz(quiz_file: str | Path, *, question_count: int) -> LegacyQuiz:
    if question_count < 1:
        raise SpeedProbeError("questions must be >= 1")
    clean_json = load_clean_quiz(quiz_file)
    report = validate_clean_quiz(clean_json)
    if report.has_hard_errors:
        raise SpeedProbeError("Probe quiz has validation hard errors")
    if question_count > report.question_count:
        raise SpeedProbeError(
            f"questions={question_count} exceeds quiz question count {report.question_count}"
        )
    return clean_quiz_to_legacy_questions(
        clean_json,
        selected_indexes=range(1, question_count + 1),
    )


def _delay_policy(policy: str) -> dict[str, Any]:
    if policy != FAST_THRESHOLD_POLICY:
        raise SpeedProbePolicyError(f"Unsupported speed probe policy: {policy!r}")
    return {
        "mode": FAST_THRESHOLD_POLICY,
        "base_preset": "fast",
        "preventive_cooldown": False,
        "auto_cooldown_on_limit": False,
    }


def _disposable_quiz_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H-%M-%S")
    return f"SPEED PROBE {stamp}"


def _questions_by_source(legacy_quiz: LegacyQuiz) -> dict[int, Question]:
    return {
        int(raw["source_question_index"]): question
        for raw, question in zip(legacy_quiz.raw_questions, legacy_quiz.questions)
    }


def _classified_probe_error(
    exc: BaseException,
) -> tuple[str, dict[str, Any], bool]:
    if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
        return "paused", {
            "code": "paused_by_user",
            "kind": exc.__class__.__name__,
            "message": str(exc),
        }, False
    if isinstance(exc, asyncio.TimeoutError):
        return "paused", {
            "code": "telegram_timeout",
            "kind": exc.__class__.__name__,
            "message": str(exc),
        }, True
    if isinstance(exc, UnexpectedBotState):
        return "failed", {
            "code": "unexpected_bot_state",
            "kind": exc.__class__.__name__,
            "message": str(exc),
        }, False

    text = str(exc)
    lowered = text.lower()
    if "too many incoming messages" in lowered:
        return "paused", {
            "code": "telegram_too_many_incoming_messages",
            "kind": exc.__class__.__name__,
            "message": text,
        }, True
    if "too many requests" in lowered:
        return "paused", {
            "code": "telegram_too_many_requests",
            "kind": exc.__class__.__name__,
            "message": text,
        }, True
    if "floodwait" in lowered or "floodwait" in exc.__class__.__name__.lower():
        error: dict[str, Any] = {
            "code": "telegram_flood_wait",
            "kind": exc.__class__.__name__,
            "message": text,
        }
        seconds = getattr(exc, "seconds", None)
        if isinstance(seconds, int):
            error["retry_after_seconds"] = seconds
        return "paused", error, True
    return "failed", {
        "code": "speed_probe_failed",
        "kind": exc.__class__.__name__,
        "message": text,
    }, False


def _timing_event(
    *,
    source_question_index: int,
    status: str,
    duration_seconds: float,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "source_question_index": source_question_index,
        "question_index": source_question_index,
        "status": status,
        "duration_seconds": round(max(0.0, duration_seconds), 6),
        "recorded_at": _utc_now(),
    }
    if error is not None:
        event["error"] = dict(error)
    return event


def _recommendation_placeholder() -> dict[str, Any]:
    return {
        "status": "manual_review_required",
        "message": (
            "Analyze this probe report manually before changing production pacing."
        ),
        "between_questions": None,
        "long_pause_every": None,
        "long_pause_duration": None,
    }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SpeedProbeStateError("Expected a list of objects")
    if not all(isinstance(item, Mapping) for item in value):
        raise SpeedProbeStateError("Expected a list of objects")
    return [dict(item) for item in value]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
