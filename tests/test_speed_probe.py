import asyncio
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from backend import accounts, config, runs
from backend.quizbot_client import FloodWaitCapExceeded
from backend.speed_probe import (
    FAST_THRESHOLD_POLICY,
    SpeedProbeActiveProfileError,
    SpeedProbeService,
)


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


class OrderedProbeClient:
    def __init__(
        self,
        *,
        label: str,
        entered: list[str],
        block_enter: asyncio.Event | None = None,
    ):
        self.label = label
        self.entered = entered
        self.block_enter = block_enter

    async def __aenter__(self):
        self.entered.append(self.label)
        if self.block_enter is not None:
            await self.block_enter.wait()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class OrderedProbeClientFactory:
    def __init__(self, clients: list[OrderedProbeClient]):
        self.clients = clients
        self.profile_ids: list[str] = []

    def __call__(self, profile_id: str) -> OrderedProbeClient:
        self.profile_ids.append(profile_id)
        return self.clients.pop(0)


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
        self.speed_snapshots.append(_client_delay_between_questions(client))
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


def _client_delay_between_questions(client) -> tuple[float, float]:
    profile = getattr(client, "timing_profile", None)
    if profile is not None:
        return profile.delay_between_questions
    return config.DELAY_BETWEEN_QUESTIONS


def _service(
    tmp_path: Path,
    flow: FakeFlow,
    *,
    client_factory: FakeClientFactory | OrderedProbeClientFactory | None = None,
):
    store = runs.RunStore(tmp_path / "runtime")
    factory = client_factory or FakeClientFactory()
    account_store = tmp_path / "accounts"
    accounts.create_profile(
        display_name="default",
        api_id=12345,
        api_hash="api-hash",
        phone="+70000000000",
        store_root=account_store,
    )
    service = SpeedProbeService(
        run_store=store,
        client_factory=factory,
        flow_primitives=flow,
        monotonic=MonotonicClock(),
        account_store_root=account_store,
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


def test_flood_wait_cap_recorded_as_limit_with_retry_after(tmp_path):
    quiz_path = _quiz_file(tmp_path, 4)
    flow = FakeFlow(failures={3: FloodWaitCapExceeded(7200, 300.0, context="poll")})
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
    assert report.limit_events[0]["kind"] == "telegram_flood_wait"
    assert report.last_error["code"] == "telegram_flood_wait"
    assert report.last_error["retry_after_seconds"] == 7200
    assert report.question_timings[-1]["status"] == "limit"


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


def test_probe_without_profile_or_confirm_refuses_active_profile(tmp_path):
    quiz_path = _quiz_file(tmp_path, 2)
    flow = FakeFlow()
    service, store, factory = _service(tmp_path, flow)

    with pytest.raises(SpeedProbeActiveProfileError):
        asyncio.run(
            service.start_probe(
                quiz_file=quiz_path,
                question_count=2,
                policy=FAST_THRESHOLD_POLICY,
            )
        )

    # Ничего не тронуто: ни клиент, ни flow, ни активный запуск.
    assert factory.profile_ids == []
    assert flow.created == []
    assert store.get_active_run_id(required=False) is None


@pytest.mark.parametrize("blank_profile", ["", "   "])
def test_probe_blank_profile_without_confirm_refuses_active_profile(
    tmp_path, blank_profile
):
    quiz_path = _quiz_file(tmp_path, 2)
    flow = FakeFlow()
    service, store, factory = _service(tmp_path, flow)

    with pytest.raises(SpeedProbeActiveProfileError):
        asyncio.run(
            service.start_probe(
                quiz_file=quiz_path,
                question_count=2,
                policy=FAST_THRESHOLD_POLICY,
                account_profile_id=blank_profile,
            )
        )

    # Пустой/пробельный профиль трактуется как отсутствующий: ничего не тронуто.
    assert factory.profile_ids == []
    assert flow.created == []
    assert store.get_active_run_id(required=False) is None


def test_probe_blank_profile_with_confirm_active_uses_active_profile(tmp_path):
    quiz_path = _quiz_file(tmp_path, 2)
    flow = FakeFlow()
    service, store, factory = _service(tmp_path, flow)

    run = asyncio.run(
        service.start_probe(
            quiz_file=quiz_path,
            question_count=2,
            policy=FAST_THRESHOLD_POLICY,
            account_profile_id="   ",
            confirm_active=True,
        )
    )

    # Blank + confirm_active ведёт себя как "нет профиля + подтверждено":
    # выбран активный "default", "" дальше не утекает.
    assert run.status == "completed"
    assert run.account_profile_id == "default"
    assert factory.profile_ids == ["default"]
    assert store.get_active_run_id() == run.probe_id


def test_probe_with_confirm_active_uses_active_profile(tmp_path):
    quiz_path = _quiz_file(tmp_path, 2)
    flow = FakeFlow()
    service, store, factory = _service(tmp_path, flow)

    run = asyncio.run(
        service.start_probe(
            quiz_file=quiz_path,
            question_count=2,
            policy=FAST_THRESHOLD_POLICY,
            confirm_active=True,
        )
    )

    assert run.status == "completed"
    # Активный профиль из стора ("default") выбран и реально использован.
    assert run.account_profile_id == "default"
    assert factory.profile_ids == ["default"]
    assert store.get_active_run_id() == run.probe_id


def test_concurrent_speed_probe_runs_for_same_profile_use_session_lock(tmp_path):
    async def run_scenario():
        quiz_path = _quiz_file(tmp_path, 2)
        entered: list[str] = []
        first_release = asyncio.Event()
        first_client = OrderedProbeClient(
            label="first",
            entered=entered,
            block_enter=first_release,
        )
        second_client = OrderedProbeClient(label="second", entered=entered)
        flow = FakeFlow()
        service, store, _factory = _service(
            tmp_path,
            flow,
            client_factory=OrderedProbeClientFactory([first_client, second_client]),
        )

        first_task = asyncio.create_task(
            service.start_probe(
                quiz_file=quiz_path,
                question_count=2,
                policy=FAST_THRESHOLD_POLICY,
                account_profile_id="default",
            )
        )
        while len(entered) < 1:
            await asyncio.sleep(0.01)
        second_task = asyncio.create_task(
            service.start_probe(
                quiz_file=quiz_path,
                question_count=2,
                policy=FAST_THRESHOLD_POLICY,
                account_profile_id="default",
                replace_active=True,
            )
        )

        await asyncio.sleep(0.05)
        assert entered == ["first"]
        first_release.set()

        first = await first_task
        second = await second_task
        assert entered == ["first", "second"]
        assert first.status == "completed"
        assert second.status == "completed"

    asyncio.run(run_scenario())


class ProfileCapturingProbeClient:
    def __init__(self, *, profiles_seen: list):
        self.profiles_seen = profiles_seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class ProfileCapturingProbeFactory:
    def __init__(self, clients: list[ProfileCapturingProbeClient]):
        self.clients = clients

    def __call__(self, profile_id: str) -> ProfileCapturingProbeClient:
        return self.clients.pop(0)


class ProfileCapturingProbeFlow:
    async def create_quiz(self, client, quiz_name: str) -> None:
        return None

    async def upload_question(self, client, q, index_in_quiz: int, **kwargs) -> None:
        client.profiles_seen.append(getattr(client, "timing_profile", None))

    async def finish_quiz(self, client) -> str:
        return "https://t.me/QuizBot?start=probe"


def test_concurrent_probes_have_isolated_immutable_timing_profiles(tmp_path):
    async def run_scenario():
        quiz_path = _quiz_file(tmp_path, 2)
        globals_before = {
            "DELAY_BETWEEN_MESSAGES": config.DELAY_BETWEEN_MESSAGES,
            "DELAY_BETWEEN_QUESTIONS": config.DELAY_BETWEEN_QUESTIONS,
            "LONG_PAUSE_EVERY_N_QUESTIONS": config.LONG_PAUSE_EVERY_N_QUESTIONS,
            "LONG_PAUSE_DURATION": config.LONG_PAUSE_DURATION,
        }
        first_profiles: list = []
        second_profiles: list = []
        factory = ProfileCapturingProbeFactory(
            [
                ProfileCapturingProbeClient(profiles_seen=first_profiles),
                ProfileCapturingProbeClient(profiles_seen=second_profiles),
            ]
        )
        flow = ProfileCapturingProbeFlow()
        service, _store, _factory = _service(tmp_path, flow, client_factory=factory)

        first_task = asyncio.create_task(
            service.start_probe(
                quiz_file=quiz_path,
                question_count=2,
                policy=FAST_THRESHOLD_POLICY,
                account_profile_id="default",
            )
        )
        await first_task
        second_task = asyncio.create_task(
            service.start_probe(
                quiz_file=quiz_path,
                question_count=2,
                policy=FAST_THRESHOLD_POLICY,
                account_profile_id="default",
                replace_active=True,
            )
        )
        await second_task

        # Каждый probe получил собственный immutable-профиль, не общий с другим.
        assert first_profiles and second_profiles
        assert all(p is not None for p in first_profiles + second_profiles)
        assert all(p is first_profiles[0] for p in first_profiles)
        assert all(p is second_profiles[0] for p in second_profiles)
        assert first_profiles[0] is not second_profiles[0]
        # Профили — заморожены и одинаковы по значению (fast-порог).
        fast = config.build_timing_profile("fast")
        assert first_profiles[0] == fast == second_profiles[0]
        # Нет утечки в process-global config.
        assert {
            "DELAY_BETWEEN_MESSAGES": config.DELAY_BETWEEN_MESSAGES,
            "DELAY_BETWEEN_QUESTIONS": config.DELAY_BETWEEN_QUESTIONS,
            "LONG_PAUSE_EVERY_N_QUESTIONS": config.LONG_PAUSE_EVERY_N_QUESTIONS,
            "LONG_PAUSE_DURATION": config.LONG_PAUSE_DURATION,
        } == globals_before

    asyncio.run(run_scenario())
