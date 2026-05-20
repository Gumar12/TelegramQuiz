"""Probe-скрипт: подключается к Telegram через Telethon и логирует ВСЕ
входящие сообщения от @QuizBot вместе с подписями inline-кнопок.

Запуск:
    1. Скопировать .env.example → .env, заполнить API_ID/API_HASH/PHONE
    2. python probe.py
    3. При первом запуске ввести код подтверждения из Telegram
    4. Открыть @QuizBot в любом Telegram-клиенте (телефон/десктоп)
    5. Создать тестовый квиз с 1-2 вопросами руками
    6. В терминале появятся все сообщения бота с разметкой кнопок
    7. Скопировать тексты и подписи кнопок в docs/probe-log.md
    8. Ctrl+C для выхода
"""
import asyncio
import logging

from telethon import TelegramClient, events

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("probe")


async def main() -> None:
    config.assert_credentials()
    client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
    await client.start(phone=config.PHONE)
    bot = await client.get_entity(config.BOT_USERNAME)
    log.info("Connected. Listening for messages from @%s (id=%s)", config.BOT_USERNAME, bot.id)
    log.info("Now go to @QuizBot in your Telegram app and create a test quiz manually.")
    log.info("Press Ctrl+C to stop.\n")

    @client.on(events.NewMessage(from_users=bot.id))
    async def handler(event):
        msg = event.message
        print("=" * 70)
        print("TEXT:")
        print(msg.text or "<no text>")
        if msg.buttons:
            print("\nBUTTONS:")
            for row_idx, row in enumerate(msg.buttons):
                for col_idx, btn in enumerate(row):
                    print(f"  [{row_idx},{col_idx}]: {btn.text!r}")
        print()

    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProbe stopped.")
