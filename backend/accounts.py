"""Local Telegram account profile store.

The public API deliberately returns only display/status metadata. Telegram API
secrets, raw phone values, and session contents are available only through the
private loader used by the client factory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from backend import config

MAX_ENABLED_PROFILES = 2
PROFILES_FILENAME = "profiles.json"
ACTIVE_PROFILE_FILENAME = "active_profile.json"
DEFAULT_PROFILE_ID = "default"


class AccountProfileError(ValueError):
    """Base account profile service error."""


class ProfileNotFoundError(AccountProfileError):
    """Raised when a requested account profile does not exist."""


class ProfileDisabledError(AccountProfileError):
    """Raised when a disabled profile is selected for a new run."""


class EnabledProfileLimitError(AccountProfileError):
    """Raised when enabling a profile would exceed the enabled profile cap."""


class ProfileDeletionForbiddenError(AccountProfileError):
    """Raised when a protected account profile cannot be deleted."""


@dataclass(frozen=True)
class AccountProfilePublic:
    id: str
    display_name: str
    status: str
    session_path_basename: str
    telegram_phone_masked: str
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccountProfilePrivate:
    id: str
    display_name: str
    api_id: int
    api_hash: str
    phone: str
    session_path: str
    env_source: str
    pacing_policy: str
    is_enabled: bool
    is_authorized: bool


def list_profiles(
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> list[AccountProfilePublic]:
    data = _load_store(store_root=store_root, config_module=config_module)
    try:
        active_profile_id = _read_active_profile_id(
            store_root=store_root,
            config_module=config_module,
            data=data,
            allow_disabled=True,
        )
    except ProfileNotFoundError:
        active_profile_id = ""
    return [
        _to_public(profile, active_profile_id=active_profile_id)
        for profile in data["profiles"]
    ]


def current_profile(
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    data = _load_store(store_root=store_root, config_module=config_module)
    active_profile_id = _read_active_profile_id(
        store_root=store_root,
        config_module=config_module,
        data=data,
    )
    profile = _find_profile(data, active_profile_id)
    if not profile.get("is_enabled", False):
        raise ProfileDisabledError(
            f"Account profile {active_profile_id!r} is disabled"
        )
    return _to_public(profile, active_profile_id=active_profile_id)


def use_profile(
    profile_id: str,
    *,
    changed_by: str = "cli",
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    data = _load_store(store_root=store_root, config_module=config_module)
    profile = _find_profile(data, profile_id)
    if not profile.get("is_enabled", False):
        raise ProfileDisabledError(f"Account profile {profile_id!r} is disabled")
    _write_active_profile_id(
        profile_id,
        changed_by=changed_by,
        store_root=store_root,
        config_module=config_module,
    )
    return _to_public(profile, active_profile_id=profile_id)


def create_profile(
    *,
    display_name: str,
    api_id: int,
    api_hash: str,
    phone: str,
    enabled: bool = True,
    changed_by: str = "cli",
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    data = _load_store(store_root=store_root, config_module=config_module)
    name = _clean_display_name(display_name)
    profile_id = _unique_profile_id(data, name)
    enabled_value = bool(enabled) and _enabled_count(data["profiles"]) < MAX_ENABLED_PROFILES
    now = _utc_now()
    session_path = _account_store_root(store_root, config_module=config_module) / "sessions" / f"{profile_id}.session"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    profile = _normalize_profile(
        {
            "id": profile_id,
            "display_name": name,
            "api_id": _normalize_api_id(api_id),
            "api_hash": _clean_api_hash(api_hash),
            "phone": _normalize_phone(phone),
            "telegram_session_path": str(session_path),
            "env_source": "ui",
            "pacing_policy": "normal",
            "is_enabled": enabled_value,
            "is_authorized": False,
            "created_at": now,
            "updated_at": now,
        }
    )
    data["profiles"].append(profile)
    _write_store(data, store_root=store_root, config_module=config_module)
    if enabled_value:
        _write_active_profile_id(
            profile_id,
            changed_by=changed_by,
            store_root=store_root,
            config_module=config_module,
        )
        active_profile_id = profile_id
    else:
        try:
            active_profile_id = _read_active_profile_id(
                store_root=store_root,
                config_module=config_module,
                data=data,
                allow_disabled=True,
            )
        except ProfileNotFoundError:
            active_profile_id = ""
    return _to_public(profile, active_profile_id=active_profile_id)


def update_profile(
    profile_id: str,
    *,
    api_hash: str | None = None,
    api_id: int | None = None,
    display_name: str | None = None,
    phone: str | None = None,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    data = _load_store(store_root=store_root, config_module=config_module)
    profile = _find_profile(data, profile_id)
    if display_name is not None:
        profile["display_name"] = _clean_display_name(display_name)

    credentials_changed = False
    if api_id is not None:
        next_api_id = _normalize_api_id(api_id)
        if int(profile.get("api_id") or 0) != next_api_id:
            profile["api_id"] = next_api_id
            credentials_changed = True
    if api_hash is not None:
        next_api_hash = _clean_api_hash(api_hash)
        if str(profile.get("api_hash") or "") != next_api_hash:
            profile["api_hash"] = next_api_hash
            credentials_changed = True
    if phone is not None:
        next_phone = _normalize_phone(phone)
        if str(profile.get("phone") or "") != next_phone:
            profile["phone"] = next_phone
            credentials_changed = True

    if credentials_changed:
        profile["is_authorized"] = False
        _delete_session_files(Path(_profile_session_path(profile)).expanduser())

    profile["updated_at"] = _utc_now()
    _write_store(data, store_root=store_root, config_module=config_module)
    active_profile_id = _read_active_profile_id(
        store_root=store_root,
        config_module=config_module,
        data=data,
        allow_disabled=True,
    )
    return _to_public(profile, active_profile_id=active_profile_id)


def delete_profile(
    profile_id: str,
    *,
    changed_by: str = "cli",
    delete_session: bool = True,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic | None:
    data = _load_store(store_root=store_root, config_module=config_module)
    profile = _find_profile(data, profile_id)
    session_path = Path(_profile_session_path(profile)).expanduser()
    data["profiles"] = [
        item for item in data["profiles"] if str(item["id"]) != profile_id
    ]
    _write_store(data, store_root=store_root, config_module=config_module)
    if delete_session:
        _delete_session_files(session_path)

    if not data["profiles"]:
        _clear_active_profile_id(store_root=store_root, config_module=config_module)
        return None

    try:
        active_profile_id = _choose_active_profile_id(data, allow_disabled=False)
    except ProfileDisabledError:
        active_profile_id = _choose_active_profile_id(data, allow_disabled=True)
    _write_active_profile_id(
        active_profile_id,
        changed_by=changed_by,
        store_root=store_root,
        config_module=config_module,
    )
    active_profile = _find_profile(data, active_profile_id)
    return _to_public(active_profile, active_profile_id=active_profile_id)


def enable_profile(
    profile_id: str,
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    data = _load_store(store_root=store_root, config_module=config_module)
    profile = _find_profile(data, profile_id)
    if not profile.get("is_enabled", False):
        enabled_profiles = [
            item for item in data["profiles"] if item.get("is_enabled", False)
        ]
        if len(enabled_profiles) >= MAX_ENABLED_PROFILES:
            raise EnabledProfileLimitError(
                f"At most {MAX_ENABLED_PROFILES} account profiles can be enabled"
            )
        profile["is_enabled"] = True
        profile["updated_at"] = _utc_now()
        _write_store(data, store_root=store_root, config_module=config_module)
    active_profile_id = _read_active_profile_id(
        store_root=store_root,
        config_module=config_module,
        data=data,
    )
    return _to_public(profile, active_profile_id=active_profile_id)


def disable_profile(
    profile_id: str,
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    data = _load_store(store_root=store_root, config_module=config_module)
    profile = _find_profile(data, profile_id)
    if profile.get("is_enabled", False):
        profile["is_enabled"] = False
        profile["updated_at"] = _utc_now()
        _write_store(data, store_root=store_root, config_module=config_module)
    active_profile_id = _read_active_profile_id(
        store_root=store_root,
        config_module=config_module,
        data=data,
        allow_disabled=True,
    )
    if active_profile_id == profile_id and not profile.get("is_enabled", False):
        try:
            active_profile_id = _choose_active_profile_id(data, allow_disabled=False)
        except ProfileDisabledError:
            active_profile_id = _choose_active_profile_id(data, allow_disabled=True)
        _write_active_profile_id(
            active_profile_id,
            changed_by="system",
            store_root=store_root,
            config_module=config_module,
        )
    return _to_public(profile, active_profile_id=active_profile_id)


def set_profile_enabled(
    profile_id: str,
    enabled: bool,
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    if enabled:
        return enable_profile(
            profile_id,
            store_root=store_root,
            config_module=config_module,
        )
    return disable_profile(
        profile_id,
        store_root=store_root,
        config_module=config_module,
    )


def mark_profile_authorized(
    profile_id: str,
    authorized: bool = True,
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    authorized_value = bool(authorized)
    data = _load_store(store_root=store_root, config_module=config_module)
    profile = _find_profile(data, profile_id)
    if bool(profile.get("is_authorized", False)) != authorized_value:
        profile["is_authorized"] = authorized_value
        profile["updated_at"] = _utc_now()
        _write_store(data, store_root=store_root, config_module=config_module)
    active_profile_id = _read_active_profile_id(
        store_root=store_root,
        config_module=config_module,
        data=data,
        allow_disabled=True,
    )
    return _to_public(profile, active_profile_id=active_profile_id)


def get_active_profile(
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    return current_profile(store_root=store_root, config_module=config_module)


def set_active_profile(
    profile_id: str,
    *,
    changed_by: str = "cli",
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePublic:
    return use_profile(
        profile_id,
        changed_by=changed_by,
        store_root=store_root,
        config_module=config_module,
    )


def _load_private_profile(
    profile_id: str | None = None,
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> AccountProfilePrivate:
    data = _load_store(store_root=store_root, config_module=config_module)
    resolved_profile_id = profile_id or _read_active_profile_id(
        store_root=store_root,
        config_module=config_module,
        data=data,
    )
    profile = _find_profile(data, resolved_profile_id)
    if not profile.get("is_enabled", False):
        raise ProfileDisabledError(
            f"Account profile {resolved_profile_id!r} is disabled"
        )
    return AccountProfilePrivate(
        id=str(profile["id"]),
        display_name=str(profile.get("display_name") or profile["id"]),
        api_id=int(profile.get("api_id") or 0),
        api_hash=str(profile.get("api_hash") or ""),
        phone=str(profile.get("phone") or ""),
        session_path=str(_profile_session_path(profile)),
        env_source=str(profile.get("env_source") or "env"),
        pacing_policy=str(profile.get("pacing_policy") or "normal"),
        is_enabled=bool(profile.get("is_enabled", False)),
        is_authorized=bool(profile.get("is_authorized", False)),
    )


def _load_store(
    *,
    store_root: str | Path | None,
    config_module: Any,
) -> dict[str, list[dict[str, Any]]]:
    profiles_path = _profiles_path(store_root, config_module=config_module)
    if profiles_path.exists():
        with profiles_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    else:
        raw = {}

    profiles = raw.get("profiles", [])
    if not isinstance(profiles, list):
        raise AccountProfileError("profiles.json must contain a profiles list")

    normalized = [_normalize_profile(profile) for profile in profiles]
    changed = normalized != profiles

    _validate_enabled_limit(normalized)
    data = {"profiles": normalized}
    if changed or not profiles_path.exists():
        _write_store(data, store_root=store_root, config_module=config_module)

    _ensure_active_profile_file(
        data,
        store_root=store_root,
        config_module=config_module,
    )
    return data


def _write_store(
    data: dict[str, list[dict[str, Any]]],
    *,
    store_root: str | Path | None,
    config_module: Any,
) -> None:
    root = _account_store_root(store_root, config_module=config_module)
    root.mkdir(parents=True, exist_ok=True)
    with _profiles_path(store_root, config_module=config_module).open(
        "w",
        encoding="utf-8",
    ) as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _read_active_profile_id(
    *,
    store_root: str | Path | None,
    config_module: Any,
    data: dict[str, list[dict[str, Any]]] | None = None,
    allow_disabled: bool = False,
) -> str:
    data = data or _load_store(store_root=store_root, config_module=config_module)
    if not data["profiles"]:
        _clear_active_profile_id(store_root=store_root, config_module=config_module)
        raise ProfileNotFoundError("No account profiles are configured")

    active_path = _active_profile_path(store_root, config_module=config_module)
    if active_path.exists():
        with active_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        profile_id = str(raw.get("active_profile_id") or "")
        if profile_id and _profile_is_selectable(
            data,
            profile_id,
            allow_disabled=allow_disabled,
        ):
            return profile_id
    profile_id = _choose_active_profile_id(data, allow_disabled=allow_disabled)
    _write_active_profile_id(
        profile_id,
        changed_by="system",
        store_root=store_root,
        config_module=config_module,
    )
    return profile_id


def _write_active_profile_id(
    profile_id: str,
    *,
    changed_by: str,
    store_root: str | Path | None,
    config_module: Any,
) -> None:
    root = _account_store_root(store_root, config_module=config_module)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_profile_id": profile_id,
        "changed_at": _utc_now(),
        "changed_by": changed_by,
    }
    with _active_profile_path(store_root, config_module=config_module).open(
        "w",
        encoding="utf-8",
    ) as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _clear_active_profile_id(
    *,
    store_root: str | Path | None,
    config_module: Any,
) -> None:
    active_path = _active_profile_path(store_root, config_module=config_module)
    try:
        if active_path.exists():
            active_path.unlink()
    except OSError:
        pass


def _ensure_active_profile_file(
    data: dict[str, list[dict[str, Any]]],
    *,
    store_root: str | Path | None,
    config_module: Any,
) -> None:
    active_path = _active_profile_path(store_root, config_module=config_module)
    if not data["profiles"]:
        _clear_active_profile_id(store_root=store_root, config_module=config_module)
        return
    if active_path.exists():
        try:
            with active_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            profile_id = str(raw.get("active_profile_id") or "")
        except (OSError, json.JSONDecodeError):
            profile_id = ""
        if profile_id and _profile_is_selectable(
            data,
            profile_id,
            allow_disabled=True,
        ):
            return
    try:
        profile_id = _choose_active_profile_id(data, allow_disabled=False)
    except ProfileDisabledError:
        profile_id = _choose_active_profile_id(data, allow_disabled=True)
    _write_active_profile_id(
        profile_id,
        changed_by="system",
        store_root=store_root,
        config_module=config_module,
    )


def _choose_active_profile_id(
    data: dict[str, list[dict[str, Any]]],
    *,
    allow_disabled: bool,
) -> str:
    profiles = data["profiles"]
    if not profiles:
        raise ProfileNotFoundError("No account profiles are configured")
    for profile in profiles:
        if allow_disabled or profile.get("is_enabled", False):
            return str(profile["id"])
    raise ProfileDisabledError("No enabled account profiles are available")


def _find_profile(
    data: dict[str, list[dict[str, Any]]],
    profile_id: str,
) -> dict[str, Any]:
    for profile in data["profiles"]:
        if profile["id"] == profile_id:
            return profile
    raise ProfileNotFoundError(f"Account profile {profile_id!r} was not found")


def _profile_is_selectable(
    data: dict[str, list[dict[str, Any]]],
    profile_id: str,
    *,
    allow_disabled: bool,
) -> bool:
    try:
        profile = _find_profile(data, profile_id)
    except ProfileNotFoundError:
        return False
    return allow_disabled or bool(profile.get("is_enabled", False))


def _delete_session_files(session_path: Path) -> None:
    if not str(session_path):
        return
    base_paths = [session_path]
    if session_path.suffix != ".session":
        base_paths.append(Path(f"{session_path}.session"))
    candidates = []
    for base_path in base_paths:
        candidates.extend(
            [
                base_path,
                base_path.with_name(f"{base_path.name}-journal"),
                base_path.with_name(f"{base_path.name}-shm"),
                base_path.with_name(f"{base_path.name}-wal"),
            ]
        )
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
        except OSError:
            pass


def _clean_display_name(display_name: str) -> str:
    name = str(display_name or "").strip()
    if not name:
        raise AccountProfileError("Account profile display_name is required")
    return name


def _clean_api_hash(api_hash: str) -> str:
    value = str(api_hash or "").strip()
    if not value:
        raise AccountProfileError("Telegram API Hash is required")
    return value


def _normalize_api_id(api_id: int) -> int:
    try:
        value = int(api_id)
    except (TypeError, ValueError) as exc:
        raise AccountProfileError("Telegram API ID must be a positive integer") from exc
    if value <= 0:
        raise AccountProfileError("Telegram API ID must be a positive integer")
    return value


def _normalize_phone(phone: str) -> str:
    raw = str(phone or "").strip()
    compact = re.sub(r"[\s().-]+", "", raw)
    if compact.startswith("00"):
        compact = f"+{compact[2:]}"
    if re.fullmatch(r"8\d{10}", compact):
        compact = f"+7{compact[1:]}"
    if compact and not compact.startswith("+"):
        compact = f"+{compact}"
    if not re.fullmatch(r"\+\d{10,15}", compact):
        raise AccountProfileError(
            "Telegram phone must be in international format, for example +77001234567"
        )
    return compact


def _profile_id_from_display_name(display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
    return slug or "profile"


def _unique_profile_id(data: dict[str, list[dict[str, Any]]], display_name: str) -> str:
    base = _profile_id_from_display_name(display_name)
    used = {str(profile["id"]) for profile in data["profiles"]}
    if base not in used:
        return base
    index = 2
    while f"{base}-{index}" in used:
        index += 1
    return f"{base}-{index}"


def _to_public(
    profile: dict[str, Any],
    *,
    active_profile_id: str,
) -> AccountProfilePublic:
    enabled = bool(profile.get("is_enabled", False))
    authorized = bool(profile.get("is_authorized", False))
    if not enabled:
        status = "disabled"
    elif authorized:
        status = "enabled_authorized"
    else:
        status = "enabled"
    return AccountProfilePublic(
        id=str(profile["id"]),
        display_name=str(profile.get("display_name") or profile["id"]),
        status=status,
        session_path_basename=Path(_profile_session_path(profile)).name,
        telegram_phone_masked=_mask_phone(str(profile.get("phone") or "")),
        is_active=profile["id"] == active_profile_id,
    )


def _normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise AccountProfileError("Each account profile must be an object")
    if not profile.get("id"):
        raise AccountProfileError("Each account profile must have an id")

    now = _utc_now()
    normalized = dict(profile)
    normalized["id"] = str(normalized["id"])
    normalized["display_name"] = str(
        normalized.get("display_name") or normalized["id"]
    )
    normalized["api_id"] = int(normalized.get("api_id") or 0)
    normalized["api_hash"] = str(normalized.get("api_hash") or "")
    normalized["phone"] = str(normalized.get("phone") or "")
    normalized["telegram_session_path"] = str(_profile_session_path(normalized))
    normalized["env_source"] = str(normalized.get("env_source") or "env")
    normalized["pacing_policy"] = str(normalized.get("pacing_policy") or "normal")
    normalized["is_enabled"] = bool(normalized.get("is_enabled", False))
    normalized["is_authorized"] = bool(normalized.get("is_authorized", False))
    normalized["created_at"] = str(normalized.get("created_at") or now)
    normalized["updated_at"] = str(normalized.get("updated_at") or now)
    return normalized


def _profile_session_path(profile: dict[str, Any]) -> str:
    return str(
        profile.get("telegram_session_path")
        or profile.get("session_path")
        or profile.get("session")
        or ""
    )


def _mask_phone(phone: str) -> str:
    if not phone:
        return ""
    prefix = "+" if phone.startswith("+") else ""
    digits = phone[1:] if prefix else phone
    if len(digits) <= 4:
        return prefix + "*" * len(digits)
    return prefix + "*" * (len(digits) - 4) + digits[-4:]


def _enabled_count(profiles: list[dict[str, Any]]) -> int:
    return sum(1 for profile in profiles if profile.get("is_enabled", False))


def _validate_enabled_limit(profiles: list[dict[str, Any]]) -> None:
    if _enabled_count(profiles) > MAX_ENABLED_PROFILES:
        raise EnabledProfileLimitError(
            f"At most {MAX_ENABLED_PROFILES} account profiles can be enabled"
        )


def _account_store_root(
    store_root: str | Path | None,
    *,
    config_module: Any,
) -> Path:
    if store_root is not None:
        return Path(store_root)
    return Path(getattr(config_module, "RUNTIME_DIR", config.RUNTIME_DIR)) / "accounts"


def _profiles_path(
    store_root: str | Path | None,
    *,
    config_module: Any,
) -> Path:
    return (
        _account_store_root(store_root, config_module=config_module)
        / PROFILES_FILENAME
    )


def _active_profile_path(
    store_root: str | Path | None,
    *,
    config_module: Any,
) -> Path:
    return (
        _account_store_root(store_root, config_module=config_module)
        / ACTIVE_PROFILE_FILENAME
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


current = current_profile
use = use_profile
create = create_profile
update = update_profile
delete = delete_profile
enable = enable_profile
disable = disable_profile
