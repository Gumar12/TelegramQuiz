import asyncio
import hashlib
import json
import re
from pathlib import Path

import pytest

from backend import config, runs
from backend.pipeline.review import build_review_artifact
from backend.pipeline.validation import validate_clean_quiz_file
from backend.upload_service import (
    UNDO_COMMAND,
    UploadConfirmationRequired,
    UploadGateBlockedError,
    UploadService,
)


def _question(index: int) -> dict:
    marker = hashlib.sha256(f"question-{index}".encode("ascii")).hexdigest()
    return {
        "type": "question",
        "question": f"Question {index} unique marker {marker}?",
        "options": [{"text": "A"}, {"text": "B"}],
        "answers": [1],
        "mode": "single",
    }


def _quiz_file(tmp_path: Path, count: int) -> Path:
    path = tmp_path / "quiz.clean.json"
    path.write_text(
        json.dumps(
            {
                "title": "Fake upload quiz",
                "settings": {
                    "context_send_mode": "per-question",
                    "shuffle_options": False,
                },
                "items": [_question(index) for index in range(1, count + 1)],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _review_file(tmp_path: Path, quiz_path: Path, *, name: str = "review-decisions.json") -> Path:
    report = validate_clean_quiz_file(quiz_path)
    artifact = build_review_artifact(quiz_file_hash=report.quiz_file_hash)
    path = tmp_path / name
    path.write_text(
        json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


class FakeClient:
    def __init__(self, profile_id: str):
        self.profile_id = profile_id
        self.sent_text: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def send_text(self, text: str):
        self.sent_text.append(text)


class FakeClientFactory:
    def __init__(self):
        self.clients: list[FakeClient] = []

    def __call__(self, profile_id: str) -> FakeClient:
        client = FakeClient(profile_id)
        self.clients.append(client)
        return client


class FakeFlow:
    def __init__(self, failures: dict[int, BaseException] | None = None):
        self.failures = failures or {}
        self.created: list[str] = []
        self.uploaded: list[dict] = []
        self.speed_snapshots: list[tuple[float, float]] = []
        self.finished = 0

    async def create_quiz(self, client, quiz_name: str) -> None:
        self.created.append(quiz_name)

    async def upload_question(
        self,
        client,
        q,
        index_in_quiz: int,
        *,
        send_prelude: bool = True,
        shuffle_options: bool = False,
        shuffle_seed: int = 42,
    ) -> None:
        source_index = _source_index(q.question)
        self.speed_snapshots.append(config.DELAY_BETWEEN_QUESTIONS)
        failure = self.failures.get(source_index)
        if failure is not None:
            raise failure
        self.uploaded.append(
            {
                "source": source_index,
                "draft": index_in_quiz,
                "send_prelude": send_prelude,
                "shuffle_options": shuffle_options,
            }
        )

    async def finish_quiz(self, client) -> str:
        self.finished += 1
        return "https://t.me/QuizBot?start=fake"


def _source_index(text: str) -> int:
    match = re.search(r"Question (\d+)", text)
    assert match is not None
    return int(match.group(1))


def _service(tmp_path: Path, flow: FakeFlow, *, checkpoints: list[dict] | None = None):
    factory = FakeClientFactory()
    store = runs.RunStore(tmp_path / "runtime")
    callback = None
    if checkpoints is not None:
        callback = lambda run: checkpoints.append(run.to_dict())
    service = UploadService(
        run_store=store,
        client_factory=factory,
        flow_primitives=flow,
        checkpoint_callback=callback,
    )
    return service, store, factory


def _create_uploaded_run(
    store: runs.RunStore,
    quiz_path: Path,
    *,
    uploaded: list[int],
    source_count: int,
    run_id: str = "run",
) -> runs.UploadRun:
    run = store.create_upload_run(
        run_id=run_id,
        quiz_file=quiz_path,
        quiz_name="Existing",
        account_profile_id="default",
        source_question_count=source_count,
    )
    for source_index in uploaded:
        run = store.record_question_uploaded(run_id, source_index)
    run.status = "paused"
    return store.save_run(run)


def test_new_upload_starts_at_question_1_and_checkpoints_after_each_fake_ack(tmp_path):
    quiz_path = _quiz_file(tmp_path, 3)
    review_path = _review_file(tmp_path, quiz_path)
    checkpoints: list[dict] = []
    flow = FakeFlow()
    service, store, _factory = _service(tmp_path, flow, checkpoints=checkpoints)

    run = asyncio.run(
        service.start_upload(
            quiz_file=quiz_path,
            review_artifact_file=review_path,
            account_profile_id="default",
        )
    )

    assert run.status == "completed"
    assert [item["source"] for item in flow.uploaded] == [1, 2, 3]
    assert [item["draft"] for item in flow.uploaded] == [1, 2, 3]
    assert [
        (item["uploaded_questions"], item["next_question_index"])
        for item in checkpoints
    ] == [([1], 2), ([1, 2], 3), ([1, 2, 3], 4)]
    persisted = store.load_run(run.run_id)
    assert persisted.uploaded_questions == [1, 2, 3]


def test_start_from_39_skips_prior_questions_and_uploads_source_39_first(tmp_path):
    quiz_path = _quiz_file(tmp_path, 40)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow()
    service, store, _factory = _service(tmp_path, flow)

    run = asyncio.run(
        service.start_upload(
            quiz_file=quiz_path,
            review_artifact_file=review_path,
            account_profile_id="default",
            start_from=39,
        )
    )

    assert flow.uploaded[0] == {
        "source": 39,
        "draft": 1,
        "send_prelude": True,
        "shuffle_options": False,
    }
    persisted = store.load_run(run.run_id)
    assert persisted.skipped_questions == list(range(1, 39))
    assert persisted.uploaded_questions == [39, 40]


def test_resume_does_not_repeat_confirmed_questions(tmp_path):
    quiz_path = _quiz_file(tmp_path, 3)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow(failures={2: asyncio.TimeoutError()})
    service, store, _factory = _service(tmp_path, flow)

    paused = asyncio.run(
        service.start_upload(
            quiz_file=quiz_path,
            review_artifact_file=review_path,
            account_profile_id="default",
        )
    )
    flow.failures.clear()
    flow.uploaded.clear()

    resumed = asyncio.run(service.resume_upload_run(paused.run_id))

    assert resumed.status == "completed"
    assert [item["source"] for item in flow.uploaded] == [2, 3]
    assert store.load_run(paused.run_id).uploaded_questions == [1, 2, 3]


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (asyncio.TimeoutError(), "telegram_timeout"),
        (RuntimeError("FloodWait retries exhausted on poll"), "telegram_flood_wait"),
        (ValueError("Too many incoming messages"), "telegram_too_many_incoming_messages"),
    ],
)
def test_timeout_or_floodwait_pauses_with_next_question_index(tmp_path, failure, code):
    quiz_path = _quiz_file(tmp_path, 3)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow(failures={2: failure})
    service, store, _factory = _service(tmp_path, flow)

    run = asyncio.run(
        service.start_upload(
            quiz_file=quiz_path,
            review_artifact_file=review_path,
            account_profile_id="default",
        )
    )

    persisted = store.load_run(run.run_id)
    assert persisted.status == "paused"
    assert persisted.next_question_index == 2
    assert persisted.uploaded_questions == [1]
    assert persisted.last_error["code"] == code


def test_auto_speed_stays_fast_and_records_cooldown_after_threshold(tmp_path, monkeypatch):
    monkeypatch.setitem(config.AUTO_SPEED_POLICY, "cooldown_duration", (0.0, 0.0))
    quiz_path = _quiz_file(tmp_path, 52)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow()
    service, store, _factory = _service(tmp_path, flow)
    globals_before = {
        "DELAY_BETWEEN_MESSAGES": config.DELAY_BETWEEN_MESSAGES,
        "DELAY_BETWEEN_QUESTIONS": config.DELAY_BETWEEN_QUESTIONS,
        "LONG_PAUSE_EVERY_N_QUESTIONS": config.LONG_PAUSE_EVERY_N_QUESTIONS,
        "LONG_PAUSE_DURATION": config.LONG_PAUSE_DURATION,
    }

    run = asyncio.run(
        service.start_upload(
            quiz_file=quiz_path,
            review_artifact_file=review_path,
            account_profile_id="default",
            speed="auto",
        )
    )

    assert run.status == "completed"
    assert flow.speed_snapshots[0] == config.SPEED_PRESETS["fast"]["DELAY_BETWEEN_QUESTIONS"]
    assert flow.speed_snapshots[35] == config.SPEED_PRESETS["fast"]["DELAY_BETWEEN_QUESTIONS"]
    assert flow.speed_snapshots[50] == config.SPEED_PRESETS["fast"]["DELAY_BETWEEN_QUESTIONS"]
    persisted = store.load_run(run.run_id)
    assert persisted.speed == "auto"
    assert persisted.last_bot_state["active_speed_preset"] == "fast"
    assert [
        event["threshold_uploaded_count"] for event in persisted.cooldown_events
    ] == [40]
    assert persisted.cooldown_events[0]["reason"] == "auto_speed_cooldown"
    assert {
        "DELAY_BETWEEN_MESSAGES": config.DELAY_BETWEEN_MESSAGES,
        "DELAY_BETWEEN_QUESTIONS": config.DELAY_BETWEEN_QUESTIONS,
        "LONG_PAUSE_EVERY_N_QUESTIONS": config.LONG_PAUSE_EVERY_N_QUESTIONS,
        "LONG_PAUSE_DURATION": config.LONG_PAUSE_DURATION,
    } == globals_before


def test_continue_from_next_resumes(tmp_path):
    quiz_path = _quiz_file(tmp_path, 3)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow(failures={2: asyncio.TimeoutError()})
    service, _store, _factory = _service(tmp_path, flow)
    paused = asyncio.run(
        service.start_upload(
            quiz_file=quiz_path,
            review_artifact_file=review_path,
            account_profile_id="default",
        )
    )
    flow.failures.clear()
    flow.uploaded.clear()

    run = asyncio.run(service.continue_upload_run_from(paused.run_id, 2))

    assert run.status == "completed"
    assert [item["source"] for item in flow.uploaded] == [2, 3]


def test_continue_updates_launch_settings_without_losing_progress(tmp_path):
    quiz_path = _quiz_file(tmp_path, 4)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow()
    service, store, _factory = _service(tmp_path, flow)
    old_run = _create_uploaded_run(store, quiz_path, uploaded=[1, 2], source_count=4)
    old_run.speed = "normal"
    old_run.context_send_mode = "once"
    old_run.shuffle_options = False
    store.save_run(old_run)

    run = asyncio.run(
        service.continue_upload_run_from(
            old_run.run_id,
            3,
            review_artifact_file=review_path,
            context_send_mode="per-question",
            shuffle_options=True,
            speed="fast",
        )
    )

    persisted = store.load_run(run.run_id)
    assert persisted.speed == "fast"
    assert persisted.context_send_mode == "per-question"
    assert persisted.shuffle_options is True
    assert persisted.uploaded_questions == [1, 2, 3, 4]
    assert [item["source"] for item in flow.uploaded] == [3, 4]
    assert {item["shuffle_options"] for item in flow.uploaded} == {True}


def test_continue_from_before_next_requires_rollback_confirmation(tmp_path):
    quiz_path = _quiz_file(tmp_path, 4)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow()
    service, store, _factory = _service(tmp_path, flow)
    _create_uploaded_run(store, quiz_path, uploaded=[1, 2, 3], source_count=4)

    with pytest.raises(UploadConfirmationRequired) as exc_info:
        asyncio.run(
            service.continue_upload_run_from(
                "run",
                2,
                review_artifact_file=review_path,
            )
        )

    assert exc_info.value.action == "rollback"
    assert exc_info.value.details["undo_count"] == 2
    assert exc_info.value.details["source_question_indexes"] == [3, 2]


def test_rollback_updates_checkpoint_after_each_fake_undo(tmp_path):
    quiz_path = _quiz_file(tmp_path, 4)
    flow = FakeFlow()
    checkpoints: list[dict] = []
    service, store, factory = _service(tmp_path, flow, checkpoints=checkpoints)
    _create_uploaded_run(store, quiz_path, uploaded=[1, 2, 3], source_count=4)

    run = asyncio.run(
        service.rollback_upload_run(
            "run",
            2,
            confirm_rollback=True,
        )
    )

    assert factory.clients[-1].sent_text == [UNDO_COMMAND, UNDO_COMMAND]
    assert [
        (item["uploaded_questions"], item["next_question_index"])
        for item in checkpoints
    ] == [([1, 2], 3), ([1], 2)]
    assert run.status == "paused"
    assert run.next_question_index == 2


def test_continue_from_after_next_requires_skip_confirmation_and_writes_events(tmp_path):
    quiz_path = _quiz_file(tmp_path, 5)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow()
    service, store, _factory = _service(tmp_path, flow)
    _create_uploaded_run(store, quiz_path, uploaded=[1], source_count=5)

    with pytest.raises(UploadConfirmationRequired) as exc_info:
        asyncio.run(
            service.continue_upload_run_from(
                "run",
                4,
                review_artifact_file=review_path,
            )
        )
    assert exc_info.value.action == "skip_forward"
    assert exc_info.value.details["skipped_question_indexes"] == [2, 3]

    run = asyncio.run(
        service.continue_upload_run_from(
            "run",
            4,
            review_artifact_file=review_path,
            confirm_skip_forward=True,
        )
    )

    persisted = store.load_run(run.run_id)
    assert persisted.skipped_questions == [2, 3]
    assert [
        event["source_question_index"] for event in persisted.skip_events
    ] == [2, 3]
    assert {event["reason"] for event in persisted.skip_events} == {
        "continue_from_skip_forward"
    }
    assert [item["source"] for item in flow.uploaded] == [4, 5]


def test_quiz_hash_mismatch_blocks_resume(tmp_path):
    quiz_path = _quiz_file(tmp_path, 2)
    review_path = _review_file(tmp_path, quiz_path)
    flow = FakeFlow()
    service, store, _factory = _service(tmp_path, flow)
    _create_uploaded_run(store, quiz_path, uploaded=[1], source_count=2)
    quiz_path.write_text('{"title":"changed","settings":{},"items":[]}', encoding="utf-8")

    with pytest.raises(runs.QuizHashMismatchError):
        asyncio.run(service.resume_upload_run("run", review_artifact_file=review_path))


def test_upload_is_blocked_without_fresh_review_artifact(tmp_path):
    quiz_path = _quiz_file(tmp_path, 1)
    flow = FakeFlow()
    service, _store, factory = _service(tmp_path, flow)

    with pytest.raises(UploadGateBlockedError):
        asyncio.run(
            service.start_upload(
                quiz_file=quiz_path,
                review_artifact_file=tmp_path / "missing-review.json",
                account_profile_id="default",
            )
        )

    assert factory.clients == []
    assert flow.uploaded == []
