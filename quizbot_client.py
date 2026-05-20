"""Низкоуровневая обёртка Telethon для диалога с @QuizBot.

Изолирует:
- логин через сессию
- conversation-режим (send → get_response)
- задержки и FloodWait-ретраи
- отправку native-poll-ов (для quiz-вопросов)
- голосование в собственных опросах
- логирование стрелок ↔ для удобного дебага

Ничего не знает про вопросы как pydantic-модели — это уровень flow.py.
"""
import asyncio
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.custom.conversation import Conversation
from telethon.tl.custom.message import Message
from telethon.tl.functions.messages import SendVoteRequest
from telethon.tl.types import InputMediaPoll, Poll, PollAnswer

import config

log = logging.getLogger(__name__)


try:
    from telethon.tl.types import TextWithEntities

    def _twe(s: str):
        return TextWithEntities(text=s, entities=[])
except ImportError:
    def _twe(s: str):
        return s


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
                    e.seconds, attempt + 1, config.MAX_RETRIES_ON_FLOOD,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(f"FloodWait retries exhausted: {last_exc}")

    async def send_quiz_poll(
        self,
        question: str,
        options: list[str],
        correct_index: int,
        solution: str = "",
    ) -> Message:
        """Отправляет quiz-poll в @QuizBot.

        correct_index — 0-based индекс правильного ответа.
        solution — пояснение, видно только если quiz=True (поддерживается ботом).
        Возвращает Message с отправленным poll-ом (нужен для возможного SendVote).
        """
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))

        answers = [
            PollAnswer(text=_twe(opt), option=bytes([i]))
            for i, opt in enumerate(options)
        ]
        poll = Poll(
            id=0,
            question=_twe(question),
            answers=answers,
            quiz=True,
            public_voters=True,
        )
        media = InputMediaPoll(
            poll=poll,
            correct_answers=[bytes([correct_index])],
            solution=solution or "",
            solution_entities=[],
        )

        last_exc: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES_ON_FLOOD):
            try:
                msg = await self.client.send_file(config.BOT_USERNAME, file=media)
                log.info(
                    "→ [poll] %s | %d options, correct=%d, solution=%r",
                    _truncate(question, 80), len(options), correct_index,
                    _truncate(solution, 40),
                )
                return msg
            except FloodWaitError as e:
                last_exc = e
                wait = e.seconds + 2
                log.warning(
                    "FloodWait %ds on poll (attempt %d/%d) — sleeping",
                    e.seconds, attempt + 1, config.MAX_RETRIES_ON_FLOOD,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(f"FloodWait retries exhausted on poll: {last_exc}")

    async def vote_poll(self, poll_msg: Message, option_index: int) -> None:
        """Голосует за option_index (0-based) в poll-сообщении poll_msg.

        Используется как fallback, если бот после отправки регулярного poll-а
        просит проголосовать за правильный ответ.
        """
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))
        await self.client(SendVoteRequest(
            peer=config.BOT_USERNAME,
            msg_id=poll_msg.id,
            options=[bytes([option_index])],
        ))
        log.info("⌘ voted option %d in poll msg %d", option_index, poll_msg.id)

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
