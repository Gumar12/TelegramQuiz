import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import accounts, quizbot_client, telegram_client_factory
from backend.quizbot_client import QuizBotClient


POSIX_MODE_REASON = "POSIX permission bits are not reliable on Windows"


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        API_ID=12345,
        API_HASH="hash-secret-value",
        PHONE="+15551234567",
        SESSION_NAME=str(tmp_path / "runtime" / "quizbot_session"),
        RUNTIME_DIR=tmp_path / "runtime",
    )


def _profile(
    profile_id: str,
    *,
    enabled: bool,
    tmp_path: Path,
    api_hash: str | None = None,
    phone: str | None = None,
) -> dict:
    return {
        "id": profile_id,
        "display_name": profile_id.title(),
        "api_id": 1000 + len(profile_id),
        "api_hash": api_hash or f"{profile_id}-api-hash",
        "phone": phone or f"+1555000{len(profile_id):04d}",
        "telegram_session_path": str(tmp_path / "sessions" / f"{profile_id}.session"),
        "env_source": "env",
        "pacing_policy": "normal",
        "is_enabled": enabled,
        "is_authorized": False,
        "created_at": "2026-06-17T00:00:00+00:00",
        "updated_at": "2026-06-17T00:00:00+00:00",
    }


def _write_profiles(store_root: Path, profiles: list[dict]) -> None:
    store_root.mkdir(parents=True, exist_ok=True)
    (store_root / accounts.PROFILES_FILENAME).write_text(
        json.dumps({"profiles": profiles}, ensure_ascii=False),
        encoding="utf-8",
    )


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_empty_store_does_not_create_env_default_profile(tmp_path):
    store_root = tmp_path / "accounts"
    config = _config(tmp_path)

    profiles = accounts.list_profiles(store_root=store_root, config_module=config)

    assert (store_root / accounts.PROFILES_FILENAME).exists()
    assert not (store_root / accounts.ACTIVE_PROFILE_FILENAME).exists()
    assert profiles == []

    with pytest.raises(accounts.ProfileNotFoundError):
        accounts.current_profile(store_root=store_root, config_module=config)

    with pytest.raises(accounts.ProfileNotFoundError):
        accounts._load_private_profile(store_root=store_root, config_module=config)


def test_active_profile_switch_persists(tmp_path):
    store_root = tmp_path / "accounts"
    _write_profiles(
        store_root,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            _profile("study", enabled=True, tmp_path=tmp_path),
        ],
    )

    selected = accounts.use_profile("study", store_root=store_root)
    current = accounts.current_profile(store_root=store_root)
    active_payload = json.loads(
        (store_root / accounts.ACTIVE_PROFILE_FILENAME).read_text(encoding="utf-8")
    )

    assert selected.id == "study"
    assert current.id == "study"
    assert active_payload["active_profile_id"] == "study"


def test_create_profile_stores_secret_fields_and_returns_public_profile(tmp_path):
    store_root = tmp_path / "accounts"

    created = accounts.create_profile(
        display_name="Рабочий профиль",
        api_id=777,
        api_hash="secret-hash",
        phone="+77001234567",
        store_root=store_root,
    )
    payload = json.loads(
        (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )
    created_profile = next(profile for profile in payload["profiles"] if profile["id"] == "profile")
    public_text = json.dumps(created.to_dict(), ensure_ascii=False)

    assert created.display_name == "Рабочий профиль"
    assert created.status == "enabled"
    assert created.is_active is True
    assert (store_root / "sessions").exists()
    assert created_profile["api_id"] == 777
    assert created_profile["api_hash"] == "secret-hash"
    assert created_profile["phone"] == "+77001234567"
    assert created_profile["env_source"] == "ui"
    assert "secret-hash" not in public_text
    assert "+77001234567" not in public_text


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_create_profile_uses_private_posix_modes_for_account_store(tmp_path):
    store_root = tmp_path / "accounts"

    accounts.create_profile(
        display_name="Рабочий профиль",
        api_id=777,
        api_hash="secret-hash",
        phone="+77001234567",
        store_root=store_root,
    )

    assert _mode(store_root) == 0o700
    assert _mode(store_root / "sessions") == 0o700
    assert _mode(store_root / accounts.PROFILES_FILENAME) == 0o600
    assert _mode(store_root / accounts.ACTIVE_PROFILE_FILENAME) == 0o600


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_profile_and_active_writes_use_private_atomic_replace(tmp_path, monkeypatch):
    store_root = tmp_path / "accounts"
    replacements = []
    real_replace = accounts.os.replace

    def capture_replace(src, dst):
        replacements.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(accounts.os, "replace", capture_replace)

    accounts.create_profile(
        display_name="Рабочий профиль",
        api_id=777,
        api_hash="secret-hash",
        phone="+77001234567",
        store_root=store_root,
    )

    destinations = {dst for _, dst in replacements}
    assert store_root / accounts.PROFILES_FILENAME in destinations
    assert store_root / accounts.ACTIVE_PROFILE_FILENAME in destinations
    for src, dst in replacements:
        assert src.parent == dst.parent
        assert not src.exists()
        assert _mode(dst) == 0o600


def test_failed_profile_write_does_not_truncate_existing_store(tmp_path, monkeypatch):
    store_root = tmp_path / "accounts"
    profile = _profile("default", enabled=True, tmp_path=tmp_path)
    _write_profiles(store_root, [profile])
    before = (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")

    def fail_after_partial_write(data, fh, *args, **kwargs):
        fh.write("{broken")
        raise RuntimeError("simulated json failure")

    monkeypatch.setattr(accounts.json, "dump", fail_after_partial_write)

    with pytest.raises(RuntimeError, match="simulated json failure"):
        accounts.update_profile(
            "default",
            display_name="Новое имя",
            store_root=store_root,
        )

    assert (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8") == before


def test_update_profile_renames_profile_without_changing_id(tmp_path):
    store_root = tmp_path / "accounts"
    _write_profiles(store_root, [_profile("default", enabled=True, tmp_path=tmp_path)])

    updated = accounts.update_profile(
        "default",
        display_name="Основной профиль",
        store_root=store_root,
    )
    stored_profile = json.loads(
        (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )["profiles"][0]

    assert updated.id == "default"
    assert updated.display_name == "Основной профиль"
    assert stored_profile["id"] == "default"
    assert stored_profile["display_name"] == "Основной профиль"


def test_update_profile_credentials_resets_authorization_and_session(tmp_path):
    store_root = tmp_path / "accounts"
    session_path = tmp_path / "sessions" / "default.session"
    session_path.parent.mkdir(parents=True)
    session_path.write_text("session", encoding="utf-8")
    session_wal_path = session_path.with_name(f"{session_path.name}-wal")
    session_wal_path.write_text("wal", encoding="utf-8")
    profile = _profile("default", enabled=True, tmp_path=tmp_path)
    profile["telegram_session_path"] = str(session_path)
    profile["is_authorized"] = True
    _write_profiles(store_root, [profile])

    updated = accounts.update_profile(
        "default",
        api_hash="new-secret-hash",
        api_id=98765,
        phone="8 (700) 123-45-67",
        store_root=store_root,
    )
    stored_profile = json.loads(
        (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )["profiles"][0]
    private_profile = accounts._load_private_profile(
        "default",
        store_root=store_root,
    )
    public_text = json.dumps(updated.to_dict(), ensure_ascii=False)

    assert updated.status == "enabled"
    assert stored_profile["api_id"] == 98765
    assert stored_profile["api_hash"] == "new-secret-hash"
    assert stored_profile["phone"] == "+77001234567"
    assert stored_profile["is_authorized"] is False
    assert private_profile.api_id == 98765
    assert private_profile.api_hash == "new-secret-hash"
    assert private_profile.phone == "+77001234567"
    assert not session_path.exists()
    assert not session_wal_path.exists()
    assert "new-secret-hash" not in public_text
    assert "+77001234567" not in public_text


def test_create_profile_normalizes_phone(tmp_path):
    store_root = tmp_path / "accounts"

    accounts.create_profile(
        display_name="Рабочий профиль",
        api_id=777,
        api_hash="secret-hash",
        phone="7 700 123 45 67",
        store_root=store_root,
    )
    stored_profile = json.loads(
        (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )["profiles"][0]

    assert stored_profile["phone"] == "+77001234567"


def test_create_profile_rejects_invalid_phone(tmp_path):
    store_root = tmp_path / "accounts"

    with pytest.raises(accounts.AccountProfileError):
        accounts.create_profile(
            display_name="Рабочий профиль",
            api_id=777,
            api_hash="secret-hash",
            phone="not-a-phone",
            store_root=store_root,
        )


def test_delete_profile_removes_profile_session_and_reselects_active(tmp_path):
    store_root = tmp_path / "accounts"
    session_path = tmp_path / "sessions" / "study.session"
    session_path.parent.mkdir(parents=True)
    session_path.write_text("session", encoding="utf-8")
    (session_path.with_name(f"{session_path.name}-wal")).write_text(
        "wal",
        encoding="utf-8",
    )
    study = _profile("study", enabled=True, tmp_path=tmp_path)
    study["telegram_session_path"] = str(session_path)
    _write_profiles(
        store_root,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            study,
        ],
    )
    accounts.use_profile("study", store_root=store_root)

    active = accounts.delete_profile("study", store_root=store_root)
    stored = json.loads(
        (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )
    active_payload = json.loads(
        (store_root / accounts.ACTIVE_PROFILE_FILENAME).read_text(encoding="utf-8")
    )

    assert active is not None
    assert active.id == "default"
    assert [profile["id"] for profile in stored["profiles"]] == ["default"]
    assert active_payload["active_profile_id"] == "default"
    assert not session_path.exists()
    assert not session_path.with_name(f"{session_path.name}-wal").exists()


def test_delete_last_profile_clears_active_profile(tmp_path):
    store_root = tmp_path / "accounts"
    session_path = tmp_path / "sessions" / "default.session"
    session_path.parent.mkdir(parents=True)
    session_path.write_text("session", encoding="utf-8")
    session_wal_path = session_path.with_name(f"{session_path.name}-wal")
    session_wal_path.write_text("wal", encoding="utf-8")
    profile = _profile("default", enabled=True, tmp_path=tmp_path)
    profile["telegram_session_path"] = str(session_path)
    _write_profiles(store_root, [profile])
    accounts.use_profile("default", store_root=store_root)

    active = accounts.delete_profile("default", store_root=store_root)
    stored = json.loads(
        (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )

    assert active is None
    assert stored["profiles"] == []
    assert not (store_root / accounts.ACTIVE_PROFILE_FILENAME).exists()
    assert not session_path.exists()
    assert not session_wal_path.exists()
    assert accounts.list_profiles(store_root=store_root) == []
    with pytest.raises(accounts.ProfileNotFoundError):
        accounts.current_profile(store_root=store_root)


def test_disabling_active_profile_reselects_enabled_profile(tmp_path):
    store_root = tmp_path / "accounts"
    _write_profiles(
        store_root,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            _profile("study", enabled=True, tmp_path=tmp_path),
        ],
    )
    accounts.use_profile("study", store_root=store_root)

    disabled = accounts.disable_profile("study", store_root=store_root)
    current = accounts.current_profile(store_root=store_root)

    assert disabled.id == "study"
    assert disabled.is_active is False
    assert current.id == "default"


def test_more_than_two_enabled_profiles_is_rejected(tmp_path):
    store_root = tmp_path / "accounts"
    _write_profiles(
        store_root,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            _profile("study", enabled=True, tmp_path=tmp_path),
            _profile("work", enabled=False, tmp_path=tmp_path),
        ],
    )

    with pytest.raises(accounts.EnabledProfileLimitError):
        accounts.enable_profile("work", store_root=store_root)


def test_mark_profile_authorized_sets_status_and_preserves_other_fields(tmp_path):
    store_root = tmp_path / "accounts"
    profile = _profile("default", enabled=True, tmp_path=tmp_path)
    before = dict(profile)
    _write_profiles(store_root, [profile])

    updated = accounts.mark_profile_authorized("default", store_root=store_root)

    stored_profile = json.loads(
        (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )["profiles"][0]
    assert updated.id == "default"
    assert updated.status == "enabled_authorized"
    assert updated.is_active is True
    assert stored_profile["is_authorized"] is True
    assert stored_profile["updated_at"] != before["updated_at"]
    for key, value in before.items():
        if key not in {"is_authorized", "updated_at"}:
            assert stored_profile[key] == value


def test_mark_profile_authorized_false_clears_authorized_status(tmp_path):
    store_root = tmp_path / "accounts"
    profile = _profile("default", enabled=True, tmp_path=tmp_path)
    profile["is_authorized"] = True
    before = dict(profile)
    _write_profiles(store_root, [profile])

    updated = accounts.mark_profile_authorized(
        "default",
        authorized=False,
        store_root=store_root,
    )

    stored_profile = json.loads(
        (store_root / accounts.PROFILES_FILENAME).read_text(encoding="utf-8")
    )["profiles"][0]
    assert updated.status == "enabled"
    assert updated.is_active is True
    assert stored_profile["is_authorized"] is False
    assert stored_profile["updated_at"] != before["updated_at"]
    for key, value in before.items():
        if key not in {"is_authorized", "updated_at"}:
            assert stored_profile[key] == value


def test_mark_profile_authorized_unknown_profile_raises(tmp_path):
    store_root = tmp_path / "accounts"
    _write_profiles(store_root, [_profile("default", enabled=True, tmp_path=tmp_path)])

    with pytest.raises(accounts.ProfileNotFoundError):
        accounts.mark_profile_authorized("missing", store_root=store_root)


def test_mark_profile_authorized_returned_public_dto_does_not_leak_secrets(
    tmp_path,
):
    store_root = tmp_path / "accounts"
    raw_phone = "+77001234567"
    api_hash = "super-secret-api-hash"
    session_contents = "SESSION-FILE-CONTENTS-SHOULD-NOT-LEAK"
    session_path = tmp_path / "sessions" / "private.session"
    profile = _profile(
        "default",
        enabled=True,
        tmp_path=tmp_path,
        api_hash=api_hash,
        phone=raw_phone,
    )
    profile["telegram_session_path"] = str(session_path)
    profile["session_contents"] = session_contents
    _write_profiles(store_root, [profile])

    public_payload = json.dumps(
        accounts.mark_profile_authorized(
            "default",
            store_root=store_root,
        ).to_dict(),
        ensure_ascii=False,
    )

    assert api_hash not in public_payload
    assert raw_phone not in public_payload
    assert session_contents not in public_payload
    assert str(session_path) not in public_payload
    assert session_path.name in public_payload
    assert "+*******4567" in public_payload


def test_disabled_profile_cannot_be_selected_for_new_upload_or_probe(tmp_path):
    store_root = tmp_path / "accounts"
    _write_profiles(
        store_root,
        [
            _profile("default", enabled=True, tmp_path=tmp_path),
            _profile("study", enabled=False, tmp_path=tmp_path),
        ],
    )

    with pytest.raises(accounts.ProfileDisabledError):
        accounts.use_profile("study", store_root=store_root)

    with pytest.raises(accounts.ProfileDisabledError):
        telegram_client_factory.create_client("study", store_root=store_root)


def test_client_factory_creates_client_for_enabled_profile(tmp_path, monkeypatch):
    store_root = tmp_path / "accounts"
    profile = _profile("default", enabled=True, tmp_path=tmp_path)
    _write_profiles(store_root, [profile])
    captured = {}

    class FakeQuizBotClient:
        def __init__(self, *, session_name, api_id, api_hash, phone, session_chmod_callback):
            captured["session_name"] = session_name
            captured["api_id"] = api_id
            captured["api_hash"] = api_hash
            captured["phone"] = phone
            captured["session_chmod_callback"] = session_chmod_callback

    monkeypatch.setattr(telegram_client_factory, "QuizBotClient", FakeQuizBotClient)

    client = telegram_client_factory.create_client("default", store_root=store_root)

    assert isinstance(client, FakeQuizBotClient)
    assert captured == {
        "session_name": profile["telegram_session_path"],
        "api_id": profile["api_id"],
        "api_hash": profile["api_hash"],
        "phone": profile["phone"],
        "session_chmod_callback": captured["session_chmod_callback"],
    }
    assert callable(captured["session_chmod_callback"])


def test_client_factory_creates_missing_session_parent_directory(tmp_path, monkeypatch):
    store_root = tmp_path / "accounts"
    profile = _profile("default", enabled=True, tmp_path=tmp_path)
    session_path = tmp_path / "missing" / "nested" / "default.session"
    profile["telegram_session_path"] = str(session_path)
    _write_profiles(store_root, [profile])

    class FakeQuizBotClient:
        def __init__(self, *, session_name, api_id, api_hash, phone, session_chmod_callback):
            self.session_name = session_name

    monkeypatch.setattr(telegram_client_factory, "QuizBotClient", FakeQuizBotClient)

    client = telegram_client_factory.create_client("default", store_root=store_root)

    assert session_path.parent.exists()
    assert client.session_name == str(session_path)


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_client_factory_uses_private_posix_modes_for_session_files(tmp_path, monkeypatch):
    store_root = tmp_path / "accounts"
    profile = _profile("default", enabled=True, tmp_path=tmp_path)
    session_path = tmp_path / "sessions" / "default.session"
    session_path.parent.mkdir(parents=True)
    session_path.write_text("session", encoding="utf-8")
    session_path.chmod(0o644)
    sidecars = [
        session_path.with_name(f"{session_path.name}-wal"),
        session_path.with_name(f"{session_path.name}-shm"),
        session_path.with_name(f"{session_path.name}-journal"),
    ]
    for sidecar in sidecars:
        sidecar.write_text("sidecar", encoding="utf-8")
        sidecar.chmod(0o644)
    profile["telegram_session_path"] = str(session_path)
    _write_profiles(store_root, [profile])

    captured = {}

    class FakeQuizBotClient:
        def __init__(self, *, session_name, api_id, api_hash, phone, session_chmod_callback):
            self.session_name = session_name
            captured["session_chmod_callback"] = session_chmod_callback

    monkeypatch.setattr(telegram_client_factory, "QuizBotClient", FakeQuizBotClient)

    telegram_client_factory.create_client("default", store_root=store_root)

    assert _mode(session_path.parent) == 0o700
    assert _mode(session_path) == 0o644
    for sidecar in sidecars:
        assert _mode(sidecar) == 0o644

    captured["session_chmod_callback"]()

    assert _mode(session_path) == 0o600
    for sidecar in sidecars:
        assert _mode(sidecar) == 0o600


def test_public_profile_output_excludes_api_hash_raw_phone_and_session_contents(tmp_path):
    store_root = tmp_path / "accounts"
    raw_phone = "+77001234567"
    api_hash = "super-secret-api-hash"
    session_contents = "SESSION-FILE-CONTENTS-SHOULD-NOT-LEAK"
    session_path = tmp_path / "sessions" / "private.session"
    profile = _profile(
        "default",
        enabled=True,
        tmp_path=tmp_path,
        api_hash=api_hash,
        phone=raw_phone,
    )
    profile["telegram_session_path"] = str(session_path)
    profile["session_contents"] = session_contents
    _write_profiles(store_root, [profile])

    public_payload = json.dumps(
        [item.to_dict() for item in accounts.list_profiles(store_root=store_root)],
        ensure_ascii=False,
    )

    assert api_hash not in public_payload
    assert raw_phone not in public_payload
    assert session_contents not in public_payload
    assert str(session_path) not in public_payload
    assert session_path.name in public_payload


def test_existing_quizbot_client_default_behavior_remains_compatible(monkeypatch):
    captured = {}

    class FakeTelegramClient:
        def __init__(self, session_name, api_id, api_hash):
            captured["session_name"] = session_name
            captured["api_id"] = api_id
            captured["api_hash"] = api_hash

    monkeypatch.setattr(quizbot_client, "TelegramClient", FakeTelegramClient)
    monkeypatch.setattr(quizbot_client.config, "SESSION_NAME", "default-session")
    monkeypatch.setattr(quizbot_client.config, "API_ID", 42)
    monkeypatch.setattr(quizbot_client.config, "API_HASH", "default-hash")
    monkeypatch.setattr(quizbot_client.config, "PHONE", "+10000000000")

    client = QuizBotClient()

    assert captured == {
        "session_name": "default-session",
        "api_id": 42,
        "api_hash": "default-hash",
    }
    assert client.phone == "+10000000000"


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_quizbot_client_chmods_session_files_after_start_and_disconnect(tmp_path, monkeypatch):
    session_path = tmp_path / "sessions" / "probe.session"
    session_path.parent.mkdir(parents=True)
    chmod_calls = []

    class FakeConversation:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    class FakeTelegramClient:
        def __init__(self, session_name, api_id, api_hash):
            self.session_path = Path(session_name)

        async def start(self, phone=None):
            self.session_path.write_text("session", encoding="utf-8")
            self.session_path.chmod(0o644)
            wal_path = self.session_path.with_name(f"{self.session_path.name}-wal")
            wal_path.write_text("wal", encoding="utf-8")
            wal_path.chmod(0o644)

        def conversation(self, bot_username, *, timeout, exclusive):
            return FakeConversation()

        async def disconnect(self):
            shm_path = self.session_path.with_name(f"{self.session_path.name}-shm")
            shm_path.write_text("shm", encoding="utf-8")
            shm_path.chmod(0o644)

    def chmod_session_files():
        chmod_calls.append(session_path.exists())
        accounts._chmod_session_files(session_path)

    monkeypatch.setattr(quizbot_client, "TelegramClient", FakeTelegramClient)

    client = QuizBotClient(
        session_name=str(session_path),
        api_id=123,
        api_hash="hash",
        phone="+77001234567",
        session_chmod_callback=chmod_session_files,
    )

    async def run_client():
        async with client:
            assert _mode(session_path) == 0o600
            assert _mode(session_path.with_name(f"{session_path.name}-wal")) == 0o600

    asyncio.run(run_client())

    assert chmod_calls == [True, True]
    assert _mode(session_path.with_name(f"{session_path.name}-shm")) == 0o600


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_quizbot_client_chmods_and_disconnects_when_conversation_enter_fails(
    tmp_path,
    monkeypatch,
):
    session_path = tmp_path / "sessions" / "enter-fail.session"
    session_path.parent.mkdir(parents=True)

    class FakeConversation:
        async def __aenter__(self):
            raise RuntimeError("conversation enter failed")

    class FakeTelegramClient:
        def __init__(self, session_name, api_id, api_hash):
            self.session_path = Path(session_name)
            self.disconnected = False

        async def start(self, phone=None):
            self.session_path.write_text("session", encoding="utf-8")
            self.session_path.chmod(0o644)
            wal_path = self.session_path.with_name(f"{self.session_path.name}-wal")
            wal_path.write_text("wal", encoding="utf-8")
            wal_path.chmod(0o644)

        def conversation(self, bot_username, *, timeout, exclusive):
            return FakeConversation()

        async def disconnect(self):
            self.disconnected = True
            shm_path = self.session_path.with_name(f"{self.session_path.name}-shm")
            shm_path.write_text("shm", encoding="utf-8")
            shm_path.chmod(0o644)

    def chmod_session_files():
        accounts._chmod_session_files(session_path)

    monkeypatch.setattr(quizbot_client, "TelegramClient", FakeTelegramClient)

    client = QuizBotClient(
        session_name=str(session_path),
        api_id=123,
        api_hash="hash",
        phone="+77001234567",
        session_chmod_callback=chmod_session_files,
    )

    with pytest.raises(RuntimeError, match="conversation enter failed"):
        asyncio.run(client.__aenter__())

    assert client.client.disconnected is True
    assert _mode(session_path) == 0o600
    assert _mode(session_path.with_name(f"{session_path.name}-wal")) == 0o600
    assert _mode(session_path.with_name(f"{session_path.name}-shm")) == 0o600


@pytest.mark.skipif(os.name != "posix", reason=POSIX_MODE_REASON)
def test_quizbot_client_disconnects_and_chmods_when_conversation_exit_fails(
    tmp_path,
    monkeypatch,
):
    session_path = tmp_path / "sessions" / "exit-fail.session"
    session_path.parent.mkdir(parents=True)

    class FakeConversation:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            raise RuntimeError("conversation exit failed")

    class FakeTelegramClient:
        def __init__(self, session_name, api_id, api_hash):
            self.session_path = Path(session_name)
            self.disconnected = False

        async def start(self, phone=None):
            self.session_path.write_text("session", encoding="utf-8")
            self.session_path.chmod(0o644)
            wal_path = self.session_path.with_name(f"{self.session_path.name}-wal")
            wal_path.write_text("wal", encoding="utf-8")
            wal_path.chmod(0o644)

        def conversation(self, bot_username, *, timeout, exclusive):
            return FakeConversation()

        async def disconnect(self):
            self.disconnected = True
            shm_path = self.session_path.with_name(f"{self.session_path.name}-shm")
            shm_path.write_text("shm", encoding="utf-8")
            shm_path.chmod(0o644)

    def chmod_session_files():
        accounts._chmod_session_files(session_path)

    monkeypatch.setattr(quizbot_client, "TelegramClient", FakeTelegramClient)

    client = QuizBotClient(
        session_name=str(session_path),
        api_id=123,
        api_hash="hash",
        phone="+77001234567",
        session_chmod_callback=chmod_session_files,
    )

    async def run_client():
        with pytest.raises(RuntimeError, match="conversation exit failed"):
            async with client:
                pass

    asyncio.run(run_client())

    assert client.client.disconnected is True
    assert _mode(session_path) == 0o600
    assert _mode(session_path.with_name(f"{session_path.name}-wal")) == 0o600
    assert _mode(session_path.with_name(f"{session_path.name}-shm")) == 0o600
