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
import inspect
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.custom.conversation import Conversation
from telethon.tl.custom.message import Message
from telethon.tl.functions.messages import SendVoteRequest
from telethon.tl.types import InputMediaPoll, Poll, PollAnswer

try:
    from telethon.tl.types import InputPollAnswer
except ImportError:
    InputPollAnswer = None

from backend import config

_POLL_PARAMS = set(inspect.signature(Poll.__init__).parameters)
_INPUT_MEDIA_POLL_PARAMS = inspect.signature(InputMediaPoll.__init__).parameters
_CORRECT_ANSWERS_ANNOTATION = str(
    _INPUT_MEDIA_POLL_PARAMS["correct_answers"].annotation
)
_CORRECT_ANSWERS_ARE_INT = (
    "int" in _CORRECT_ANSWERS_ANNOTATION
    and "bytes" not in _CORRECT_ANSWERS_ANNOTATION
)

log = logging.getLogger(__name__)

CorrectIndexes = int | list[int]


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
        self.last_reply: Optional[Message] = None

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

    async def send_media(self, path: str, caption: str = "") -> Message:
        """Шлёт локальный медиафайл в @QuizBot как pre-question сообщение."""
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))
        last_exc: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES_ON_FLOOD):
            try:
                msg = await self.client.send_file(
                    config.BOT_USERNAME,
                    file=path,
                    caption=caption or None,
                )
                log.info("→ [media] %s", path)
                return msg
            except FloodWaitError as e:
                last_exc = e
                wait = e.seconds + 2
                log.warning(
                    "FloodWait %ds on media (attempt %d/%d) — sleeping",
                    e.seconds, attempt + 1, config.MAX_RETRIES_ON_FLOOD,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(f"FloodWait retries exhausted on media: {last_exc}")

    async def send_quiz_poll(
        self,
        question: str,
        options: list[str],
        correct_indexes: CorrectIndexes | None = None,
        solution: str = "",
        correct_index: int | None = None,
    ) -> Message:
        """Отправляет quiz-poll в @QuizBot.

        correct_indexes — 0-based индекс или индексы правильных ответов.
        solution — пояснение, видно только если quiz=True (поддерживается ботом).
        Возвращает Message с отправленным poll-ом (нужен для возможного SendVote).
        """
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))
        normalized_correct_indexes = _normalize_correct_indexes(
            correct_indexes if correct_indexes is not None else correct_index
        )

        answers = [
            _poll_answer(opt, i)
            for i, opt in enumerate(options)
        ]
        poll_kwargs = dict(
            id=0,
            question=_twe(question),
            answers=answers,
            quiz=True,
            public_voters=True,
        )
        if "multiple_choice" in _POLL_PARAMS:
            poll_kwargs["multiple_choice"] = len(normalized_correct_indexes) > 1
        # Telethon ≥1.40 (новые Telegram API layers) требуют hash у Poll
        if "hash" in _POLL_PARAMS:
            poll_kwargs["hash"] = 0
        poll = Poll(**poll_kwargs)
        media = InputMediaPoll(
            poll=poll,
            correct_answers=_correct_answers(normalized_correct_indexes),
            solution=solution or "",
            solution_entities=[],
        )

        last_exc: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES_ON_FLOOD):
            try:
                msg = await self.client.send_file(config.BOT_USERNAME, file=media)
                log.info(
                    "→ [poll] %s | %d options, correct=%s, solution=%r",
                    _truncate(question, 80), len(options), normalized_correct_indexes,
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

    async def vote_poll(self, poll_msg: Message, option_indexes: CorrectIndexes) -> None:
        """Голосует за option_indexes (0-based) в poll-сообщении poll_msg.

        Используется как fallback, если бот после отправки регулярного poll-а
        просит проголосовать за правильный ответ.
        """
        normalized_option_indexes = _normalize_correct_indexes(option_indexes)
        await asyncio.sleep(config.rand_delay(config.DELAY_BETWEEN_MESSAGES))
        await self.client(SendVoteRequest(
            peer=config.BOT_USERNAME,
            msg_id=poll_msg.id,
            options=[bytes([option_index]) for option_index in normalized_option_indexes],
        ))
        log.info("⌘ voted options %s in poll msg %d", normalized_option_indexes, poll_msg.id)

    async def wait_reply(self) -> Message:
        """Ждёт следующий ответ от @QuizBot. Бросает asyncio.TimeoutError, если нет."""
        msg = await self._conv.get_response()
        self.last_reply = msg
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


def _normalize_correct_indexes(correct_indexes: CorrectIndexes | None) -> list[int]:
    if correct_indexes is None:
        raise ValueError("correct_indexes is required")
    values = correct_indexes if isinstance(correct_indexes, list) else [correct_indexes]
    if not values:
        raise ValueError("correct_indexes must not be empty")
    if len(set(values)) != len(values):
        raise ValueError("correct_indexes must be unique")
    return values


def _correct_answers(correct_indexes: CorrectIndexes) -> list[int] | list[bytes]:
    """Return correct_answers in the shape expected by the installed Telethon."""
    values = _normalize_correct_indexes(correct_indexes)
    if _CORRECT_ANSWERS_ARE_INT:
        return values
    return [bytes([correct_index]) for correct_index in values]


def _poll_answer(text: str, index: int):
    if _CORRECT_ANSWERS_ARE_INT and InputPollAnswer is not None:
        return InputPollAnswer(text=_twe(text))
    return PollAnswer(text=_twe(text), option=bytes([index]))
