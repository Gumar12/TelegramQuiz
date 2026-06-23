"""Factory for Telegram clients bound to account profiles."""
from __future__ import annotations

import asyncio
import errno
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from backend import config
from backend.accounts import (
    _chmod_private_file,
    _chmod_session_files,
    _ensure_private_dir,
    _load_private_profile,
)
from backend.quizbot_client import QuizBotClient

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows-only fallback
    fcntl = None


def _session_lock_path(session_path: str | Path) -> Path:
    base = Path(session_path).expanduser()
    if not base.name:
        return base
    return base.with_name(f".{base.name}.lock")


async def _acquire_posix_lock(file_obj) -> None:
    if fcntl is None:
        return
    while True:
        try:
            fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                await asyncio.sleep(0.05)
                continue
            raise


async def _release_posix_lock(file_obj) -> None:
    if fcntl is None:
        return
    fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)


async def _acquire_windows_lock(file_obj) -> None:
    if os.name != "nt":
        return
    import msvcrt

    while True:
        try:
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, 33):
                await asyncio.sleep(0.05)
                continue
            raise


async def _release_windows_lock(file_obj) -> None:
    if os.name != "nt":
        return
    import msvcrt

    msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)


@asynccontextmanager
async def session_file_lock(session_path: str | Path):
    lock_path = _session_lock_path(session_path)
    if not lock_path.name:
        yield
        return

    if lock_path.parent != Path("."):
        _ensure_private_dir(lock_path.parent)

    try:
        lock_handle = open(lock_path, "a+")
    except OSError:
        yield
        return

    try:
        try:
            _chmod_private_file(lock_path)
        except OSError:
            pass

        acquired = True
        try:
            if os.name == "nt":
                await _acquire_windows_lock(lock_handle)
            else:
                await _acquire_posix_lock(lock_handle)
        except OSError:
            acquired = False

        try:
            yield
        finally:
            try:
                if acquired:
                    if os.name == "nt":
                        await _release_windows_lock(lock_handle)
                    else:
                        await _release_posix_lock(lock_handle)
            finally:
                lock_handle.close()
    except OSError:
        lock_handle.close()
        raise


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
        _ensure_private_dir(session_path.parent)
    client = QuizBotClient(
        session_name=str(session_path),
        api_id=profile.api_id,
        api_hash=profile.api_hash,
        phone=profile.phone,
        session_chmod_callback=lambda: _chmod_session_files(session_path),
    )
    return client


def session_lock_for_profile(
    profile_id: str | None = None,
    *,
    store_root: str | Path | None = None,
    config_module: Any = config,
):
    profile = _load_private_profile(
        profile_id,
        store_root=store_root,
        config_module=config_module,
    )
    return session_file_lock(profile.session_path)


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
