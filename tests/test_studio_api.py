import json
import asyncio
import time
from pathlib import Path
from urllib.parse import quote

import anyio.to_thread
import fastapi.routing
import httpx
import pytest

from backend import accounts, config, runs
from backend import studio_api
from backend import telegram_login


async def _run_in_test_threadpool(
    func,
    *args,
    abandon_on_cancel=False,
    cancellable=None,
    limiter=None,
    **kwargs,
):
    return func(*args, **kwargs)


class TestClient:
    __test__ = False

    def __init__(self, app):
        self._app = app

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def options(self, url: str, **kwargs):
        return self.request("OPTIONS", url, **kwargs)

    def request(self, method: str, url: str, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, url, **kwargs)

        original_anyio_run_sync = anyio.to_thread.run_sync
        original_fastapi_run_in_threadpool = fastapi.routing.run_in_threadpool
        try:
            anyio.to_thread.run_sync = _run_in_test_threadpool
            fastapi.routing.run_in_threadpool = _run_in_test_threadpool
            return asyncio.run(send())
        finally:
            anyio.to_thread.run_sync = original_anyio_run_sync
            fastapi.routing.run_in_threadpool = original_fastapi_run_in_threadpool


def _account_profile(
    tmp_path: Path,
    profile_id: str,
    *,
    enabled: bool = True,
    phone: str = "+77001234567",
    api_hash: str = "super-secret-api-hash",
) -> dict:
    return {
        "id": profile_id,
        "display_name": profile_id.title(),
        "api_id": 12345,
        "api_hash": api_hash,
        "phone": phone,
        "telegram_session_path": str(tmp_path / "sessions" / f"{profile_id}.session"),
        "env_source": "test",
        "pacing_policy": "normal",
        "is_enabled": enabled,
        "is_authorized": False,
        "created_at": "2026-06-19T00:00:00+00:00",
        "updated_at": "2026-06-19T00:00:00+00:00",
    }


def _write_account_profiles(store_root: Path, profiles: list[dict]) -> None:
    store_root.mkdir(parents=True, exist_ok=True)
    (store_root / accounts.PROFILES_FILENAME).write_text(
        json.dumps({"profiles": profiles}, ensure_ascii=False),
        encoding="utf-8",
    )


def _clean_quiz_file(tmp_path: Path) -> Path:
    path = tmp_path / "quiz.clean.json"
    path.write_text(
        json.dumps(
            {
                "title": "Studio adapter quiz",
                "settings": {"context_send_mode": "per-question"},
                "items": [
                    {
                        "type": "question",
                        "question": "Question?",
                        "options": [{"text": "A"}, {"text": "B"}],
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


def _write_legacy_group(
    quizzes_dir: Path,
    group_id: str = "sample",
    *,
    media: list[str] | None = None,
    question: str = "Who?",
) -> Path:
    quizzes_dir.mkdir(parents=True, exist_ok=True)
    path = quizzes_dir / f"{group_id}.json"
    payload = {
        "quiz_title": "Sample",
        "questions": [
            {
                "question": question,
                "options": ["A", "B"],
                "correct": 1,
                "explanation": "",
                "media": media or [],
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    snapshot: dict = {}
    for _ in range(50):
        snapshot = client.get(f"/api/jobs/{job_id}").json()
        if snapshot["status"] != "running":
            return snapshot
        time.sleep(0.01)
    return snapshot


def test_health_endpoint():
    client = TestClient(studio_api.create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("origin", ["http://127.0.0.1:3000", "http://localhost:3000"])
def test_cors_preflight_allows_default_vite_origins(origin: str):
    client = TestClient(studio_api.create_app())

    response = client.options(
        "/api/groups/manual",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_cors_untrusted_origin_gets_no_allow_origin():
    client = TestClient(studio_api.create_app())

    response = client.get("/api/health", headers={"Origin": "http://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_json_post_from_vite_origin(tmp_path: Path):
    origin = "http://127.0.0.1:3000"
    client = TestClient(studio_api.create_app())

    response = client.post(
        "/api/groups/manual",
        headers={"Origin": origin},
        json={"title": "CORS quiz", "workspace_dir": str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_allows_multipart_upload_from_vite_origin(tmp_path: Path):
    origin = "http://127.0.0.1:3000"
    client = TestClient(studio_api.create_app(media_dir=tmp_path / "media"))

    response = client.post(
        "/api/media/upload",
        headers={"Origin": origin},
        files={"file": ("context.png", b"image-bytes", "image/png")},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_allows_sse_from_vite_origin():
    origin = "http://127.0.0.1:3000"
    manager = studio_api.JobManager()
    job = manager.create_job("cors-sse")
    manager.complete(job.id, {"ok": True})
    client = TestClient(studio_api.create_app(manager=manager))

    response = client.get(
        f"/api/jobs/{job.id}/events",
        headers={"Origin": origin},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "text/event-stream" in response.headers["content-type"]
    assert b"data:" in response.content


@pytest.mark.parametrize("raw", ["*", "http://*.localhost:3000"])
def test_studio_cors_origins_rejects_wildcards(raw: str):
    with pytest.raises(ValueError):
        config.studio_cors_origins(raw)


def test_groups_endpoint_lists_storage_groups(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "quiz_description": "Desc",
                "questions": [
                    {
                        "question": "Who?",
                        "options": ["A", "B"],
                        "correct": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = TestClient(
        studio_api.create_app(
            quizzes_dir=quizzes_dir,
            runtime_dir=tmp_path / "runtime",
        )
    )

    response = client.get("/api/groups")

    assert response.status_code == 200
    assert response.json()["groups"][0]["id"] == "sample"


def test_create_manual_group_writes_empty_draft_to_workspace(tmp_path: Path):
    client = TestClient(studio_api.create_app())

    response = client.post(
        "/api/groups/manual",
        json={
            "title": "Ручной квиз",
            "workspace_dir": str(tmp_path),
        },
    )

    assert response.status_code == 200
    group = response.json()["group"]
    assert group["name"] == "Ручной квиз"
    assert group["status"] == "draft"
    assert group["questions"] == []
    saved_path = tmp_path / "quizzes" / f"{group['id']}.json"
    assert saved_path.exists()
    settings = client.get("/api/settings").json()
    assert settings["quizzes_dir"] == str(tmp_path / "quizzes")


def test_archive_group_endpoint_moves_quiz_out_of_active_groups(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps({"quiz_title": "Sample", "questions": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    client = TestClient(
        studio_api.create_app(
            quizzes_dir=quizzes_dir,
            runtime_dir=tmp_path / "runtime",
        )
    )

    response = client.post("/api/groups/sample/archive")
    groups_response = client.get("/api/groups")

    assert response.status_code == 200
    assert response.json()["archived"] is True
    assert not (quizzes_dir / "sample.json").exists()
    assert (quizzes_dir / "_archive" / "sample.json").exists()
    assert groups_response.json()["groups"] == []


def test_delete_group_endpoint_removes_quiz_file(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps({"quiz_title": "Sample", "questions": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    client = TestClient(
        studio_api.create_app(
            quizzes_dir=quizzes_dir,
            runtime_dir=tmp_path / "runtime",
        )
    )

    response = client.post("/api/groups/sample/delete")

    assert response.status_code == 200
    assert response.json() == {"id": "sample", "deleted": True}
    assert not (quizzes_dir / "sample.json").exists()


def test_accounts_endpoint_returns_only_public_profiles(tmp_path: Path):
    account_store = tmp_path / "runtime" / "accounts"
    raw_phone = "+77001234567"
    api_hash = "super-secret-api-hash"
    session_path = tmp_path / "sessions" / "default.session"
    profile = _account_profile(
        tmp_path,
        "default",
        phone=raw_phone,
        api_hash=api_hash,
    )
    profile["telegram_session_path"] = str(session_path)
    profile["session_contents"] = "SESSION-CONTENTS-SHOULD-NOT-LEAK"
    _write_account_profiles(account_store, [profile])
    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            account_store_root=account_store,
        )
    )

    response = client.get("/api/accounts")

    assert response.status_code == 200
    payload = response.json()
    payload_text = json.dumps(payload, ensure_ascii=False)
    assert payload["accounts"][0] == {
        "id": "default",
        "display_name": "Default",
        "status": "enabled",
        "session_path_basename": "default.session",
        "telegram_phone_masked": "+*******4567",
        "is_active": True,
    }
    assert api_hash not in payload_text
    assert raw_phone not in payload_text
    assert str(session_path) not in payload_text
    assert "SESSION-CONTENTS-SHOULD-NOT-LEAK" not in payload_text
    assert "api_hash" not in payload_text
    assert "telegram_phone_masked" in payload_text


def test_current_account_endpoint_switches_profile_as_ui(tmp_path: Path):
    account_store = tmp_path / "runtime" / "accounts"
    _write_account_profiles(
        account_store,
        [
            _account_profile(tmp_path, "default"),
            _account_profile(tmp_path, "study"),
        ],
    )
    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            account_store_root=account_store,
        )
    )

    response = client.post("/api/accounts/current", json={"profile_id": "study"})
    current = client.get("/api/accounts/current")
    active_payload = json.loads(
        (account_store / accounts.ACTIVE_PROFILE_FILENAME).read_text(encoding="utf-8")
    )

    assert response.status_code == 200
    assert response.json()["account"]["id"] == "study"
    assert current.status_code == 200
    assert current.json()["account"]["id"] == "study"
    assert active_payload["active_profile_id"] == "study"
    assert active_payload["changed_by"] == "ui"


def test_create_account_endpoint_is_unavailable_for_browser_credentials(tmp_path: Path):
    account_store = tmp_path / "runtime" / "accounts"
    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            account_store_root=account_store,
        )
    )

    response = client.post(
        "/api/accounts",
        json={
            "display_name": "Рабочий профиль",
            "api_id": 98765,
            "api_hash": "very-secret-hash",
            "phone": "+77001234567",
        },
    )
    payload_text = json.dumps(response.json(), ensure_ascii=False)

    assert response.status_code == 405
    assert not (account_store / accounts.PROFILES_FILENAME).exists()
    assert "very-secret-hash" not in payload_text
    assert "+77001234567" not in payload_text
    assert "api_hash" not in payload_text


def test_update_account_endpoint_is_unavailable_for_browser_credentials(tmp_path: Path):
    account_store = tmp_path / "runtime" / "accounts"
    original_profile = _account_profile(tmp_path, "default")
    _write_account_profiles(account_store, [original_profile])
    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            account_store_root=account_store,
        )
    )

    response = client.patch(
        "/api/accounts/default",
        json={
            "display_name": "Основной профиль",
            "api_id": 98765,
            "api_hash": "very-secret-hash",
            "phone": "+77001234567",
        },
    )
    payload_text = json.dumps(response.json(), ensure_ascii=False)
    stored_profile = json.loads(
        (account_store / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )["profiles"][0]

    assert response.status_code == 405
    assert stored_profile == original_profile
    assert "very-secret-hash" not in payload_text
    assert "+77001234567" not in payload_text
    assert "api_hash" not in payload_text


class FakeTelegramLoginManager:
    def __init__(self):
        self.started_profiles: list[tuple[str, bool]] = []
        self.submitted_codes: list[tuple[str, str]] = []
        self.submitted_passwords: list[tuple[str, str]] = []
        self.status_requests: list[str] = []
        self.cancelled: list[str] = []

    async def start(self, profile_id: str, *, force_sms: bool = False) -> dict:
        self.started_profiles.append((profile_id, force_sms))
        if profile_id == "authorized":
            return {
                "step": "authorized",
                "account": {
                    "id": "authorized",
                    "display_name": "Authorized",
                    "status": "enabled_authorized",
                    "session_path_basename": "authorized.session",
                    "telegram_phone_masked": "+*******4567",
                    "is_active": True,
                },
            }
        return {
            "login_id": "login-1",
            "profile_id": profile_id,
            "step": "code_sent",
            "phone_masked": "+*******4567",
            "expires_at": "2026-06-19T12:05:00+00:00",
        }

    async def submit_code(self, login_id: str, code: str) -> dict:
        self.submitted_codes.append((login_id, code))
        if code == "2fa":
            return {"login_id": login_id, "step": "password_required"}
        return {
            "step": "authorized",
            "account": {
                "id": "default",
                "display_name": "Default",
                "status": "enabled_authorized",
                "session_path_basename": "default.session",
                "telegram_phone_masked": "+*******4567",
                "is_active": True,
            },
        }

    async def submit_password(self, login_id: str, password: str) -> dict:
        self.submitted_passwords.append((login_id, password))
        return {
            "step": "authorized",
            "account": {
                "id": "default",
                "display_name": "Default",
                "status": "enabled_authorized",
                "session_path_basename": "default.session",
                "telegram_phone_masked": "+*******4567",
                "is_active": True,
            },
        }

    async def status(self, login_id: str) -> dict:
        self.status_requests.append(login_id)
        return {
            "login_id": login_id,
            "profile_id": "default",
            "step": "code_sent",
            "phone_masked": "+*******4567",
            "expires_at": "2026-06-19T12:05:00+00:00",
        }

    async def cancel(self, login_id: str) -> dict:
        self.cancelled.append(login_id)
        return {"ok": True}


def test_telegram_auth_start_and_status_endpoints_return_public_flow(tmp_path: Path):
    manager = FakeTelegramLoginManager()
    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            telegram_login_manager=manager,
        )
    )

    start_response = client.post("/api/auth/telegram/start", json={"profile_id": "default"})
    status_response = client.get("/api/auth/telegram/login-1")

    assert start_response.status_code == 200
    assert start_response.json() == {
        "login_id": "login-1",
        "profile_id": "default",
        "step": "code_sent",
        "phone_masked": "+*******4567",
        "expires_at": "2026-06-19T12:05:00+00:00",
    }
    assert status_response.status_code == 200
    assert status_response.json()["step"] == "code_sent"
    assert manager.started_profiles == [("default", False)]
    assert manager.status_requests == ["login-1"]


def test_telegram_auth_start_can_force_sms_code_delivery(tmp_path: Path):
    manager = FakeTelegramLoginManager()
    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            telegram_login_manager=manager,
        )
    )

    response = client.post(
        "/api/auth/telegram/start",
        json={"profile_id": "default", "force_sms": True},
    )

    assert response.status_code == 200
    assert response.json()["step"] == "code_sent"
    assert manager.started_profiles == [("default", True)]


def test_telegram_auth_code_password_and_cancel_endpoints(tmp_path: Path):
    manager = FakeTelegramLoginManager()
    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            telegram_login_manager=manager,
        )
    )

    code_response = client.post(
        "/api/auth/telegram/code",
        json={"login_id": "login-1", "code": "2fa"},
    )
    password_response = client.post(
        "/api/auth/telegram/password",
        json={"login_id": "login-1", "password": "secret-password"},
    )
    cancel_response = client.delete("/api/auth/telegram/login-1")

    assert code_response.status_code == 200
    assert code_response.json() == {"login_id": "login-1", "step": "password_required"}
    assert password_response.status_code == 200
    assert password_response.json()["step"] == "authorized"
    assert password_response.json()["account"]["status"] == "enabled_authorized"
    assert cancel_response.status_code == 200
    assert cancel_response.json() == {"ok": True}
    assert manager.submitted_codes == [("login-1", "2fa")]
    assert manager.submitted_passwords == [("login-1", "secret-password")]
    assert manager.cancelled == ["login-1"]


def test_telegram_auth_already_authorized_start_returns_public_account(tmp_path: Path):
    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            telegram_login_manager=FakeTelegramLoginManager(),
        )
    )

    response = client.post("/api/auth/telegram/start", json={"profile_id": "authorized"})

    assert response.status_code == 200
    assert response.json()["step"] == "authorized"
    assert response.json()["account"]["id"] == "authorized"


def test_telegram_auth_errors_are_mapped_without_leaking_secrets(tmp_path: Path):
    raw_phone = "+77001234567"
    api_hash = "super-secret-api-hash"
    session_path = "/tmp/private.session"

    class FailingTelegramLoginManager:
        async def start(self, profile_id: str) -> dict:
            raise RuntimeError(
                f"leak attempt {raw_phone} {api_hash} {session_path}"
            )

    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            telegram_login_manager=FailingTelegramLoginManager(),
        )
    )

    response = client.post("/api/auth/telegram/start", json={"profile_id": "default"})
    payload_text = json.dumps(response.json(), ensure_ascii=False)

    assert response.status_code == 502
    assert response.json()["detail"] == "Telegram login service failed"
    assert raw_phone not in payload_text
    assert api_hash not in payload_text
    assert session_path not in payload_text


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (accounts.ProfileNotFoundError("missing"), 404),
        (accounts.ProfileDisabledError("disabled"), 409),
        (telegram_login.LoginExpiredError("expired"), 410),
        (telegram_login.LoginCredentialsMissingError("missing creds"), 409),
        (telegram_login.InvalidTelegramCodeError("bad code"), 400),
        (telegram_login.InvalidTelegramPasswordError("bad password"), 400),
        (telegram_login.TelegramLoginAuthError("telegram down"), 502),
    ],
)
def test_telegram_auth_error_mapping(tmp_path: Path, error: Exception, status_code: int):
    class FailingTelegramLoginManager:
        async def start(self, profile_id: str, *, force_sms: bool = False) -> dict:
            raise error

    client = TestClient(
        studio_api.create_app(
            runtime_dir=tmp_path / "runtime",
            telegram_login_manager=FailingTelegramLoginManager(),
        )
    )

    response = client.post("/api/auth/telegram/start", json={"profile_id": "default"})

    assert response.status_code == status_code


def test_active_run_endpoint_returns_inactive_without_active_run(tmp_path: Path):
    client = TestClient(studio_api.create_app(runtime_dir=tmp_path / "runtime"))

    response = client.get("/api/runs/active")

    assert response.status_code == 200
    assert response.json() == {"active": False}


def test_run_endpoints_return_safe_snapshot_and_pause_without_live_calls(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    quiz_path = _clean_quiz_file(tmp_path)
    store = runs.RunStore(runtime_dir)
    store.create_upload_run(
        run_id="run-one",
        quiz_file=quiz_path,
        quiz_name="Studio adapter quiz",
        account_profile_id="default",
        status="running",
        source_question_count=1,
    )
    store.update_status(
        "run-one",
        "running",
        last_error={
            "code": "telegram_timeout",
            "message": "Timed out",
            "api_hash": "must-not-leak",
            "session_path": "/tmp/private.session",
            "phone": "+77001234567",
        },
    )
    client = TestClient(studio_api.create_app(runtime_dir=runtime_dir))

    list_response = client.get("/api/runs")
    active_response = client.get("/api/runs/active")
    run_response = client.get("/api/runs/run-one")
    pause_response = client.post("/api/runs/run-one/pause", json={})

    assert list_response.status_code == 200
    assert [item["run_id"] for item in list_response.json()["runs"]] == ["run-one"]
    assert active_response.status_code == 200
    assert active_response.json()["active"] is True
    assert run_response.status_code == 200
    assert run_response.json()["run_id"] == "run-one"
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"
    assert store.load_run("run-one").status == "paused"

    payload_text = json.dumps(
        {
            "list": list_response.json(),
            "active": active_response.json(),
            "run": run_response.json(),
            "pause": pause_response.json(),
        },
        ensure_ascii=False,
    )
    assert "must-not-leak" not in payload_text
    assert "private.session" not in payload_text
    assert "+77001234567" not in payload_text


def test_settings_endpoint_returns_paths(tmp_path: Path):
    source_path = tmp_path / "questions_v2.json"
    media_dir = tmp_path / "media"
    quizzes_dir = tmp_path / "quizzes"
    client = TestClient(
        studio_api.create_app(
            source_path=source_path,
            media_dir=media_dir,
            quizzes_dir=quizzes_dir,
            runtime_dir=tmp_path / "runtime",
        )
    )

    response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(source_path)
    assert payload["media_dir"] == str(media_dir)
    assert payload["quizzes_dir"] == str(quizzes_dir)


def test_validate_job_returns_report(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "questions": [
                    {
                        "question": "Who?",
                        "options": ["A", "B"],
                        "correct": 1,
                        "explanation": "",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = TestClient(
        studio_api.create_app(
            quizzes_dir=quizzes_dir,
            runtime_dir=tmp_path / "runtime",
        )
    )

    response = client.post("/api/jobs/validate", json={"group_id": "sample", "strict": False})

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    snapshot = client.get(f"/api/jobs/{job_id}").json()
    assert snapshot["status"] == "completed"
    assert snapshot["result"]["report"]["questions_total"] == 1
    review_artifact = snapshot["result"]["review_artifact"]
    assert Path(review_artifact["path"]).exists()
    assert snapshot["result"]["upload_validation"]["hard_error_count"] == 0


def test_validate_job_returns_report_errors_for_invalid_question(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    long_option = (
        "основными формами кооперации крестьян стали товарищества по совместной "
        "обработке земли, сельхозартели и коммуны"
    )
    (quizzes_dir / "sample.json").write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "questions": [
                    {
                        "question": "Who?",
                        "options": ["A", long_option, "C"],
                        "correct": 1,
                        "explanation": "",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = TestClient(
        studio_api.create_app(
            quizzes_dir=quizzes_dir,
            runtime_dir=tmp_path / "runtime",
        )
    )

    response = client.post("/api/jobs/validate", json={"group_id": "sample", "strict": False})

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    snapshot = client.get(f"/api/jobs/{job_id}").json()
    assert snapshot["status"] == "completed"
    report = snapshot["result"]["report"]
    assert snapshot["result"]["exit_code"] == 1
    assert report["errors"] == [
        {
            "index": 1,
            "source_item_id": None,
            "question": "Who?",
            "code": "too_long_option",
            "message": "Вариант #2 длиннее 100 символов. Сократите вариант перед запуском.",
            "option": {
                "index": 2,
                "text": long_option,
                "length": len(long_option),
                "max_length": 100,
            },
        }
    ]


def test_upload_job_blocks_without_fresh_review_artifact(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    _write_legacy_group(quizzes_dir)
    client = TestClient(
        studio_api.create_app(
            quizzes_dir=quizzes_dir,
            runtime_dir=tmp_path / "runtime",
        )
    )

    response = client.post("/api/jobs/upload", json={"group_id": "sample"})
    snapshot = _wait_for_job(client, response.json()["job_id"])

    assert response.status_code == 200
    assert snapshot["status"] == "failed"
    assert "Review artifact is required" in snapshot["error"]


def test_upload_job_blocks_stale_review_artifact(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    group_path = _write_legacy_group(quizzes_dir, question="Original?")
    client = TestClient(
        studio_api.create_app(
            quizzes_dir=quizzes_dir,
            runtime_dir=tmp_path / "runtime",
        )
    )

    validate_response = client.post("/api/jobs/validate", json={"group_id": "sample", "strict": False})
    validate_snapshot = _wait_for_job(client, validate_response.json()["job_id"])
    assert validate_snapshot["status"] == "completed"
    assert "review_artifact" in validate_snapshot["result"]

    payload = json.loads(group_path.read_text(encoding="utf-8"))
    payload["questions"][0]["question"] = "Changed after validation?"
    group_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    upload_response = client.post("/api/jobs/upload", json={"group_id": "sample"})
    upload_snapshot = _wait_for_job(client, upload_response.json()["job_id"])

    assert upload_snapshot["status"] == "failed"
    assert "review_decisions_stale" in upload_snapshot["error"]


def test_upload_job_blocks_missing_media_before_live_upload(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    _write_legacy_group(quizzes_dir, media=["media/missing.png"])
    client = TestClient(
        studio_api.create_app(
            quizzes_dir=quizzes_dir,
            media_dir=tmp_path / "media",
            runtime_dir=tmp_path / "runtime",
        )
    )

    response = client.post("/api/jobs/upload", json={"group_id": "sample"})
    snapshot = _wait_for_job(client, response.json()["job_id"])

    assert snapshot["status"] == "failed"
    assert "media_missing" in snapshot["error"]


def test_upload_endpoint_rejects_protected_active_run_without_confirmation(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    runtime_dir = tmp_path / "runtime"
    _write_legacy_group(quizzes_dir)
    quiz_path = _clean_quiz_file(tmp_path)
    store = runs.RunStore(runtime_dir)
    store.create_upload_run(
        run_id="active-run",
        quiz_file=quiz_path,
        quiz_name="Active",
        account_profile_id="default",
        source_question_count=1,
    )
    store.record_question_uploaded("active-run", 1)
    client = TestClient(studio_api.create_app(quizzes_dir=quizzes_dir, runtime_dir=runtime_dir))

    response = client.post("/api/jobs/upload", json={"group_id": "sample"})
    detail = response.json()["detail"]
    payload_text = json.dumps(detail, ensure_ascii=False)

    assert response.status_code == 409
    assert detail["code"] == "protected_active_run"
    assert detail["required_action"] == "confirm_replace_active"
    assert detail["active_run"]["run_id"] == "active-run"
    assert "api_hash" not in payload_text
    assert "session" not in payload_text
    assert "+77001234567" not in payload_text


def test_upload_endpoint_confirmed_replace_reaches_service_with_replace_active(tmp_path: Path, monkeypatch):
    quizzes_dir = tmp_path / "quizzes"
    runtime_dir = tmp_path / "runtime"
    _write_legacy_group(quizzes_dir)
    quiz_path = _clean_quiz_file(tmp_path)
    store = runs.RunStore(runtime_dir)
    store.create_upload_run(
        run_id="active-run",
        quiz_file=quiz_path,
        quiz_name="Active",
        account_profile_id="default",
        source_question_count=1,
    )
    store.record_question_uploaded("active-run", 1)
    calls: list[dict] = []

    class FakeUploadService:
        def __init__(self, **kwargs):
            pass

        async def start_upload(self, **kwargs):
            calls.append(kwargs)
            return runs.UploadRun(
                run_id="new-run",
                quiz_file=str(kwargs["quiz_file"]),
                quiz_file_hash=runs.compute_file_sha256(kwargs["quiz_file"]),
                quiz_name=kwargs["quiz_name"],
                account_profile_id="default",
                status="completed",
                source_question_count=1,
            )

    monkeypatch.setattr(studio_api.upload_service, "UploadService", FakeUploadService)
    client = TestClient(studio_api.create_app(quizzes_dir=quizzes_dir, runtime_dir=runtime_dir))

    response = client.post(
        "/api/jobs/upload",
        json={"group_id": "sample", "confirm_replace_active": True},
    )
    snapshot = _wait_for_job(client, response.json()["job_id"])

    assert response.status_code == 200
    assert snapshot["status"] == "completed"
    assert calls[0]["replace_active"] is True


def test_create_from_docx_exports_editor_json_without_openai(tmp_path: Path, monkeypatch):
    def fake_build_output(docx_path, output_path, media_dir, title, description):
        data = {
            "quiz_title": title,
            "quiz_description": description,
            "format_version": "2.0",
            "report": {"items_total": 2},
            "questions": [
                {
                    "id": 1,
                    "date": "10 мая",
                    "section": "УТРО",
                    "question": "Вопрос?",
                    "options": ["A", "B", "C"],
                    "correct": 2,
                    "type": "single",
                    "source": "docx_v2",
                },
                {
                    "id": 2,
                    "date": "10 мая",
                    "section": "УТРО",
                    "question": "Требует проверки?",
                    "options": ["A"],
                    "correct": None,
                    "type": "needs_answer_review",
                    "source": "docx_v2",
                },
            ],
        }
        Path(output_path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    monkeypatch.setattr(studio_api, "build_output", fake_build_output)
    client = TestClient(studio_api.create_app())

    response = client.post(
        "/api/jobs/create-from-docx",
        data={
            "title": "Custom quiz",
            "description": "Local parser",
            "workspace_dir": str(tmp_path),
        },
        files={
            "file": (
                "sample.docx",
                b"not a real docx because build_output is patched",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(50):
        snapshot = client.get(f"/api/jobs/{job_id}").json()
        if snapshot["status"] != "running":
            break
        time.sleep(0.01)

    assert snapshot["status"] == "completed"
    created = snapshot["result"]["groups"][0]
    output_path = Path(created["output"])
    assert output_path.parent == tmp_path / "quizzes"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["format_version"] == "2.0-direct"
    assert payload["quiz_title"] == "Custom quiz"
    assert payload["questions"][0]["correct"] == 2
    assert "Парсер не нашёл правильный ответ." in payload["questions"][1]["quality_flags"]

    group_response = client.get(f"/api/groups/{created['id']}")
    assert group_response.status_code == 200
    group = group_response.json()
    assert group["status"] == "review"
    assert group["questions"][1]["correct"] == -1


def test_media_endpoint_resolves_current_media_dir(tmp_path: Path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    image = media_dir / "image_001.png"
    image.write_bytes(b"fake-image")
    client = TestClient(studio_api.create_app(media_dir=media_dir))

    plain_response = client.get("/api/media/image_001.png")
    prefixed_response = client.get("/api/media/media/image_001.png")

    assert plain_response.status_code == 200
    assert plain_response.content == b"fake-image"
    assert prefixed_response.status_code == 200
    assert prefixed_response.content == b"fake-image"


def test_media_endpoint_rejects_traversal_absolute_workspace_and_runtime(tmp_path: Path):
    media_dir = tmp_path / "media"
    workspace_dir = tmp_path / "workspace"
    runtime_dir = tmp_path / "runtime"
    media_dir.mkdir()
    workspace_dir.mkdir()
    runtime_dir.mkdir()
    outside = tmp_path / "outside.png"
    workspace_image = workspace_dir / "leak.png"
    workspace_json = workspace_dir / "questions_v2.json"
    runtime_image = runtime_dir / "state.png"
    for path in [outside, workspace_image, workspace_json, runtime_image]:
        path.write_bytes(b"private")
    client = TestClient(
        studio_api.create_app(
            media_dir=media_dir,
            runtime_dir=runtime_dir,
            source_path=workspace_json,
        )
    )

    blocked_paths = [
        "%2E%2E/outside.png",
        quote(str(outside), safe=""),
        quote(str(workspace_image), safe=""),
        quote(str(workspace_json), safe=""),
        quote(str(runtime_image), safe=""),
        "../outside.png",
        "workspace/leak.png",
        "questions_v2.json",
        "state.png",
    ]

    for media_path in blocked_paths:
        response = client.get(f"/api/media/{media_path}")
        assert response.status_code == 404, media_path


def test_media_endpoint_rejects_non_allowed_suffix_under_media_dir(tmp_path: Path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "secret.txt").write_text("private", encoding="utf-8")
    client = TestClient(studio_api.create_app(media_dir=media_dir))

    response = client.get("/api/media/secret.txt")

    assert response.status_code == 404


def test_upload_media_saves_image_to_current_media_dir(tmp_path: Path):
    media_dir = tmp_path / "media"
    client = TestClient(studio_api.create_app(media_dir=media_dir))

    response = client.post(
        "/api/media/upload",
        files={"file": ("context.png", b"image-bytes", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"].startswith("media/")
    assert payload["path"].endswith("_context.png")
    saved_path = Path(payload["saved_path"])
    assert saved_path.parent == media_dir
    assert saved_path.read_bytes() == b"image-bytes"
    assert client.get(f"/api/media/{payload['path']}").content == b"image-bytes"


def test_upload_media_rejects_non_image_extension(tmp_path: Path):
    client = TestClient(studio_api.create_app(media_dir=tmp_path / "media"))

    response = client.post(
        "/api/media/upload",
        files={"file": ("context.txt", b"text", "text/plain")},
    )

    assert response.status_code == 400
