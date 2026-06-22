import json
from pathlib import Path

from backend import pipeline_cli, runs
from backend.upload_service import UploadConfirmationRequired, UploadGateBlockedError


def _write_quiz(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "title": "История Казахстана",
                "settings": {"context_send_mode": "per-question"},
                "items": [
                    {
                        "type": "question",
                        "question": "Қазақ хандығы қашан құрылды?",
                        "options": [{"text": "1465"}, {"text": "1731"}],
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


def _run(
    *,
    run_id: str = "upload-run",
    status: str = "paused",
    quiz_name: str = "История Казахстана",
    profile: str = "default",
    next_question: int = 12,
    last_error: dict | None = None,
) -> runs.UploadRun:
    return runs.UploadRun(
        run_id=run_id,
        quiz_file="quiz.clean.json",
        quiz_file_hash="hash",
        quiz_name=quiz_name,
        account_profile_id=profile,
        status=status,
        next_question_index=next_question,
        source_question_count=180,
        last_error=last_error,
    )


class FakeStore:
    def __init__(
        self,
        *,
        active_run_id: str | None = None,
        active_run=None,
        snapshot: dict | None = None,
    ):
        self.active_run_id = active_run_id
        self.active_run = active_run
        self.snapshot = snapshot or _run(run_id=active_run_id or "active-run").to_dict()
        self.safe_status_args: list[str | None] = []
        self.updated: list[tuple[str, str, dict | None]] = []

    def get_active_run_id(self, *, required: bool = True):
        if self.active_run_id is None and required:
            raise runs.ActiveRunNotFoundError("No active run")
        return self.active_run_id

    def load_run(self, run_id: str):
        assert run_id == self.active_run_id
        return self.active_run

    def safe_status_snapshot(self, run_id=None):
        self.safe_status_args.append(run_id)
        return dict(self.snapshot)

    def resolve_run_id(self, run_id=None):
        return run_id or self.active_run_id

    def update_status(self, run_id, status, *, last_error=None):
        resolved = self.resolve_run_id(run_id)
        self.updated.append((resolved, status, last_error))
        return _run(run_id=resolved, status=status, last_error=last_error)


class FakeUploadService:
    def __init__(self, *, run_store=None, run=None, gate_blocked: bool = False):
        self.run_store = run_store or FakeStore(active_run_id=None)
        self.run = run or _run(status="completed", next_question=181)
        self.gate_blocked = gate_blocked
        self.start_calls: list[dict] = []
        self.resume_calls: list[str | None] = []

    def start_upload(self, **kwargs):
        self.start_calls.append(kwargs)
        if self.gate_blocked:
            raise UploadGateBlockedError("review artifact missing")
        return self.run

    def resume_upload_run(self, run_id=None):
        self.resume_calls.append(run_id)
        return self.run


class ConfirmingService(FakeUploadService):
    def __init__(self, *, action: str):
        super().__init__(run_store=FakeStore(active_run_id=None))
        self.action = action
        self.rollback_calls: list[dict] = []
        self.continue_calls: list[dict] = []

    def rollback_upload_run(self, run_id, rollback_to, *, confirm_rollback=False):
        self.rollback_calls.append(
            {
                "run_id": run_id,
                "rollback_to": rollback_to,
                "confirm_rollback": confirm_rollback,
            }
        )
        if not confirm_rollback:
            raise UploadConfirmationRequired(
                "rollback",
                run_id=run_id or "active-run",
                rollback_to=rollback_to,
                undo_count=2,
            )
        return _run(run_id=run_id or "active-run", next_question=rollback_to)

    def continue_upload_run_from(
        self,
        run_id,
        question_index,
        *,
        confirm_rollback=False,
        confirm_skip_forward=False,
    ):
        self.continue_calls.append(
            {
                "run_id": run_id,
                "question_index": question_index,
                "confirm_rollback": confirm_rollback,
                "confirm_skip_forward": confirm_skip_forward,
            }
        )
        if self.action == "rollback" and not confirm_rollback:
            raise UploadConfirmationRequired(
                "rollback",
                run_id=run_id or "active-run",
                rollback_to=question_index,
                undo_count=3,
            )
        if self.action == "skip_forward" and not confirm_skip_forward:
            raise UploadConfirmationRequired(
                "skip_forward",
                run_id=run_id or "active-run",
                continue_from=question_index,
                skipped_question_indexes=[4, 5],
            )
        return _run(run_id=run_id or "active-run", next_question=question_index)


class TtyInput:
    def isatty(self):
        return True


def test_upload_blocks_without_fresh_review_decisions(tmp_path, monkeypatch, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    _write_quiz(quiz_path)
    service = FakeUploadService(gate_blocked=True)
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: service)

    exit_code = pipeline_cli.run(
        ["upload", "--file", str(quiz_path), "--name", "История", "--speed", "fast"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert service.start_calls
    assert "Upload заблокирован" in captured.out
    assert "python -m backend.pipeline_cli validate" in captured.out
    assert "--interactive" in captured.out


def test_upload_start_from_39_passes_request_to_service(tmp_path, monkeypatch, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    _write_quiz(quiz_path)
    service = FakeUploadService()
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: service)

    exit_code = pipeline_cli.run(
        [
            "upload",
            "--file",
            str(quiz_path),
            "--name",
            "История",
            "--speed",
            "fast",
            "--start-from",
            "39",
            "--profile",
            "second",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert service.start_calls == [
        {
            "quiz_file": quiz_path,
            "quiz_name": "История",
            "speed": "fast",
            "start_from": 39,
            "account_profile_id": "second",
            "replace_active": False,
        }
    ]
    assert "ID запуска" in captured.out
    assert "Профиль" in captured.out


def test_status_resolves_active_run(monkeypatch, capsys):
    store = FakeStore(
        active_run_id="active-run",
        snapshot=_run(run_id="active-run", next_question=79).to_dict(),
    )
    monkeypatch.setattr(pipeline_cli, "_make_run_store", lambda: store)

    exit_code = pipeline_cli.run(["status"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert store.safe_status_args == [None]
    assert "ID запуска: active-run" in captured.out
    assert "Следующий вопрос: 79" in captured.out


def test_resume_resolves_active_run(monkeypatch, capsys):
    service = FakeUploadService(run=_run(run_id="active-run", next_question=80))
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: service)

    exit_code = pipeline_cli.run(["resume"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert service.resume_calls == [None]
    assert "Resume завершен" in captured.out
    assert "ID запуска: active-run" in captured.out


def test_rollback_requires_confirmation_flag_in_test_mode(monkeypatch, capsys):
    service = ConfirmingService(action="rollback")
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: service)

    exit_code = pipeline_cli.run(["rollback", "--to", "67"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert service.rollback_calls == [
        {"run_id": None, "rollback_to": 67, "confirm_rollback": False}
    ]
    assert "Требуется подтверждение" in captured.out
    assert "--yes" in captured.out

    exit_code = pipeline_cli.run(["rollback", "--to", "67", "--yes"])

    assert exit_code == 0
    assert service.rollback_calls[-1] == {
        "run_id": None,
        "rollback_to": 67,
        "confirm_rollback": True,
    }


def test_continue_from_handles_resume_rollback_and_skip_forward(
    monkeypatch, capsys
):
    resume_service = ConfirmingService(action="resume")
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: resume_service)
    assert pipeline_cli.run(["continue-from", "10"]) == 0
    assert resume_service.continue_calls == [
        {
            "run_id": None,
            "question_index": 10,
            "confirm_rollback": False,
            "confirm_skip_forward": False,
        }
    ]

    rollback_service = ConfirmingService(action="rollback")
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: rollback_service)
    monkeypatch.setattr(pipeline_cli.sys, "stdin", TtyInput())
    monkeypatch.setattr("builtins.input", lambda _prompt: "да")
    assert pipeline_cli.run(["continue-from", "7"]) == 0
    assert rollback_service.continue_calls[-1] == {
        "run_id": None,
        "question_index": 7,
        "confirm_rollback": True,
        "confirm_skip_forward": False,
    }

    skip_service = ConfirmingService(action="skip_forward")
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: skip_service)
    assert pipeline_cli.run(["continue-from", "12"]) == 0
    assert skip_service.continue_calls[-1] == {
        "run_id": None,
        "question_index": 12,
        "confirm_rollback": False,
        "confirm_skip_forward": True,
    }

    captured = capsys.readouterr()
    assert "Continue-from завершен" in captured.out


def test_active_protected_run_replacement_blocked_without_confirmation(
    tmp_path, monkeypatch, capsys
):
    quiz_path = tmp_path / "quiz.clean.json"
    _write_quiz(quiz_path)
    store = runs.RunStore(tmp_path / "runtime")
    store.create_upload_run(
        run_id="active-run",
        quiz_file=quiz_path,
        quiz_name="Старый квиз",
        account_profile_id="default",
        source_question_count=1,
    )
    store.record_question_uploaded("active-run", 1)
    service = FakeUploadService(run_store=store)
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: service)

    exit_code = pipeline_cli.run(
        ["upload", "--file", str(quiz_path), "--name", "Новый квиз", "--speed", "fast"]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert service.start_calls == []
    assert "защищенным прогрессом" in captured.out
    assert "python -m backend.pipeline_cli resume" in captured.out


def test_cli_output_is_readable_russian(tmp_path, monkeypatch, capsys):
    quiz_path = tmp_path / "quiz.clean.json"
    _write_quiz(quiz_path)
    service = FakeUploadService(
        run=_run(
            run_id="run-ru",
            status="paused",
            quiz_name="История Казахстана",
            next_question=42,
            last_error={"code": "telegram_timeout", "message": "Таймаут ответа"},
        )
    )
    monkeypatch.setattr(pipeline_cli, "_make_upload_service", lambda: service)

    exit_code = pipeline_cli.run(
        ["upload", "--file", str(quiz_path), "--name", "История Казахстана"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Квиз: История Казахстана" in captured.out
    assert "Следующий вопрос: 42" in captured.out
    assert "Последняя ошибка: telegram_timeout: Таймаут ответа" in captured.out
    assert "\\u" not in captured.out
