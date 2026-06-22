import json

import pytest

from backend import runs


def _quiz_file(tmp_path, text="История Казахстана"):
    path = tmp_path / "quiz.clean.json"
    path.write_text(
        json.dumps(
            {
                "title": text,
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
    return path


def test_create_load_update_run_state(tmp_path):
    quiz_path = _quiz_file(tmp_path)
    store = runs.RunStore(tmp_path / "runtime")

    created = store.create_upload_run(
        run_id="run-one",
        quiz_file=quiz_path,
        quiz_name="Қазақ тарихы",
        account_profile_id="default",
        speed="fast",
        source_question_count=1,
    )
    loaded = store.load_run("run-one")
    updated = store.update_status(
        "run-one",
        "paused",
        last_error={"code": "telegram_timeout", "api_hash": "must-not-leak"},
    )

    assert created.run_id == "run-one"
    assert loaded.quiz_file_hash == runs.compute_file_sha256(quiz_path)
    assert isinstance(loaded, runs.UploadRun)
    assert updated.status == "paused"
    assert store.load_run("run-one").last_error["code"] == "telegram_timeout"
    assert "must-not-leak" not in store.state_path("run-one").read_text(
        encoding="utf-8"
    )


def test_checkpoint_after_question_updates_next_question_index(tmp_path):
    quiz_path = _quiz_file(tmp_path)
    store = runs.RunStore(tmp_path / "runtime")
    store.create_upload_run(
        run_id="run-checkpoint",
        quiz_file=quiz_path,
        quiz_name="Checkpoint",
        account_profile_id="default",
    )

    updated = store.record_question_uploaded(
        "run-checkpoint",
        1,
        bot_message_id=123,
    )
    persisted = json.loads(
        store.state_path("run-checkpoint").read_text(encoding="utf-8")
    )

    assert updated.next_question_index == 2
    assert persisted["next_question_index"] == 2
    assert persisted["uploaded_questions"] == [1]
    assert persisted["last_bot_state"] == {"bot_message_id": 123}


def test_update_auto_resume_persists_public_snapshot(tmp_path):
    quiz_path = _quiz_file(tmp_path)
    store = runs.RunStore(tmp_path / "runtime")
    store.create_upload_run(
        run_id="run-auto-resume",
        quiz_file=quiz_path,
        quiz_name="Auto resume",
        account_profile_id="default",
        source_question_count=1,
    )

    updated = store.update_auto_resume(
        "run-auto-resume",
        enabled=True,
        delay_seconds=300,
        next_at="2026-06-21T12:00:00+00:00",
        increment_attempts=True,
        last_job_id="job-one",
    )
    snapshot = store.safe_status_snapshot("run-auto-resume")

    assert updated.auto_resume_enabled is True
    assert updated.auto_resume_delay_seconds == 300
    assert updated.auto_resume_attempts == 1
    assert snapshot["auto_resume_enabled"] is True
    assert snapshot["auto_resume_delay_seconds"] == 300
    assert snapshot["auto_resume_next_at"] == "2026-06-21T12:00:00+00:00"
    assert snapshot["auto_resume_attempts"] == 1
    assert snapshot["auto_resume_last_job_id"] == "job-one"


def test_active_run_pointer_resolves_default_run(tmp_path):
    quiz_path = _quiz_file(tmp_path)
    store = runs.RunStore(tmp_path / "runtime")
    store.create_upload_run(
        run_id="active-run",
        quiz_file=quiz_path,
        quiz_name="Active",
        account_profile_id="default",
    )

    active_payload = json.loads(store.active_run_path().read_text(encoding="utf-8"))

    assert active_payload["run_id"] == "active-run"
    assert store.resolve_run_id(None) == "active-run"
    assert store.resolve_run(None).run_id == "active-run"


def test_protected_progress_detection_works():
    base = runs.UploadRun(
        run_id="run",
        quiz_file="quiz.json",
        quiz_file_hash="hash",
        quiz_name="Quiz",
        account_profile_id="default",
        start_question_index=3,
        next_question_index=3,
    )

    assert not runs.has_protected_progress(base)
    assert runs.has_protected_progress(
        runs.UploadRun(**{**base.to_dict(), "uploaded_questions": [3]})
    )
    assert runs.has_protected_progress(
        runs.UploadRun(**{**base.to_dict(), "skip_events": [{"reason": "skip"}]})
    )
    assert runs.has_protected_progress(
        runs.UploadRun(**{**base.to_dict(), "next_question_index": 4})
    )
    assert runs.has_protected_progress(
        runs.UploadRun(**{**base.to_dict(), "status": "running"})
    )


def test_replacing_active_run_marks_old_run_cancelled_replaced(tmp_path):
    quiz_path = _quiz_file(tmp_path)
    store = runs.RunStore(tmp_path / "runtime")
    store.create_upload_run(
        run_id="old-run",
        quiz_file=quiz_path,
        quiz_name="Old",
        account_profile_id="default",
    )
    store.create_upload_run(
        run_id="new-run",
        quiz_file=quiz_path,
        quiz_name="New",
        account_profile_id="default",
        make_active=False,
    )

    replaced = store.replace_active_run("new-run", reason="confirmed_replace")
    old_run = store.load_run("old-run")

    assert replaced.run_id == "old-run"
    assert old_run.status == "cancelled_replaced"
    assert old_run.replaced_by_run_id == "new-run"
    assert old_run.cleanup_events[0]["reason"] == "confirmed_replace"
    assert store.resolve_run_id(None) == "new-run"


def test_quiz_hash_mismatch_blocks_resume(tmp_path):
    quiz_path = _quiz_file(tmp_path)
    store = runs.RunStore(tmp_path / "runtime")
    store.create_upload_run(
        run_id="hash-run",
        quiz_file=quiz_path,
        quiz_name="Hash",
        account_profile_id="default",
    )
    quiz_path.write_text('{"title":"changed","items":[]}', encoding="utf-8")

    with pytest.raises(runs.QuizHashMismatchError):
        store.assert_quiz_hash_matches("hash-run")


def test_utf8_json_output_is_readable_and_snapshot_has_no_secrets(tmp_path):
    quiz_path = _quiz_file(tmp_path, text="Қазақ тарихы")
    store = runs.RunStore(tmp_path / "runtime")
    store.create_upload_run(
        run_id="utf8-run",
        quiz_file=quiz_path,
        quiz_name="Қазақ тарихы",
        account_profile_id="default",
    )
    store.update_status(
        "utf8-run",
        "failed",
        last_error={
            "code": "missing_credentials",
            "message": "Нужно выбрать профиль",
            "api_hash": "secret",
            "session_path": "/tmp/private.session",
            "phone": "+77001234567",
        },
    )

    raw_state = store.state_path("utf8-run").read_text(encoding="utf-8")
    snapshot = store.safe_status_snapshot("utf8-run")
    snapshot_text = json.dumps(snapshot, ensure_ascii=False)

    assert "Қазақ тарихы" in raw_state
    assert "\\u049a" not in raw_state
    assert "secret" not in raw_state
    assert "private.session" not in raw_state
    assert "+77001234567" not in raw_state
    assert "secret" not in snapshot_text
    assert "private.session" not in snapshot_text
    assert "+77001234567" not in snapshot_text
    assert snapshot["last_error"] == {
        "code": "missing_credentials",
        "message": "Нужно выбрать профиль",
    }


def test_upload_snapshot_includes_estimated_remaining_seconds(tmp_path):
    quiz_path = _quiz_file(tmp_path)
    store = runs.RunStore(tmp_path / "runtime")
    store.create_upload_run(
        run_id="eta-run",
        quiz_file=quiz_path,
        quiz_name="ETA",
        account_profile_id="default",
        speed="auto",
        source_question_count=80,
    )
    store.record_question_uploaded("eta-run", 1)

    snapshot = store.safe_status_snapshot("eta-run")

    assert snapshot["estimated_remaining_seconds"] > 0


def test_upload_eta_uses_speed_preset_and_tunable_bot_response(tmp_path):
    quiz_path = _quiz_file(tmp_path)
    runtime_dir = tmp_path / "runtime"
    runs.config.save_eta_settings({"bot_response_seconds": 1.0}, runtime_dir)
    store = runs.RunStore(runtime_dir)
    store.create_upload_run(
        run_id="fast-eta-run",
        quiz_file=quiz_path,
        quiz_name="Fast ETA",
        account_profile_id="default",
        speed="fast",
        source_question_count=20,
    )

    snapshot = store.safe_status_snapshot("fast-eta-run")

    assert snapshot["estimated_remaining_seconds"] == 270
