"""Terminal Telegram login probe for web-platform account profiles."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from backend import accounts


def _mask_phone(phone: str) -> str:
    prefix = "+" if phone.startswith("+") else ""
    digits = phone[1:] if prefix else phone
    if len(digits) <= 4:
        return prefix + "*" * len(digits)
    return f"{prefix}{'*' * (len(digits) - 4)}{digits[-4:]}"


def _hash_fingerprint(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _session_path(profile: accounts.AccountProfilePrivate, *, use_profile_session: bool) -> Path:
    path = Path(profile.session_path).expanduser()
    if use_profile_session:
        return path
    return path.with_name(f"{path.stem}-terminal-test.session")


async def _main(args: argparse.Namespace) -> int:
    profile = accounts._load_private_profile(args.profile)
    session_path = _session_path(
        profile,
        use_profile_session=args.use_profile_session,
    )
    session_path.parent.mkdir(parents=True, exist_ok=True)

    print("Profile:", profile.id, flush=True)
    print("Display:", profile.display_name, flush=True)
    print("Phone:", _mask_phone(profile.phone), flush=True)
    print("API ID present:", bool(profile.api_id), flush=True)
    print("API Hash len:", len(profile.api_hash), flush=True)
    print("API Hash sha256/8:", _hash_fingerprint(profile.api_hash), flush=True)
    print("Session:", session_path, flush=True)

    client = TelegramClient(str(session_path), profile.api_id, profile.api_hash)
    print("Connecting to Telegram...", flush=True)
    await client.connect()
    try:
        if await client.is_user_authorized():
            print("Already authorized.", flush=True)
            if args.use_profile_session:
                accounts.mark_profile_authorized(profile.id, store_root=None)
            return 0

        print("Requesting Telegram code...", flush=True)
        sent_code = await client.send_code_request(
            profile.phone,
            force_sms=args.force_sms,
        )
        print("Code request OK.", flush=True)
        print(
            "Delivery:",
            sent_code.type.__class__.__name__ if sent_code.type else "none",
            flush=True,
        )
        print(
            "Next:",
            sent_code.next_type.__class__.__name__ if sent_code.next_type else "none",
            flush=True,
        )

        code = input("Telegram code: ").strip()
        try:
            await client.sign_in(
                phone=profile.phone,
                code=code,
                phone_code_hash=sent_code.phone_code_hash,
            )
        except SessionPasswordNeededError:
            password = getpass.getpass("Telegram 2FA password: ")
            await client.sign_in(password=password)

        if not await client.is_user_authorized():
            print("Login failed: session is still not authorized.", flush=True)
            return 2

        if args.use_profile_session:
            accounts.mark_profile_authorized(profile.id, store_root=None)
            print("Profile session authorized and marked in account store.", flush=True)
        else:
            print("Terminal test session authorized.", flush=True)
            print(
                "Run again with --use-profile-session if you want to authorize the platform profile session.",
                flush=True,
            )
        return 0
    finally:
        await client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Telegram login using saved web-platform account profile credentials.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Account profile id. Defaults to the active profile.",
    )
    parser.add_argument(
        "--force-sms",
        action="store_true",
        help="Ask Telegram to send SMS when supported.",
    )
    parser.add_argument(
        "--use-profile-session",
        action="store_true",
        help="Write authorization into the platform profile session instead of a terminal-test session.",
    )
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
