"""Probe-скрипт: подключается к Telegram через Telethon и логирует ВСЕ
входящие сообщения от @QuizBot вместе с подписями inline-кнопок.

Legacy-запуск без веб-платформы:
    1. Скопировать backend/.env.example → backend/.env, заполнить API_ID/API_HASH/PHONE
    2. python -m backend.probe
    3. При первом запуске ввести код подтверждения из Telegram
    4. Открыть @QuizBot в любом Telegram-клиенте (телефон/десктоп)
    5. Создать тестовый квиз с 1-2 вопросами руками
    6. В терминале появятся все сообщения бота с разметкой кнопок
    7. Скопировать тексты и подписи кнопок в docs/probe-log.md
    8. Ctrl+C для выхода
"""
import asyncio
import logging
import sys
import traceback

from telethon import TelegramClient, events

from backend import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("probe")

PROBE_LOG_PATH = config.PROBE_LOG_PATH
_probe_log_file = open(PROBE_LOG_PATH, "a", encoding="utf-8")


def tee(line: str = "") -> None:
    print(line, flush=True)
    _probe_log_file.write(line + "\n")
    _probe_log_file.flush()


def _ask_code() -> str:
    print("\n>>> Telegram прислал код подтверждения в чат 'Telegram'.", flush=True)
    print(">>> Введи код (только цифры) и нажми Enter:", flush=True)
    return input("CODE: ").strip()


def _ask_password() -> str:
    print("\n>>> Аккаунт защищён 2FA. Введи cloud-пароль и нажми Enter:", flush=True)
    return input("PASSWORD: ").strip()


async def main() -> None:
    config.assert_credentials()
    print(f">>> API_ID={config.API_ID}, PHONE={config.PHONE}", flush=True)

    client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)

    print(">>> Connecting to Telegram…", flush=True)
    await client.connect()

    if not await client.is_user_authorized():
        print(">>> Session not authorized — starting login flow.", flush=True)
        try:
            await client.send_code_request(config.PHONE)
            code = _ask_code()
            try:
                await client.sign_in(phone=config.PHONE, code=code)
            except Exception as e:
                if "password" in str(e).lower() or "two-step" in str(e).lower() or "SESSION_PASSWORD_NEEDED" in str(e):
                    pwd = _ask_password()
                    await client.sign_in(password=pwd)
                else:
                    raise
        except Exception:
            print(">>> LOGIN FAILED:", flush=True)
            traceback.print_exc()
            await client.disconnect()
            return
        print(">>> Login successful. Session saved.", flush=True)
    else:
        print(">>> Session already authorized — skipping login.", flush=True)

    bot = await client.get_entity(config.BOT_USERNAME)
    log.info("Connected. Listening for messages from @%s (id=%s)", config.BOT_USERNAME, bot.id)
    log.info("Now go to @QuizBot in your Telegram app and create a test quiz manually.")
    log.info("Press Ctrl+C to stop.\n")

    @client.on(events.NewMessage(from_users=bot.id))
    async def handler(event):
        msg = event.message
        tee("=" * 70)
        tee("TEXT:")
        tee(msg.text or "<no text>")
        if msg.buttons:
            tee("")
            tee("BUTTONS:")
            for row_idx, row in enumerate(msg.buttons):
                for col_idx, btn in enumerate(row):
                    tee(f"  [{row_idx},{col_idx}]: {btn.text!r}")
        tee("")

    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProbe stopped.")
    except Exception:
        print("\n>>> UNEXPECTED ERROR:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(2)
