import asyncio
import copy
import hashlib
import json
import re
from pathlib import Path

from backend import config, runs
from backend.speed_probe import FAST_THRESHOLD_POLICY, SpeedProbeService


def _question(index: int) -> dict:
    marker = hashlib.sha256(f"probe-question-{index}".encode("ascii")).hexdigest()
    return {
        "type": "question",
        "question": f"Probe question {index} unique marker {marker}?",
        "options": [{"text": "A"}, {"text": "B"}],
        "answers": [1],
        "mode": "single",
    }


def _quiz_file(tmp_path: Path, count: int) -> Path:
    path = tmp_path / "probe.clean.json"
    path.write_text(
        json.dumps(
            {
                "title": "Probe source",
                "settings": {"context_send_mode": "per-question"},
                "items": [_question(index) for index in range(1, count + 1)],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeClientFactory:
    def __init__(self):
        self.profile_ids: list[str] = []

    def __call__(self, profile_id: str) -> FakeClient:
        self.profile_ids.append(profile_id)
        return FakeClient()


class FakeFlow:
    def __init__(self, failures: dict[int, BaseException] | None = None):
        self.failures = failures or {}
        self.created: list[str] = []
        self.uploaded: list[int] = []
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
        self.uploaded.append(source_index)

    async def finish_quiz(self, client) -> str:
        self.finished += 1
        return "https://t.me/QuizBot?start=probe"


class MonotonicClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self) -> float:
        self.value += 0.25
        return self.value


def _source_index(text: str) -> int:
    match = re.search(r"Probe question (\d+)", text)
    assert match is not None
    return int(match.group(1))


def _service(tmp_path: Path, flow: FakeFlow):
    store = runs.RunStore(tmp_path / "runtime")
    factory = FakeClientFactory()
    service = SpeedProbeService(
        run_store=store,
        client_factory=factory,
        flow_primitives=flow,
        monotonic=MonotonicClock(),
    )
    return service, store, factory


def test_probe_creates_speed_probe_run_and_active_run(tmp_path):
    quiz_path = _quiz_file(tmp_path, 2)
    flow = FakeFlow()
    service, store, factory = _service(tmp_path, flow)

    run = asyncio.run(
        service.start_probe(
            quiz_file=quiz_path,
            question_count=2,
            policy=FAST_THRESHOLD_POLICY,
            account_profile_id="default",
        )
    )

    assert isinstance(run, runs.SpeedProbeRun)
    assert store.get_active_run_id() == run.probe_id
    assert run.cleanup_status == "manual_required"
    assert run.status == "completed"
    assert factory.profile_ids == ["default"]
    assert flow.created[0].startswith("SPEED PROBE ")
    assert service.report_path(run.probe_id).exists()


def test_probe_uses_fast_threshold_policy_and_fast_preset(tmp_path):
    quiz_path = _quiz_file(tmp_path, 1)
    flow = FakeFlow()
    service, _store, _factory = _service(tmp_path, flow)

    run = asyncio.run(
        service.start_probe(
            quiz_file=quiz_path,
            question_count=1,
            policy=FAST_THRESHOLD_POLICY,
            account_profile_id="default",
        )
    )

    assert run.delay_policy == {
        "mode": "fast-threshold",
        "base_preset": "fast",
        "preventive_cooldown": False,
        "auto_cooldown_on_limit": False,
    }
    assert flow.speed_snapshots == [config.SPEED_PRESETS["fast"]["DELAY_BETWEEN_QUESTIONS"]]


def test_first_limit_event_records_source_question_index(tmp_path):
    quiz_path = _quiz_file(tmp_path, 4)
    flow = FakeFlow(failures={3: RuntimeError("Too many requests: retry later")})
    service, store, _factory = _service(tmp_path, flow)

    run = asyncio.run(
        service.start_probe(
            quiz_file=quiz_path,
            question_count=4,
            policy=FAST_THRESHOLD_POLICY,
            account_profile_id="default",
        )
    )

    persisted = store.load_run(run.probe_id)
    report = service.load_report(run.probe_id)
    assert persisted.status == "paused"
    assert persisted.first_limit_at_question == 3
    assert persisted.limit_events[0]["source_question_index"] == 3
    assert report.first_limit_at_question == 3
    assert report.limit_events[0]["kind"] == "telegram_too_many_requests"
    assert report.questions_confirmed == 2
    assert report.question_timings[-1]["source_question_index"] == 3
    assert report.last_error["code"] == "telegram_too_many_requests"


def test_too_many_incoming_messages_is_recorded_as_limit(tmp_path):
    quiz_path = _quiz_file(tmp_path, 4)
    flow = FakeFlow(failures={3: ValueError("Too many incoming messages")})
    service, store, _factory = _service(tmp_path, flow)

    run = asyncio.run(
        service.start_probe(
            quiz_file=quiz_path,
            question_count=4,
            policy=FAST_THRESHOLD_POLICY,
            account_profile_id="default",
        )
    )

    persisted = store.load_run(run.probe_id)
    report = service.load_report(run.probe_id)
    assert persisted.status == "paused"
    assert persisted.first_limit_at_question == 3
    assert persisted.limit_events[0]["kind"] == "telegram_too_many_incoming_messages"
    assert report.question_timings[-1]["status"] == "limit"
    assert report.last_error["code"] == "telegram_too_many_incoming_messages"


def test_probe_pause_resume_uses_same_run_ledger(tmp_path):
    quiz_path = _quiz_file(tmp_path, 3)
    flow = FakeFlow(failures={2: KeyboardInterrupt()})
    service, store, _factory = _service(tmp_path, flow)

    paused = asyncio.run(
        service.start_probe(
            quiz_file=quiz_path,
            question_count=3,
            policy=FAST_THRESHOLD_POLICY,
            account_profile_id="default",
        )
    )

    assert paused.status == "paused"
    assert store.get_active_run_id() == paused.probe_id
    assert service.load_report(paused.probe_id).next_question_index == 2

    flow.failures.clear()
    resumed = asyncio.run(service.resume_probe_run())

    assert resumed.probe_id == paused.probe_id
    assert resumed.status == "completed"
    assert store.get_active_run_id() == paused.probe_id
    assert flow.created == [paused.quiz_name]
    assert flow.uploaded == [1, 2, 3]


def test_report_recommendation_placeholder_does_not_change_config_defaults(tmp_path):
    quiz_path = _quiz_file(tmp_path, 2)
    flow = FakeFlow()
    service, _store, _factory = _service(tmp_path, flow)
    globals_before = {
        "DELAY_BETWEEN_MESSAGES": config.DELAY_BETWEEN_MESSAGES,
        "DELAY_BETWEEN_QUESTIONS": config.DELAY_BETWEEN_QUESTIONS,
        "LONG_PAUSE_EVERY_N_QUESTIONS": config.LONG_PAUSE_EVERY_N_QUESTIONS,
        "LONG_PAUSE_DURATION": config.LONG_PAUSE_DURATION,
    }
    presets_before = copy.deepcopy(config.SPEED_PRESETS)

    run = asyncio.run(
        service.start_probe(
            quiz_file=quiz_path,
            question_count=2,
            policy=FAST_THRESHOLD_POLICY,
            account_profile_id="default",
        )
    )

    report = service.load_report(run.probe_id).to_dict()
    assert report["recommended_safe_policy"]["status"] == "manual_review_required"
    assert report["cleanup_status"] == "manual_required"
    assert config.SPEED_PRESETS == presets_before
    assert {
        "DELAY_BETWEEN_MESSAGES": config.DELAY_BETWEEN_MESSAGES,
        "DELAY_BETWEEN_QUESTIONS": config.DELAY_BETWEEN_QUESTIONS,
        "LONG_PAUSE_EVERY_N_QUESTIONS": config.LONG_PAUSE_EVERY_N_QUESTIONS,
        "LONG_PAUSE_DURATION": config.LONG_PAUSE_DURATION,
    } == globals_before
