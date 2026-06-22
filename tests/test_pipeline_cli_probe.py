import json
from pathlib import Path

from backend import pipeline_cli, runs


def _write_quiz(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "title": "Speed probe source",
                "settings": {"context_send_mode": "per-question"},
                "items": [
                    {
                        "type": "question",
                        "question": "Probe question?",
                        "options": [{"text": "A"}, {"text": "B"}],
                        "answers": [1],
                        "mode": "single",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _probe_run(
    *,
    probe_id: str = "probe-run",
    status: str = "paused",
    cleanup_status: str = "manual_required",
) -> runs.SpeedProbeRun:
    return runs.SpeedProbeRun(
        probe_id=probe_id,
        account_profile_id="default",
        quiz_name="SPEED PROBE 2026-06-18 00-00-00",
        source_quiz_file="probe.clean.json",
        source_quiz_file_hash="hash",
        delay_policy={
            "mode": "fast-threshold",
            "base_preset": "fast",
            "preventive_cooldown": False,
            "auto_cooldown_on_limit": False,
        },
        status=status,
        cleanup_status=cleanup_status,
    )


class FakeStore:
    def __init__(self, *, active_run=None):
        self.active_run = active_run

    def get_active_run_id(self, *, required: bool = True):
        if self.active_run is None:
            if required:
                raise runs.ActiveRunNotFoundError("No active run")
            return None
        return self.active_run.probe_id

    def load_run(self, run_id: str):
        assert self.active_run is not None
        assert run_id == self.active_run.probe_id
        return self.active_run

    def resolve_run(self, run_id=None):
        if run_id is None:
            assert self.active_run is not None
            return self.active_run
        return self.load_run(run_id)


class FakeSpeedProbeService:
    def __init__(self, *, run_store=None, run=None):
        self.run_store = run_store or FakeStore()
        self.run = run or _probe_run(status="completed")
        self.start_calls: list[dict] = []
        self.resume_calls: list[str | None] = []

    def start_probe(self, **kwargs):
        self.start_calls.append(kwargs)
        return self.run

    def resume_probe_run(self, run_id=None):
        self.resume_calls.append(run_id)
        return self.run

    def report_path(self, run_id: str) -> Path:
        return Path("/tmp") / run_id / "speed-probe-report.json"


class FakeUploadService:
    def __init__(self, *, run_store):
        self.run_store = run_store
        self.resume_calls: list[str | None] = []

    def resume_upload_run(self, run_id=None):
        self.resume_calls.append(run_id)
        raise AssertionError("upload resume must not handle speed probe runs")


def test_probe_speed_passes_fast_threshold_policy_to_service(
    tmp_path,
    monkeypatch,
    capsys,
):
    quiz_path = tmp_path / "probe.clean.json"
    _write_quiz(quiz_path)
    service = FakeSpeedProbeService()
    monkeypatch.setattr(pipeline_cli, "_make_speed_probe_service", lambda: service)

    exit_code = pipeline_cli.run(
        [
            "probe-speed",
            "--file",
            str(quiz_path),
            "--questions",
            "200",
            "--policy",
            "fast-threshold",
            "--profile",
            "second",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert service.start_calls == [
        {
            "quiz_file": quiz_path,
            "question_count": 200,
            "policy": "fast-threshold",
            "account_profile_id": "second",
            "replace_active": False,
        }
    ]
    assert "Speed probe" in captured.out
    assert "Отчет probe: /tmp/probe-run/speed-probe-report.json" in captured.out


def test_probe_speed_replacement_requires_confirmation_for_protected_active_run(
    tmp_path,
    monkeypatch,
    capsys,
):
    quiz_path = tmp_path / "probe.clean.json"
    _write_quiz(quiz_path)
    active = _probe_run(status="paused")
    active.first_limit_at_question = 3
    store = FakeStore(active_run=active)
    service = FakeSpeedProbeService(run_store=store)
    monkeypatch.setattr(pipeline_cli, "_make_speed_probe_service", lambda: service)

    exit_code = pipeline_cli.run(
        [
            "probe-speed",
            "--file",
            str(quiz_path),
            "--questions",
            "1",
            "--policy",
            "fast-threshold",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert service.start_calls == []
    assert "защищенным прогрессом" in captured.out
    assert "Новый probe-speed не запущен" in captured.out


def test_resume_active_speed_probe_uses_probe_service(monkeypatch, capsys):
    active = _probe_run(status="paused")
    store = FakeStore(active_run=active)
    upload_service = FakeUploadService(run_store=store)
    probe_service = FakeSpeedProbeService(
        run_store=store,
        run=_probe_run(probe_id=active.probe_id, status="completed"),
    )
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: upload_service)
    monkeypatch.setattr(pipeline_cli, "_make_speed_probe_service", lambda: probe_service)

    exit_code = pipeline_cli.run(["resume"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert upload_service.resume_calls == []
    assert probe_service.resume_calls == [None]
    assert "Speed probe resume" in captured.out
    assert "ID запуска: probe-run" in captured.out
