"""Factory for Telegram clients bound to account profiles."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from backend import config
from backend.accounts import _load_private_profile
from backend.quizbot_client import QuizBotClient


def create_client(
    profile_id: str | None = None,
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> QuizBotClient:
    profile = _load_private_profile(
        profile_id,
        store_root=store_root,
        config_module=config_module,
    )
    session_path = Path(profile.session_path).expanduser()
    if session_path.parent != Path("."):
        session_path.parent.mkdir(parents=True, exist_ok=True)
    return QuizBotClient(
        session_name=str(session_path),
        api_id=profile.api_id,
        api_hash=profile.api_hash,
        phone=profile.phone,
    )


def create_client_for_profile(
    profile_id: str,
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
) -> QuizBotClient:
    return create_client(
        profile_id,
        store_root=store_root,
        config_module=config_module,
    )
