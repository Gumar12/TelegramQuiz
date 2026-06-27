import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.telegram_login import (
    LoginExpiredError,
    TelegramLoginAuthError,
    TelegramLoginManager,
    UnknownLoginError,
)


RAW_PHONE = "+77001234567"
API_HASH = "api-hash-should-not-leak"
SESSION_PATH = f"/tmp/telegramquiz-test-{uuid.uuid4().hex}.session"
PHONE_CODE_HASH = "phone-code-hash-should-stay-in-memory"
SESSION_CONTENTS = "session-contents-should-not-leak"
VALID_CODE = "24680"
VALID_PASSWORD = "ultra-secret-password"
POSIX_MODE_REASON = "POSIX permission bits are not reliable on Windows"


class PasswordRequiredError(Exception):
    pass


class PhoneCodeInvalidError(Exception):
    pass


class PhoneCodeExpiredError(Exception):
    pass


class PhoneCodeHashInvalidError(Exception):
    pass


class TokenSequence:
    def __init__(self):
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"login-{self.index}"


class FrozenClock:
    def __init__(self):
        self.value = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class FakePublicAccount:
    def __init__(self, profile_id: str):
        self.profile_id = profile_id

    def to_dict(self) -> dict:
        return {
            "id": self.profile_id,
            "display_name": "Default",
            "status": "enabled_authorized",
            "telegram_phone_masked": "+*******4567",
            "is_active": True,
        }


class FakeAccounts:
    def __init__(
        self,
        *,
        phone: str = RAW_PHONE,
        api_hash: str = API_HASH,
        session_path: str = SESSION_PATH,
        is_authorized: bool = False,
    ):
        self.profile = SimpleNamespace(
            id="default",
            display_name="Default",
            api_id=12345,
            api_hash=api_hash,
            phone=phone,
            session_path=session_path,
            session_contents=SESSION_CONTENTS,
            is_enabled=True,
            is_authorized=is_authorized,
        )
        self.marked: list[tuple[str, bool]] = []

    def _load_private_profile(self, profile_id: str, *, store_root=None, config_module=None):
        assert profile_id == self.profile.id
        return self.profile

    def mark_profile_authorized(
        self,
        profile_id: str,
        *,
        authorized: bool = True,
        store_root=None,
        config_module=None,
    ):
        self.marked.append((profile_id, authorized))
        return FakePublicAccount(profile_id)


class FakeTelegramClient:
    def __init__(
        self,
        *,
        authorized: bool = False,
        code_error: BaseException | None = None,
        password_required: bool = False,
    ):
        self.authorized = authorized
        self.code_error = code_error
        self.password_required = password_required
        self.connected = False
        self.disconnected = False
        self.phone_code_hash: str | None = None
        self.sent_code_to: list[str] = []
        self.send_code_force_sms: list[bool] = []
        self.sign_in_calls: list[dict] = []

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def send_code_request(self, phone: str, *, force_sms: bool = False):
        self.sent_code_to.append(phone)
        self.send_code_force_sms.append(force_sms)
        self.phone_code_hash = PHONE_CODE_HASH
        return SimpleNamespace(phone_code_hash=PHONE_CODE_HASH)

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        password: str | None = None,
        phone_code_hash: str | None = None,
    ):
        self.sign_in_calls.append(
            {
                "phone": phone,
                "code": code,
                "password": password,
                "phone_code_hash": phone_code_hash,
            }
        )
        if password is not None:
            if password != VALID_PASSWORD:
                raise ValueError("PASSWORD_HASH_INVALID")
            self.authorized = True
            return SimpleNamespace(id=1)

        effective_phone_code_hash = phone_code_hash or self.phone_code_hash
        if effective_phone_code_hash != PHONE_CODE_HASH:
            raise AssertionError("phone_code_hash was not preserved in memory")
        if self.code_error is not None:
            raise self.code_error
        if code != VALID_CODE:
            raise ValueError("PHONE_CODE_INVALID")
        if self.password_required:
            raise PasswordRequiredError("SESSION_PASSWORD_NEEDED")
        self.authorized = True
        return SimpleNamespace(id=1)


class SessionWritingClient(FakeTelegramClient):
    def __init__(self, session_path: Path):
        super().__init__()
        self.session_path = session_path

    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        password: str | None = None,
        phone_code_hash: str | None = None,
    ):
        result = await super().sign_in(
            phone=phone,
            code=code,
            password=password,
            phone_code_hash=phone_code_hash,
        )
        self.session_path.write_text("session", encoding="utf-8")
        self.session_path.chmod(0o644)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = self.session_path.with_name(f"{self.session_path.name}{suffix}")
            sidecar.write_text("sidecar", encoding="utf-8")
            sidecar.chmod(0o644)
        return result


class DelayedSendCodeClient(FakeTelegramClient):
    def __init__(self):
        super().__init__()
        self.release_send_code = asyncio.Event()
        self.send_code_started = asyncio.Event()

    async def send_code_request(self, phone: str):
        self.send_code_started.set()
        await self.release_send_code.wait()
        return await super().send_code_request(phone)


class DelayedConnectClient(FakeTelegramClient):
    def __init__(self, connect_started: asyncio.Event, connect_release: asyncio.Event):
        super().__init__()
        self.connect_started = connect_started
        self.connect_release = connect_release

    async def connect(self):
        self.connect_started.set()
        await self.connect_release.wait()
        self.connected = True


class FakeClientFactory:
    def __init__(self, clients: list[FakeTelegramClient]):
        self.clients = clients
        self.profile_ids: list[str] = []

    def __call__(self, profile_id: str, *, store_root=None, config_module=None):
        self.profile_ids.append(profile_id)
        return self.clients.pop(0)


def _manager(
    accounts: FakeAccounts,
    factory: FakeClientFactory,
    *,
    clock: FrozenClock | None = None,
    ttl_seconds: int = 300,
):
    return TelegramLoginManager(
        account_module=accounts,
        config_module=SimpleNamespace(),
        store_root=Path("/unused/accounts"),
        client_factory=factory,
        clock=clock or FrozenClock(),
        ttl_seconds=ttl_seconds,
        token_factory=TokenSequence(),
    )


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_start_sends_code_and_returns_public_snapshot():
    accounts = FakeAccounts()
    client = FakeTelegramClient()
    manager = _manager(accounts, FakeClientFactory([client]))

    result = asyncio.run(manager.start("default"))

    assert result["login_id"] == "login-1"
    assert result["profile_id"] == "default"
    assert result["step"] == "code_sent"
    assert result["phone_masked"] == "+*******4567"
    assert "phone_code_hash" not in result
    assert client.connected is True
    assert client.disconnected is False
    assert client.sent_code_to == [RAW_PHONE]
    assert client.send_code_force_sms == [False]


def test_start_can_force_sms_code_delivery():
    accounts = FakeAccounts()
    client = FakeTelegramClient()
    manager = _manager(accounts, FakeClientFactory([client]))

    result = asyncio.run(manager.start("default", force_sms=True))

    assert result["step"] == "code_sent"
    assert client.sent_code_to == [RAW_PHONE]
    assert client.send_code_force_sms == [True]


def test_start_for_unauthorized_profile_resets_stale_session_file(tmp_path):
    session_path = tmp_path / "stale.session"
    journal_path = session_path.with_name(f"{session_path.name}-journal")
    shm_path = session_path.with_name(f"{session_path.name}-shm")
    wal_path = session_path.with_name(f"{session_path.name}-wal")
    session_path.write_text("stale", encoding="utf-8")
    journal_path.write_text("stale-journal", encoding="utf-8")
    shm_path.write_text("stale-shm", encoding="utf-8")
    wal_path.write_text("stale-wal", encoding="utf-8")
    accounts = FakeAccounts(session_path=str(session_path), is_authorized=False)
    client = FakeTelegramClient()
    manager = _manager(accounts, FakeClientFactory([client]))

    asyncio.run(manager.start("default"))

    assert not session_path.exists()
    assert not journal_path.exists()
    assert not shm_path.exists()
    assert not wal_path.exists()
    assert client.sent_code_to == [RAW_PHONE]


def test_start_for_authorized_profile_keeps_existing_session_file(tmp_path):
    session_path = tmp_path / "authorized.session"
    session_path.write_text("authorized", encoding="utf-8")
    accounts = FakeAccounts(session_path=str(session_path), is_authorized=True)
    client = FakeTelegramClient(authorized=True)
    manager = _manager(accounts, FakeClientFactory([client]))

    asyncio.run(manager.start("default"))

    assert session_path.read_text(encoding="utf-8") == "authorized"
    assert client.disconnected is True


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_start_for_authorized_profile_chmods_existing_session_files(tmp_path):
    session_path = tmp_path / "authorized.session"
    session_path.write_text("authorized", encoding="utf-8")
    session_path.chmod(0o644)
    sidecars = [
        session_path.with_name(f"{session_path.name}-wal"),
        session_path.with_name(f"{session_path.name}-shm"),
        session_path.with_name(f"{session_path.name}-journal"),
    ]
    for sidecar in sidecars:
        sidecar.write_text("sidecar", encoding="utf-8")
        sidecar.chmod(0o644)
    accounts = FakeAccounts(session_path=str(session_path), is_authorized=True)
    client = FakeTelegramClient(authorized=True)
    manager = _manager(accounts, FakeClientFactory([client]))

    asyncio.run(manager.start("default"))

    assert _mode(session_path) == 0o600
    for sidecar in sidecars:
        assert _mode(sidecar) == 0o600


def test_already_authorized_client_returns_authorized_and_marks_account():
    accounts = FakeAccounts()
    client = FakeTelegramClient(authorized=True)
    manager = _manager(accounts, FakeClientFactory([client]))

    result = asyncio.run(manager.start("default"))

    assert result == {
        "step": "authorized",
        "account": FakePublicAccount("default").to_dict(),
    }
    assert accounts.marked == [("default", True)]
    assert client.disconnected is True


def test_submit_code_authorizes_marks_account_and_disconnects():
    accounts = FakeAccounts()
    client = FakeTelegramClient()
    manager = _manager(accounts, FakeClientFactory([client]))

    started = asyncio.run(manager.start("default"))
    result = asyncio.run(manager.submit_code(started["login_id"], VALID_CODE))

    assert result["step"] == "authorized"
    assert result["account"]["status"] == "enabled_authorized"
    assert accounts.marked == [("default", True)]
    assert client.disconnected is True
    assert client.sign_in_calls[-1]["phone_code_hash"] == PHONE_CODE_HASH
    assert client.phone_code_hash == PHONE_CODE_HASH
    with pytest.raises(UnknownLoginError):
        asyncio.run(manager.status(started["login_id"]))


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_submit_code_chmods_session_files_created_during_login(tmp_path):
    session_path = tmp_path / "created.session"
    accounts = FakeAccounts(session_path=str(session_path), is_authorized=False)
    client = SessionWritingClient(session_path)
    manager = _manager(accounts, FakeClientFactory([client]))

    started = asyncio.run(manager.start("default"))
    asyncio.run(manager.submit_code(started["login_id"], VALID_CODE))

    assert _mode(session_path) == 0o600
    for suffix in ("-wal", "-shm", "-journal"):
        assert _mode(session_path.with_name(f"{session_path.name}{suffix}")) == 0o600


def test_password_required_then_password_success():
    accounts = FakeAccounts()
    client = FakeTelegramClient(password_required=True)
    manager = _manager(accounts, FakeClientFactory([client]))

    started = asyncio.run(manager.start("default"))
    next_step = asyncio.run(manager.submit_code(started["login_id"], VALID_CODE))

    assert next_step["step"] == "password_required"
    assert next_step["login_id"] == started["login_id"]
    assert client.disconnected is False

    result = asyncio.run(
        manager.submit_password(started["login_id"], VALID_PASSWORD)
    )

    assert result["step"] == "authorized"
    assert accounts.marked == [("default", True)]
    assert client.disconnected is True


@pytest.mark.parametrize(
    ("code_error", "message", "discarded"),
    [
        (PhoneCodeInvalidError("PHONE_CODE_INVALID"), "Telegram rejected the login code", False),
        (PhoneCodeExpiredError("PHONE_CODE_EXPIRED"), "Telegram login code expired", True),
        (
            PhoneCodeHashInvalidError("PHONE_CODE_HASH_INVALID: An invalid or expired phone_code_hash was provided"),
            "Telegram code request expired",
            True,
        ),
    ],
)
def test_submit_code_maps_telethon_code_errors_without_generic_failure(code_error, message, discarded):
    accounts = FakeAccounts()
    client = FakeTelegramClient(code_error=code_error)
    manager = _manager(accounts, FakeClientFactory([client]))

    started = asyncio.run(manager.start("default"))

    with pytest.raises(TelegramLoginAuthError) as exc_info:
        asyncio.run(manager.submit_code(started["login_id"], VALID_CODE))

    assert str(exc_info.value) == message
    assert client.disconnected is discarded
    if discarded:
        with pytest.raises(UnknownLoginError):
            asyncio.run(manager.status(started["login_id"]))
    else:
        assert asyncio.run(manager.status(started["login_id"]))["login_id"] == started["login_id"]


def test_submit_code_unknown_telegram_error_returns_sanitized_reason():
    accounts = FakeAccounts()
    client = FakeTelegramClient(
        code_error=RuntimeError(f"sign in failed for {RAW_PHONE} {API_HASH} {SESSION_PATH}")
    )
    manager = _manager(accounts, FakeClientFactory([client]))

    started = asyncio.run(manager.start("default"))

    with pytest.raises(TelegramLoginAuthError) as exc_info:
        asyncio.run(manager.submit_code(started["login_id"], VALID_CODE))

    message = str(exc_info.value)
    assert "RuntimeError" in message
    assert "sign in failed" in message
    assert RAW_PHONE not in message
    assert API_HASH not in message
    assert SESSION_PATH not in message


def test_cancel_disconnects_and_removes_flow():
    accounts = FakeAccounts()
    client = FakeTelegramClient()
    manager = _manager(accounts, FakeClientFactory([client]))

    started = asyncio.run(manager.start("default"))
    result = asyncio.run(manager.cancel(started["login_id"]))

    assert result == {"ok": True}
    assert client.disconnected is True
    with pytest.raises(UnknownLoginError):
        asyncio.run(manager.status(started["login_id"]))


def test_expired_flow_is_cleaned_up_and_cannot_be_reused():
    clock = FrozenClock()
    accounts = FakeAccounts()
    client = FakeTelegramClient()
    manager = _manager(
        accounts,
        FakeClientFactory([client]),
        clock=clock,
        ttl_seconds=10,
    )

    started = asyncio.run(manager.start("default"))
    clock.advance(11)

    with pytest.raises(LoginExpiredError):
        asyncio.run(manager.status(started["login_id"]))
    assert client.disconnected is True
    with pytest.raises(UnknownLoginError):
        asyncio.run(manager.submit_code(started["login_id"], VALID_CODE))


def test_new_start_after_expired_code_replaces_expired_flow():
    accounts = FakeAccounts()
    expired_client = FakeTelegramClient(code_error=PhoneCodeExpiredError("PHONE_CODE_EXPIRED"))
    next_client = FakeTelegramClient()
    manager = _manager(accounts, FakeClientFactory([expired_client, next_client]))

    expired = asyncio.run(manager.start("default"))
    with pytest.raises(TelegramLoginAuthError) as exc_info:
        asyncio.run(manager.submit_code(expired["login_id"], VALID_CODE))

    assert str(exc_info.value) == "Telegram login code expired"
    fresh = asyncio.run(manager.start("default"))
    result = asyncio.run(manager.submit_code(fresh["login_id"], VALID_CODE))

    assert fresh["login_id"] == "login-2"
    assert result["step"] == "authorized"
    assert expired_client.disconnected is True
    assert next_client.disconnected is True


def test_starting_new_flow_replaces_and_disconnects_previous_profile_flow():
    accounts = FakeAccounts()
    first_client = FakeTelegramClient()
    second_client = FakeTelegramClient()
    manager = _manager(
        accounts,
        FakeClientFactory([first_client, second_client]),
    )

    first = asyncio.run(manager.start("default"))
    second = asyncio.run(manager.start("default"))

    assert first["login_id"] == "login-1"
    assert second["login_id"] == "login-2"
    assert first_client.disconnected is True
    assert second_client.disconnected is False
    with pytest.raises(UnknownLoginError):
        asyncio.run(manager.status(first["login_id"]))


def test_concurrent_start_for_same_profile_keeps_only_latest_flow():
    async def run_scenario():
        accounts = FakeAccounts()
        first_client = DelayedSendCodeClient()
        second_client = FakeTelegramClient()
        manager = _manager(
            accounts,
            FakeClientFactory([first_client, second_client]),
        )

        first_task = asyncio.create_task(manager.start("default"))
        await first_client.send_code_started.wait()
        second_task = asyncio.create_task(manager.start("default"))
        await asyncio.sleep(0.05)

        assert second_client.connected is False
        first_client.release_send_code.set()
        first = await first_task
        second = await second_task
        return manager, first, second, first_client, second_client

    manager, first, second, first_client, second_client = asyncio.run(run_scenario())

    assert first["login_id"] == "login-1"
    assert second["login_id"] == "login-2"
    assert first_client.disconnected is True
    assert second_client.disconnected is False
    with pytest.raises(UnknownLoginError):
        asyncio.run(manager.status(first["login_id"]))
    assert asyncio.run(manager.status(second["login_id"]))["login_id"] == "login-2"


def test_concurrent_start_for_same_profile_via_session_lock_across_managers(tmp_path: Path):
    async def run_scenario():
        session_path = tmp_path / "default.session"
        accounts = FakeAccounts(session_path=str(session_path))
        connect_started = asyncio.Event()
        connect_release = asyncio.Event()
        first_client = DelayedConnectClient(connect_started, connect_release)
        second_client = FakeTelegramClient()
        first_manager = _manager(
            accounts,
            FakeClientFactory([first_client]),
        )
        second_manager = _manager(
            accounts,
            FakeClientFactory([second_client]),
        )

        first_task = asyncio.create_task(first_manager.start("default"))
        await connect_started.wait()
        second_task = asyncio.create_task(second_manager.start("default"))
        await asyncio.sleep(0.05)

        assert second_client.connected is False
        connect_release.set()
        first = await first_task
        second = await second_task
        return first, second, first_client, second_client

    first, second, first_client, second_client = asyncio.run(run_scenario())

    assert first["step"] == "code_sent"
    assert second["step"] == "code_sent"
    assert first_client.connected is True
    assert second_client.connected is True


def test_start_error_returns_sanitized_telegram_reason_without_login_flow():
    accounts = FakeAccounts()

    class FailingSendCodeClient(FakeTelegramClient):
        async def send_code_request(self, phone: str):
            raise RuntimeError(
                f"send failed for {phone} {API_HASH} {SESSION_PATH}"
            )

    client = FailingSendCodeClient()
    manager = _manager(accounts, FakeClientFactory([client]))

    with pytest.raises(TelegramLoginAuthError) as exc_info:
        asyncio.run(manager.start("default"))

    message = str(exc_info.value)
    assert "RuntimeError" in message
    assert "send failed" in message
    assert RAW_PHONE not in message
    assert API_HASH not in message
    assert SESSION_PATH not in message
    assert "<phone>" in message
    assert "<token>" in message
    assert client.disconnected is True


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_start_failure_chmods_sidecars_created_during_disconnect(tmp_path):
    session_path = tmp_path / "start-failure.session"
    accounts = FakeAccounts(session_path=str(session_path))

    class FailingSendCodeClient(FakeTelegramClient):
        def __init__(self):
            super().__init__()
            self.session_path = session_path

        async def send_code_request(self, phone: str):
            raise RuntimeError("send failed")

        async def disconnect(self):
            await super().disconnect()
            self.session_path.write_text("session", encoding="utf-8")
            self.session_path.chmod(0o644)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = self.session_path.with_name(f"{self.session_path.name}{suffix}")
                sidecar.write_text("sidecar", encoding="utf-8")
                sidecar.chmod(0o644)

    client = FailingSendCodeClient()
    manager = _manager(accounts, FakeClientFactory([client]))

    with pytest.raises(TelegramLoginAuthError):
        asyncio.run(manager.start("default"))

    assert client.disconnected is True
    assert _mode(session_path) == 0o600
    for suffix in ("-wal", "-shm", "-journal"):
        assert _mode(session_path.with_name(f"{session_path.name}{suffix}")) == 0o600


class QrPasswordError(Exception):
    pass


class FakeQRLogin:
    def __init__(self, client: "FakeQrClient", script: list[str]):
        self._client = client
        self._script = list(script)
        self.url = "tg://login?token=token-1"
        self.expires = None
        self.recreate_count = 0
        self.wait_calls = 0
        self.release = asyncio.Event()

    async def recreate(self) -> None:
        self.recreate_count += 1
        self.url = f"tg://login?token=token-{self.recreate_count + 1}"

    async def wait(self, timeout=None):
        index = self.wait_calls
        self.wait_calls += 1
        action = self._script[index] if index < len(self._script) else self._script[-1]
        if action == "timeout":
            raise asyncio.TimeoutError()
        if action == "password":
            raise QrPasswordError("SESSION_PASSWORD_NEEDED")
        if action == "hang":
            await self.release.wait()
            raise AssertionError("hang action was released unexpectedly")
        if action == "user":
            self._client.authorized = True
            return SimpleNamespace(id=1)
        raise AssertionError(f"unknown qr action {action!r}")


class FakeQrClient(FakeTelegramClient):
    def __init__(self, *, authorized: bool = False, script: list[str] | None = None):
        super().__init__(authorized=authorized)
        self._script = script or ["user"]
        self.qr_login_calls = 0
        self.qr: FakeQRLogin | None = None

    async def qr_login(self, ignored_ids=None):
        self.qr_login_calls += 1
        self.qr = FakeQRLogin(self, self._script)
        return self.qr


async def _wait_until(predicate, *, attempts: int = 200, delay: float = 0.005):
    for _ in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(delay)
    return False


def test_qr_start_already_authorized_marks_account_without_building_qr():
    accounts = FakeAccounts(is_authorized=True)
    client = FakeQrClient(authorized=True)
    manager = _manager(accounts, FakeClientFactory([client]))

    result = asyncio.run(manager.start_qr("default"))

    assert result == {
        "step": "authorized",
        "account": FakePublicAccount("default").to_dict(),
    }
    assert accounts.marked == [("default", True)]
    assert client.qr_login_calls == 0
    assert client.disconnected is True


def test_qr_start_returns_pending_snapshot_and_authorizes_on_scan():
    async def scenario():
        accounts = FakeAccounts()
        client = FakeQrClient(script=["user"])
        manager = _manager(accounts, FakeClientFactory([client]))

        started = await manager.start_qr("default")
        task = manager._flows[started["login_id"]].task
        await task
        return started, accounts, client, manager

    started, accounts, client, manager = asyncio.run(scenario())

    assert started["step"] == "qr_pending"
    assert started["login_id"] == "login-1"
    assert started["qr_url"] == "tg://login?token=token-1"
    assert started["qr_image"].startswith("data:image/png;base64,")
    assert accounts.marked == [("default", True)]
    assert client.disconnected is True
    # The flow must survive as a terminal authorized snapshot so the next poll
    # observes success instead of racing the discard and getting a 404.
    status_after = asyncio.run(manager.status(started["login_id"]))
    assert status_after["step"] == "authorized"
    assert status_after["account"]["status"] == "enabled_authorized"


def test_qr_recreates_token_on_timeout_and_refreshes_snapshot():
    async def scenario():
        accounts = FakeAccounts()
        client = FakeQrClient(script=["timeout", "hang"])
        manager = _manager(accounts, FakeClientFactory([client]))

        started = await manager.start_qr("default")
        login_id = started["login_id"]
        await _wait_until(
            lambda: client.qr is not None
            and client.qr.recreate_count >= 1
            and client.qr.wait_calls >= 2
        )
        status = await manager.status(login_id)
        await manager.cancel(login_id)
        return started, status, client

    started, status, client = asyncio.run(scenario())

    assert started["qr_url"] == "tg://login?token=token-1"
    assert client.qr.recreate_count >= 1
    assert status["step"] == "qr_pending"
    assert status["qr_url"] == "tg://login?token=token-2"
    assert status["qr_image"].startswith("data:image/png;base64,")


def test_qr_password_required_then_password_success():
    async def scenario():
        accounts = FakeAccounts()
        client = FakeQrClient(script=["password"])
        manager = _manager(accounts, FakeClientFactory([client]))

        started = await manager.start_qr("default")
        login_id = started["login_id"]
        await manager._flows[login_id].task
        status = await manager.status(login_id)
        result = await manager.submit_password(login_id, VALID_PASSWORD)
        return status, result, accounts, client

    status, result, accounts, client = asyncio.run(scenario())

    assert status["step"] == "password_required"
    assert result["step"] == "authorized"
    assert accounts.marked == [("default", True)]
    assert client.disconnected is True


def test_qr_cancel_stops_background_task_and_disconnects():
    async def scenario():
        accounts = FakeAccounts()
        client = FakeQrClient(script=["hang"])
        manager = _manager(accounts, FakeClientFactory([client]))

        started = await manager.start_qr("default")
        login_id = started["login_id"]
        task = manager._flows[login_id].task
        await _wait_until(lambda: client.qr is not None and client.qr.wait_calls >= 1)
        result = await manager.cancel(login_id)
        await _wait_until(lambda: task.done())
        return result, task, client, manager, login_id

    result, task, client, manager, login_id = asyncio.run(scenario())

    assert result == {"ok": True}
    assert task.done()
    assert client.disconnected is True
    assert login_id not in manager._flows


def test_public_snapshots_do_not_leak_raw_phone_api_hash_session_or_login_secrets():
    accounts = FakeAccounts()
    client = FakeTelegramClient(password_required=True)
    manager = _manager(accounts, FakeClientFactory([client]))

    started = asyncio.run(manager.start("default"))
    status = asyncio.run(manager.status(started["login_id"]))
    password_required = asyncio.run(manager.submit_code(started["login_id"], VALID_CODE))
    authorized = asyncio.run(
        manager.submit_password(started["login_id"], VALID_PASSWORD)
    )
    public_payload = json.dumps(
        [started, status, password_required, authorized],
        ensure_ascii=False,
        sort_keys=True,
    )

    forbidden = [
        RAW_PHONE,
        API_HASH,
        SESSION_PATH,
        PHONE_CODE_HASH,
        SESSION_CONTENTS,
        VALID_CODE,
        VALID_PASSWORD,
    ]
    for secret in forbidden:
        assert secret not in public_payload
