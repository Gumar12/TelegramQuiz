"""Низкоуровневая обёртка Telethon для диалога с @QuizBot.

Изолирует:
- логин через сессию
- conversation-режим (send → get_response)
- задержки и FloodWait-ретраи
- логирование стрелок ↔ для удобного дебага

Ничего не знает про вопросы — это уровень flow.py.
"""
import asyncio
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.custom.conversation import Conversation
from telethon.tl.custom.message import Message

import config

log = logging.getLogger(__name__)


class QuizBotClient:
    """Async context manager: открывает сессию + conversation с @QuizBot."""

    def __init__(self):
        self.client = TelegramClient(
            config.SESSION_NAME, config.API_ID, config.API_HASH
        )
        self._conv: Optional[Conversation] = None

    async def __aenter__(self) -> "QuizBotClient":
        await self.client.start(phone=config.PHONE)
        log.info("Telegram session started")
        self._conv = self.client.conversation(
            config.BOT_USERNAME,
            timeout=config.WAIT_REPLY_TIMEOUT,
            exclusive=True,
        )
        await self._conv.__aenter__()
        log.info("Opened conversation with @%s", config.BOT_USERNAME)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conv is not None:
            await self._conv.__aexit__(exc_type, exc_val, exc_tb)
        await self.client.disconnect()
        log.info("Telegram session closed")

    async def send_text(self, text: str) -> Message:
        """Шлёт текст в @QuizBot с задержкой и FloodWait-обработкой."""
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))
        last_exc: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES_ON_FLOOD):
            try:
                msg = await self._conv.send_message(text)
                log.info("→ %s", _truncate(text, 100))
                return msg
            except FloodWaitError as e:
                last_exc = e
                wait = e.seconds + 2
                log.warning(
                    "FloodWait %ds (attempt %d/%d) — sleeping",
                    e.seconds,
                    attempt + 1,
                    config.MAX_RETRIES_ON_FLOOD,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(f"FloodWait retries exhausted: {last_exc}")

    async def wait_reply(self) -> Message:
        """Ждёт следующий ответ от @QuizBot. Бросает asyncio.TimeoutError, если нет."""
        msg = await self._conv.get_response()
        log.info("← %s", _truncate(msg.text or "<no text>", 200))
        if msg.buttons:
            labels = [b.text for row in msg.buttons for b in row]
            log.debug("   buttons: %s", labels)
        return msg

    async def click(
        self,
        msg: Message,
        *,
        text: Optional[str] = None,
        index: Optional[int] = None,
    ) -> None:
        """Нажимает inline-кнопку по тексту или индексу."""
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))
        if text is not None:
            await msg.click(text=text)
            log.info("⌘ clicked button: %r", text)
        elif index is not None:
            await msg.click(index)
            log.info("⌘ clicked button index: %d", index)
        else:
            raise ValueError("must specify either text= or index=")


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"
