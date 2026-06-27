"""Memory-only Telegram authorization flow for account profiles."""
from __future__ import annotations

import asyncio
import base64
import inspect
import io
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from backend import accounts, config, telegram_client_factory

try:
    import qrcode
except ImportError:  # pragma: no cover - QR login degrades gracefully without dep
    qrcode = None

# App-коды Telegram нередко приходят с задержкой; даём пользователю запас,
# чтобы flow не «истёк» пока он ищет код в служебном чате.
LOGIN_TTL_SECONDS = 900
log = logging.getLogger(__name__)


def _qr_png_data_url(url: str) -> str:
    """Render a tg://login QR URL as a base64 PNG data URL.

    The URL is a session-grade secret (scanning it authorizes the account), so
    callers must never log the returned value — only serve it to the local UI.
    """
    if qrcode is None:
        raise TelegramLoginError(
            "QR login is unavailable: install qrcode[pil]"
        )
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class TelegramLoginError(ValueError):
    """Base Telegram login service error."""


class UnknownLoginError(TelegramLoginError):
    """Raised when a login id is not known by this process."""


class LoginExpiredError(TelegramLoginError):
    """Raised when a temporary login flow has expired."""


class LoginCredentialsMissingError(TelegramLoginError):
    """Raised when an account profile lacks Telegram credentials."""


class LoginStepError(TelegramLoginError):
    """Raised when a code/password is submitted for the wrong step."""


class AccountAuthorizationUpdateMissingError(TelegramLoginError):
    """Raised when the account service cannot mark authorization status."""


class TelegramLoginAuthError(TelegramLoginError):
    """Raised for Telegram authentication failures."""


class InvalidTelegramCodeError(TelegramLoginAuthError):
    """Raised when Telegram rejects the submitted login code."""


class InvalidTelegramPasswordError(TelegramLoginAuthError):
    """Raised when Telegram rejects the submitted 2FA password."""


@dataclass(slots=True)
class TelegramLoginFlow:
    login_id: str
    profile_id: str
    phone: str
    phone_masked: str
    session_path: str
    phone_code_hash: str
    step: str
    expires_at: datetime
    client: Any
    qr: Any = None
    qr_url: str | None = None
    qr_image: str | None = None
    task: Any = None
    error: str | None = None
    account: Any = None


class TelegramLoginManager:
    """Coordinates temporary Telegram login flows.

    The manager intentionally keeps `phone_code_hash` and the active Telegram
    client in process memory only. Successful terminal paths update the account
    profile through the injected account module.
    """

    def __init__(
        self,
        *,
        account_module: Any = accounts,
        config_module: Any = config,
        store_root: str | Path | None = None,
        client_factory: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: int = LOGIN_TTL_SECONDS,
        token_factory: Callable[[], str] | None = None,
    ):
        self.account_module = account_module
        self.config_module = config_module
        self.store_root = Path(store_root) if store_root is not None else None
        self.client_factory = (
            client_factory or telegram_client_factory.create_client_for_profile
        )
        self.clock = clock or _utc_now
        self.ttl_seconds = ttl_seconds
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._flows: dict[str, TelegramLoginFlow] = {}
        self._profile_locks: dict[str, asyncio.Lock] = {}
        self._profile_logins: dict[str, str] = {}

    async def start(self, profile_id: str, *, force_sms: bool = False) -> dict[str, Any]:
        """Start or replace a Telegram login flow for an existing profile."""

        lock = self._profile_locks.setdefault(profile_id, asyncio.Lock())
        async with lock:
            return await self._start_locked(profile_id, force_sms=force_sms)

    async def _start_locked(self, profile_id: str, *, force_sms: bool) -> dict[str, Any]:
        await self.cleanup_expired()
        await self._cancel_profile_flow(profile_id)

        profile = self._load_private_profile(profile_id)
        self._assert_credentials(profile)
        log.info(
            "telegram_login.start profile=%s phone=%s authorized=%s force_sms=%s",
            profile_id,
            _mask_phone(str(getattr(profile, "phone", "") or "")),
            bool(getattr(profile, "is_authorized", False)),
            force_sms,
        )
        if not bool(getattr(profile, "is_authorized", False)):
            _delete_session_files(Path(str(getattr(profile, "session_path", "") or "")))
        session_path = Path(str(getattr(profile, "session_path", "") or "")).expanduser()
        client = self._create_client(profile_id)

        async with telegram_client_factory.session_file_lock(session_path):
            try:
                await self._connect(client)
                accounts._chmod_session_files(session_path)
                log.info("telegram_login.connected profile=%s", profile_id)
                if await self._is_user_authorized(client):
                    account = self._mark_authorized(profile_id, authorized=True)
                    await self._disconnect(client)
                    accounts._chmod_session_files(session_path)
                    log.info("telegram_login.already_authorized profile=%s", profile_id)
                    return self._authorized_snapshot(account)

                log.info(
                    "telegram_login.send_code_request.start profile=%s phone=%s force_sms=%s",
                    profile_id,
                    _mask_phone(profile.phone),
                    force_sms,
                )
                sent_code = await self._send_code_request(
                    client,
                    profile.phone,
                    force_sms=force_sms,
                )
                log.info(
                    "telegram_login.send_code_request.ok profile=%s delivery=%s next=%s timeout=%s",
                    profile_id,
                    _sent_code_delivery_name(getattr(sent_code, "type", None)),
                    _sent_code_delivery_name(getattr(sent_code, "next_type", None)),
                    getattr(sent_code, "timeout", None),
                )
                login_id = self.token_factory()
                expires_at = self._now() + timedelta(seconds=self.ttl_seconds)
                flow = TelegramLoginFlow(
                    login_id=login_id,
                    profile_id=profile_id,
                    phone=profile.phone,
                    phone_masked=_mask_phone(profile.phone),
                    session_path=str(session_path),
                    phone_code_hash=str(getattr(sent_code, "phone_code_hash", "") or ""),
                    step="code_sent",
                    expires_at=expires_at,
                    client=client,
                )
                self._flows[login_id] = flow
                self._profile_logins[profile_id] = login_id
                return self._flow_snapshot(flow)
            except Exception as exc:
                if profile_id not in self._profile_logins:
                    try:
                        await self._disconnect(client)
                    finally:
                        accounts._chmod_session_files(session_path)
                safe_error = _safe_telegram_error(exc)
                log.warning(
                    "telegram_login.start.failed profile=%s error=%s",
                    profile_id,
                    safe_error,
                )
                raise TelegramLoginAuthError(safe_error) from exc

    async def start_qr(self, profile_id: str) -> dict[str, Any]:
        """Start or replace a QR-code Telegram login flow for an existing profile."""

        lock = self._profile_locks.setdefault(profile_id, asyncio.Lock())
        async with lock:
            return await self._start_qr_locked(profile_id)

    async def _start_qr_locked(self, profile_id: str) -> dict[str, Any]:
        await self.cleanup_expired()
        await self._cancel_profile_flow(profile_id)

        profile = self._load_private_profile(profile_id)
        self._assert_credentials(profile)
        log.info(
            "telegram_login.qr_start profile=%s authorized=%s",
            profile_id,
            bool(getattr(profile, "is_authorized", False)),
        )
        if not bool(getattr(profile, "is_authorized", False)):
            _delete_session_files(Path(str(getattr(profile, "session_path", "") or "")))
        session_path = Path(str(getattr(profile, "session_path", "") or "")).expanduser()
        client = self._create_client(profile_id)

        async with telegram_client_factory.session_file_lock(session_path):
            try:
                await self._connect(client)
                accounts._chmod_session_files(session_path)
                log.info("telegram_login.qr_connected profile=%s", profile_id)
                if await self._is_user_authorized(client):
                    account = self._mark_authorized(profile_id, authorized=True)
                    await self._disconnect(client)
                    accounts._chmod_session_files(session_path)
                    log.info("telegram_login.qr_already_authorized profile=%s", profile_id)
                    return self._authorized_snapshot(account)
                # is_user_authorized() is False here, so qr.url is safe to read
                # (guards against the LoginTokenSuccess AttributeError, Telethon #3922).
                qr = await self._qr_login(client)
                qr_url = qr.url
                qr_image = _qr_png_data_url(qr_url)
                accounts._chmod_session_files(session_path)
            except Exception as exc:
                try:
                    await self._disconnect(client)
                finally:
                    accounts._chmod_session_files(session_path)
                safe_error = _safe_telegram_error(exc)
                log.warning(
                    "telegram_login.qr_start.failed profile=%s error=%s",
                    profile_id,
                    safe_error,
                )
                raise TelegramLoginAuthError(safe_error) from exc

        login_id = self.token_factory()
        expires_at = self._now() + timedelta(seconds=self.ttl_seconds)
        flow = TelegramLoginFlow(
            login_id=login_id,
            profile_id=profile_id,
            phone=getattr(profile, "phone", "") or "",
            phone_masked=_mask_phone(getattr(profile, "phone", "") or ""),
            session_path=str(session_path),
            phone_code_hash="",
            step="qr_pending",
            expires_at=expires_at,
            client=client,
            qr=qr,
            qr_url=qr_url,
            qr_image=qr_image,
        )
        self._flows[login_id] = flow
        self._profile_logins[profile_id] = login_id
        flow.task = asyncio.create_task(self._run_qr_wait(flow))
        log.info("telegram_login.qr_pending profile=%s", profile_id)
        return self._qr_snapshot(flow)

    async def _run_qr_wait(self, flow: TelegramLoginFlow) -> None:
        """Background worker: wait for the QR scan, refreshing the token as it expires."""

        session_path = Path(flow.session_path).expanduser()
        try:
            outcome = await self._qr_wait_loop(flow, session_path)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_qr_flow(flow, exc)
            return

        if outcome == "password":
            # Flow stays alive; submit_password reuses the existing 2FA path.
            return
        if outcome == "expired":
            await self._expire_qr_flow(flow)
            return

        try:
            async with telegram_client_factory.session_file_lock(session_path):
                authorized = await self._is_user_authorized(flow.client)
                accounts._chmod_session_files(session_path)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._fail_qr_flow(flow, exc)
            return

        if not authorized:
            await self._fail_qr_flow(
                flow,
                TelegramLoginAuthError("Telegram QR login did not authorize the session"),
            )
            return
        await self._finish_authorized_qr(flow)

    async def _finish_authorized_qr(self, flow: TelegramLoginFlow) -> None:
        """Finalize a scanned QR flow without discarding it.

        QR success is delivered to the UI through status polling, so the flow
        must stay findable as a terminal ``authorized`` snapshot — otherwise the
        next poll races the discard and 404s even though login succeeded.
        """
        account = self._mark_authorized(flow.profile_id, authorized=True)
        flow.account = account
        flow.step = "authorized"
        if self._profile_logins.get(flow.profile_id) == flow.login_id:
            self._profile_logins.pop(flow.profile_id, None)
        await self._disconnect(flow.client)
        accounts._chmod_session_files(Path(flow.session_path).expanduser())
        log.info("telegram_login.qr_authorized profile=%s", flow.profile_id)

    async def _qr_wait_loop(self, flow: TelegramLoginFlow, session_path: Path) -> str:
        deadline = self._now() + timedelta(seconds=self.ttl_seconds)
        async with telegram_client_factory.session_file_lock(session_path):
            while True:
                remaining = (deadline - self._now()).total_seconds()
                if remaining <= 0:
                    return "expired"
                timeout = self._qr_timeout(flow, remaining)
                try:
                    await _maybe_await(flow.qr.wait(timeout))
                except asyncio.TimeoutError:
                    await _maybe_await(flow.qr.recreate())
                    self._refresh_qr(flow)
                    accounts._chmod_session_files(session_path)
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if _is_password_required_error(exc):
                        flow.step = "password_required"
                        accounts._chmod_session_files(session_path)
                        return "password"
                    raise
                accounts._chmod_session_files(session_path)
                return "authorized"

    def _qr_timeout(self, flow: TelegramLoginFlow, remaining: float) -> float:
        candidates = [remaining]
        expires = getattr(flow.qr, "expires", None)
        if isinstance(expires, datetime):
            exp = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
            token_ttl = (exp - self._now()).total_seconds()
            if token_ttl > 0:
                candidates.append(token_ttl)
        return max(1.0, min(candidates))

    def _refresh_qr(self, flow: TelegramLoginFlow) -> None:
        flow.qr_url = flow.qr.url
        flow.qr_image = _qr_png_data_url(flow.qr.url)

    async def _fail_qr_flow(self, flow: TelegramLoginFlow, exc: BaseException) -> None:
        flow.error = _safe_telegram_error(exc)
        flow.step = "error"
        if self._profile_logins.get(flow.profile_id) == flow.login_id:
            self._profile_logins.pop(flow.profile_id, None)
        await self._disconnect(flow.client)
        accounts._chmod_session_files(Path(flow.session_path).expanduser())
        log.warning("telegram_login.qr_failed profile=%s error=%s", flow.profile_id, flow.error)

    async def _expire_qr_flow(self, flow: TelegramLoginFlow) -> None:
        flow.error = "Telegram QR login expired"
        flow.step = "error"
        if self._profile_logins.get(flow.profile_id) == flow.login_id:
            self._profile_logins.pop(flow.profile_id, None)
        await self._disconnect(flow.client)
        accounts._chmod_session_files(Path(flow.session_path).expanduser())
        log.info("telegram_login.qr_expired profile=%s", flow.profile_id)

    async def _qr_login(self, client: Any) -> Any:
        return await _maybe_await(_telegram_client(client).qr_login())

    async def submit_code(self, login_id: str, code: str) -> dict[str, Any]:
        """Submit the Telegram login code for an active flow."""

        flow = await self._require_flow(login_id)
        if flow.step != "code_sent":
            raise LoginStepError("Login code cannot be submitted for this step")

        # Диагностика: длина кода, не сам код (секрет наружу не пишем).
        log.info(
            "telegram_login.submit_code.start profile=%s code_len=%d",
            flow.profile_id,
            len(code or ""),
        )
        async with telegram_client_factory.session_file_lock(Path(flow.session_path)):
            try:
                await self._sign_in_code(flow, code)
            except Exception as exc:
                accounts._chmod_session_files(Path(flow.session_path).expanduser())
                if _is_password_required_error(exc):
                    flow.step = "password_required"
                    log.info(
                        "telegram_login.submit_code.password_required profile=%s",
                        flow.profile_id,
                    )
                    return self._flow_snapshot(flow, include_phone=False)
                if _is_expired_code_error(exc):
                    log.warning(
                        "telegram_login.submit_code.expired profile=%s error=%s",
                        flow.profile_id,
                        _safe_telegram_error(exc),
                    )
                    await self._discard_flow(flow)
                    raise InvalidTelegramCodeError(_expired_code_message(exc)) from exc
                if _is_invalid_code_error(exc):
                    log.warning(
                        "telegram_login.submit_code.invalid profile=%s error=%s",
                        flow.profile_id,
                        _safe_telegram_error(exc),
                    )
                    raise InvalidTelegramCodeError("Telegram rejected the login code") from exc
                log.warning(
                    "telegram_login.submit_code.failed profile=%s error=%s",
                    flow.profile_id,
                    _safe_telegram_error(exc),
                )
                raise TelegramLoginAuthError(_safe_telegram_error(exc)) from exc
            accounts._chmod_session_files(Path(flow.session_path).expanduser())

            if not await self._is_user_authorized(flow.client):
                log.warning(
                    "telegram_login.submit_code.not_authorized profile=%s",
                    flow.profile_id,
                )
                raise TelegramLoginAuthError("Telegram login did not authorize the session")
            log.info("telegram_login.submit_code.authorized profile=%s", flow.profile_id)
            return await self._finish_authorized(flow)

    async def submit_password(self, login_id: str, password: str) -> dict[str, Any]:
        """Submit the Telegram 2FA password for an active flow."""

        flow = await self._require_flow(login_id)
        if flow.step != "password_required":
            raise LoginStepError("Password can only be submitted after Telegram requires 2FA")

        async with telegram_client_factory.session_file_lock(Path(flow.session_path)):
            try:
                await self._sign_in_password(flow, password)
            except Exception as exc:
                accounts._chmod_session_files(Path(flow.session_path).expanduser())
                if _is_invalid_password_error(exc):
                    raise InvalidTelegramPasswordError(
                        "Telegram rejected the 2FA password"
                    ) from exc
                raise TelegramLoginAuthError(_safe_telegram_error(exc)) from exc
            accounts._chmod_session_files(Path(flow.session_path).expanduser())

            if not await self._is_user_authorized(flow.client):
                raise TelegramLoginAuthError("Telegram 2FA login did not authorize the session")
            return await self._finish_authorized(flow)

    async def status(self, login_id: str) -> dict[str, Any]:
        """Return a public snapshot for an active login flow."""

        flow = await self._require_flow(login_id)
        return self._snapshot(flow)

    async def cancel(self, login_id: str) -> dict[str, bool]:
        """Cancel a login flow and disconnect its Telegram client."""

        flow = self._flows.get(login_id)
        if flow is None:
            raise UnknownLoginError(f"Unknown Telegram login id: {login_id}")
        await self._discard_flow(flow)
        return {"ok": True}

    async def cleanup_expired(self) -> int:
        """Disconnect and remove expired login flows."""

        expired = [
            flow
            for flow in list(self._flows.values())
            if self._is_expired(flow)
        ]
        for flow in expired:
            await self._discard_flow(flow)
        return len(expired)

    def _load_private_profile(self, profile_id: str) -> Any:
        loader = getattr(self.account_module, "_load_private_profile", None)
        if loader is None:
            raise LoginCredentialsMissingError("Account service cannot load credentials")
        return _call_with_supported_kwargs(
            loader,
            profile_id,
            store_root=self.store_root,
            config_module=self.config_module,
        )

    def _assert_credentials(self, profile: Any) -> None:
        missing = [
            name
            for name in ("api_id", "api_hash", "phone")
            if not getattr(profile, name, None)
        ]
        if missing:
            raise LoginCredentialsMissingError(
                f"Missing Telegram credential fields: {', '.join(missing)}"
            )

    def _create_client(self, profile_id: str) -> Any:
        return _call_with_supported_kwargs(
            self.client_factory,
            profile_id,
            store_root=self.store_root,
            config_module=self.config_module,
        )

    async def _cancel_profile_flow(self, profile_id: str) -> None:
        old_login_id = self._profile_logins.get(profile_id)
        if old_login_id is None:
            return
        old_flow = self._flows.get(old_login_id)
        if old_flow is not None:
            await self._discard_flow(old_flow)

    async def _require_flow(self, login_id: str) -> TelegramLoginFlow:
        flow = self._flows.get(login_id)
        if flow is None:
            raise UnknownLoginError(f"Unknown Telegram login id: {login_id}")
        if self._is_expired(flow):
            await self._discard_flow(flow)
            raise LoginExpiredError(f"Telegram login expired: {login_id}")
        return flow

    async def _finish_authorized(self, flow: TelegramLoginFlow) -> dict[str, Any]:
        try:
            account = self._mark_authorized(flow.profile_id, authorized=True)
            return self._authorized_snapshot(account)
        finally:
            await self._discard_flow(flow)

    def _mark_authorized(self, profile_id: str, *, authorized: bool) -> Any:
        marker = getattr(self.account_module, "mark_profile_authorized", None)
        if marker is None:
            raise AccountAuthorizationUpdateMissingError(
                "Account service does not expose mark_profile_authorized"
            )
        return _call_with_supported_kwargs(
            marker,
            profile_id,
            authorized=authorized,
            store_root=self.store_root,
            config_module=self.config_module,
        )

    async def _discard_flow(self, flow: TelegramLoginFlow) -> None:
        self._flows.pop(flow.login_id, None)
        if self._profile_logins.get(flow.profile_id) == flow.login_id:
            self._profile_logins.pop(flow.profile_id, None)
        await self._cancel_flow_task(flow)
        await self._disconnect(flow.client)
        accounts._chmod_session_files(Path(flow.session_path).expanduser())

    async def _cancel_flow_task(self, flow: TelegramLoginFlow) -> None:
        task = getattr(flow, "task", None)
        if task is None or task is asyncio.current_task():
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover - worker already surfaced its own error
            pass

    def _snapshot(self, flow: TelegramLoginFlow) -> dict[str, Any]:
        if flow.step == "qr_pending":
            return self._qr_snapshot(flow)
        if flow.step == "authorized":
            return self._authorized_snapshot(flow.account)
        if flow.step == "error":
            return {
                "login_id": flow.login_id,
                "profile_id": flow.profile_id,
                "step": "error",
                "error": flow.error or "Telegram login failed",
            }
        return self._flow_snapshot(flow)

    def _qr_snapshot(self, flow: TelegramLoginFlow) -> dict[str, Any]:
        return {
            "login_id": flow.login_id,
            "profile_id": flow.profile_id,
            "step": "qr_pending",
            "qr_url": flow.qr_url,
            "qr_image": flow.qr_image,
            "expires_at": flow.expires_at.isoformat(),
        }

    def _flow_snapshot(
        self,
        flow: TelegramLoginFlow,
        *,
        include_phone: bool = True,
    ) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "login_id": flow.login_id,
            "profile_id": flow.profile_id,
            "step": flow.step,
            "expires_at": flow.expires_at.isoformat(),
        }
        if include_phone:
            snapshot["phone_masked"] = flow.phone_masked
        return snapshot

    def _authorized_snapshot(self, account: Any) -> dict[str, Any]:
        payload = account.to_dict() if hasattr(account, "to_dict") else account
        return {"step": "authorized", "account": payload}

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _is_expired(self, flow: TelegramLoginFlow) -> bool:
        return self._now() >= flow.expires_at

    async def _connect(self, client: Any) -> None:
        await _maybe_await(_telegram_client(client).connect())

    async def _disconnect(self, client: Any) -> None:
        disconnect = getattr(_telegram_client(client), "disconnect", None)
        if disconnect is not None:
            await _maybe_await(disconnect())

    async def _is_user_authorized(self, client: Any) -> bool:
        return bool(await _maybe_await(_telegram_client(client).is_user_authorized()))

    async def _send_code_request(
        self,
        client: Any,
        phone: str,
        *,
        force_sms: bool = False,
    ) -> Any:
        return await _maybe_await(
            _call_with_supported_kwargs(
                _telegram_client(client).send_code_request,
                phone,
                force_sms=force_sms,
            )
        )

    async def _sign_in_code(self, flow: TelegramLoginFlow, code: str) -> Any:
        return await _maybe_await(
            _telegram_client(flow.client).sign_in(
                phone=flow.phone,
                code=code,
                phone_code_hash=flow.phone_code_hash or None,
            )
        )

    async def _sign_in_password(self, flow: TelegramLoginFlow, password: str) -> Any:
        return await _maybe_await(
            _telegram_client(flow.client).sign_in(password=password)
        )


def _telegram_client(client: Any) -> Any:
    return getattr(client, "client", client)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _mask_phone(phone: str) -> str:
    if not phone:
        return ""
    prefix = "+" if phone.startswith("+") else ""
    digits = phone[1:] if prefix else phone
    if len(digits) <= 4:
        return prefix + "*" * len(digits)
    return prefix + "*" * (len(digits) - 4) + digits[-4:]


def _sent_code_delivery_name(value: Any) -> str:
    if value is None:
        return "none"
    name = value.__class__.__name__
    if name and name != "type":
        return name
    return str(value)


def _safe_telegram_error(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        return f"Telegram login failed: {exc.__class__.__name__}"
    message = re.sub(r"\+?\d{10,15}", "<phone>", message)
    message = re.sub(r"\b[a-fA-F0-9]{32,}\b", "<token>", message)
    message = re.sub(r"\b[\w.-]*(?:hash|secret|token)[\w.-]*\b", "<token>", message, flags=re.IGNORECASE)
    message = re.sub(r"(/[^\s:]+)+", "<path>", message)
    return f"Telegram login failed: {exc.__class__.__name__}: {message}"


def _delete_session_files(session_path: Path) -> None:
    if not str(session_path):
        return
    base_paths = [session_path]
    if session_path.suffix != ".session":
        base_paths.append(Path(f"{session_path}.session"))
    candidates: list[Path] = []
    for base_path in base_paths:
        candidates.extend(
            [
                base_path,
                base_path.with_name(f"{base_path.name}-journal"),
                base_path.with_name(f"{base_path.name}-shm"),
                base_path.with_name(f"{base_path.name}-wal"),
            ]
        )
    for path in candidates:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _call_with_supported_kwargs(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args, **kwargs)

    parameters = signature.parameters.values()
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if accepts_kwargs:
        return func(*args, **kwargs)

    supported = {
        name: value
        for name, value in kwargs.items()
        if name in signature.parameters
    }
    return func(*args, **supported)


def _is_password_required_error(exc: BaseException) -> bool:
    text = f"{exc.__class__.__name__} {exc}".lower()
    return (
        "session_password_needed" in text
        or "passwordneeded" in text.replace("_", "")
        or "password required" in text
        or "password needed" in text
        or "two-step" in text
        or "2fa" in text
    )


def _is_invalid_code_error(exc: BaseException) -> bool:
    text = f"{exc.__class__.__name__} {exc}".lower()
    normalized = text.replace("_", "").replace(" ", "")
    return (
        "phone_code_invalid" in text
        or "phonecodeinvalid" in normalized
        or "code invalid" in text
        or "invalid code" in text
    )


def _is_expired_code_error(exc: BaseException) -> bool:
    text = f"{exc.__class__.__name__} {exc}".lower()
    normalized = text.replace("_", "").replace(" ", "")
    return (
        "phone_code_expired" in text
        or "phonecodeexpired" in normalized
        or "phone_code_hash_invalid" in text
        or "phonecodehashinvalid" in normalized
        or "invalid or expired" in text and "phone_code_hash" in text
        or "code expired" in text
        or "expired code" in text
    )


def _expired_code_message(exc: BaseException) -> str:
    text = f"{exc.__class__.__name__} {exc}".lower()
    normalized = text.replace("_", "").replace(" ", "")
    if (
        "phone_code_hash_invalid" in text
        or "phonecodehashinvalid" in normalized
        or "invalid or expired" in text and "phone_code_hash" in text
    ):
        return "Telegram code request expired"
    return "Telegram login code expired"


def _is_invalid_password_error(exc: BaseException) -> bool:
    text = f"{exc.__class__.__name__} {exc}".lower()
    return (
        "password_hash_invalid" in text
        or "password invalid" in text
        or "invalid password" in text
    )
