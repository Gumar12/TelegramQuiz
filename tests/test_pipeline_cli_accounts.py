import json
from pathlib import Path

from backend import accounts, pipeline_cli, runs


def _set_runtime(tmp_path: Path, monkeypatch) -> Path:
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(accounts.config, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(accounts.config, "API_ID", 12345)
    monkeypatch.setattr(accounts.config, "API_HASH", "config-api-hash-secret")
    monkeypatch.setattr(accounts.config, "PHONE", "+15551234567")
    monkeypatch.setattr(accounts.config, "SESSION_NAME", str(runtime / "default.session"))
    return runtime


def _profile(
    profile_id: str,
    *,
    enabled: bool,
    tmp_path: Path,
    api_hash: str | None = None,
    phone: str | None = None,
    session_name: str | None = None,
) -> dict:
    return {
        "id": profile_id,
        "display_name": profile_id.title(),
        "api_id": 1000 + len(profile_id),
        "api_hash": api_hash or f"{profile_id}-api-hash",
        "phone": phone or f"+1555000{len(profile_id):04d}",
        "telegram_session_path": session_name
        or str(tmp_path / "sessions" / f"{profile_id}.session"),
        "env_source": "env",
        "pacing_policy": "normal",
        "is_enabled": enabled,
        "is_authorized": False,
        "created_at": "2026-06-17T00:00:00+00:00",
        "updated_at": "2026-06-17T00:00:00+00:00",
    }


def _write_profiles(runtime: Path, profiles: list[dict]) -> Path:
    store_root = runtime / "accounts"
    store_root.mkdir(parents=True, exist_ok=True)
    (store_root / accounts.PROFILES_FILENAME).write_text(
        json.dumps({"profiles": profiles}, ensure_ascii=False),
        encoding="utf-8",
    )
    return store_root


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
        ),
        encoding="utf-8",
    )


def test_account_list_current_and_use_work(tmp_path, monkeypatch, capsys):
    runtime = _set_runtime(tmp_path, monkeypatch)
    store_root = _write_profiles(
        runtime,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            _profile("second", enabled=True, tmp_path=tmp_path),
        ],
    )

    assert pipeline_cli.run(["account", "list"]) == 0
    captured = capsys.readouterr()
    assert "id=default" in captured.out
    assert "id=second" in captured.out
    assert "active=да" in captured.out

    assert pipeline_cli.run(["account", "current"]) == 0
    captured = capsys.readouterr()
    assert "id=default" in captured.out

    assert pipeline_cli.run(["account", "use", "second"]) == 0
    captured = capsys.readouterr()
    assert "id=second" in captured.out
    assert "active=да" in captured.out
    assert accounts.current_profile(store_root=store_root).id == "second"


def test_account_use_rejects_disabled_profile(tmp_path, monkeypatch, capsys):
    runtime = _set_runtime(tmp_path, monkeypatch)
    store_root = _write_profiles(
        runtime,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            _profile("second", enabled=False, tmp_path=tmp_path),
        ],
    )

    assert pipeline_cli.run(["account", "use", "second"]) == 1

    captured = capsys.readouterr()
    assert "disabled" in captured.err
    assert accounts.current_profile(store_root=store_root).id == "default"


def test_account_enable_blocks_more_than_two_enabled_profiles(
    tmp_path, monkeypatch, capsys
):
    runtime = _set_runtime(tmp_path, monkeypatch)
    store_root = _write_profiles(
        runtime,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            _profile("second", enabled=True, tmp_path=tmp_path),
            _profile("work", enabled=False, tmp_path=tmp_path),
        ],
    )

    assert pipeline_cli.run(["account", "enable", "work"]) == 1

    captured = capsys.readouterr()
    assert "At most 2 account profiles" in captured.err
    profiles = {
        profile.id: profile.status
        for profile in accounts.list_profiles(store_root=store_root)
    }
    assert profiles["work"] == "disabled"


def test_account_output_does_not_include_secrets(tmp_path, monkeypatch, capsys):
    runtime = _set_runtime(tmp_path, monkeypatch)
    api_hash = "super-secret-api-hash"
    raw_phone = "+77001234567"
    session_contents = "SESSION-FILE-CONTENTS-SHOULD-NOT-LEAK"
    session_path = tmp_path / "sessions" / "private.session"
    profile = _profile(
        "default",
        enabled=True,
        tmp_path=tmp_path,
        api_hash=api_hash,
        phone=raw_phone,
        session_name=str(session_path),
    )
    profile["session_contents"] = session_contents
    _write_profiles(runtime, [profile])

    assert pipeline_cli.run(["account", "list"]) == 0
    assert pipeline_cli.run(["account", "current"]) == 0

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "id=default" in output
    assert "private.session" in output
    assert api_hash not in output
    assert raw_phone not in output
    assert session_contents not in output
    assert str(session_path) not in output


def test_account_use_rejects_switch_when_active_run_has_progress(
    tmp_path, monkeypatch, capsys
):
    runtime = _set_runtime(tmp_path, monkeypatch)
    store_root = _write_profiles(
        runtime,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            _profile("second", enabled=True, tmp_path=tmp_path),
        ],
    )
    quiz_path = tmp_path / "quiz.clean.json"
    _write_quiz(quiz_path)
    run_store = runs.RunStore(runtime)
    run_store.create_upload_run(
        run_id="active-run",
        quiz_file=quiz_path,
        quiz_name="Active",
        account_profile_id="default",
        source_question_count=1,
    )
    run_store.record_question_uploaded("active-run", 1)

    assert pipeline_cli.run(["account", "use", "second"]) == 1

    captured = capsys.readouterr()
    assert "Нельзя переключить account profile" in captured.err
    assert "active-run" in captured.err
    assert accounts.current_profile(store_root=store_root).id == "default"
