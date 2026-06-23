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
from typing import Callable, Optional

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


class FloodWaitCapExceeded(RuntimeError):
    """FloodWait дольше порога: не спим часами, а отдаём наверх с retry-after.

    Несёт actionable-метаданные (`retry_after`/`cooldown_seconds`), чтобы
    оркестратор поставил run на контролируемую паузу/кулдаун.
    """

    def __init__(self, retry_after: int, cap_seconds: float, *, context: str = ""):
        self.retry_after = retry_after
        self.seconds = retry_after  # совместимость с classify-ветками FloodWait
        self.cooldown_seconds = retry_after
        self.cap_seconds = cap_seconds
        suffix = f" on {context}" if context else ""
        super().__init__(
            f"FloodWait {retry_after}s exceeds cap {cap_seconds:g}s{suffix}: "
            "controlled pause required"
        )


try:
    from telethon.tl.types import TextWithEntities

    def _twe(s: str):
        return TextWithEntities(text=s, entities=[])
except ImportError:
    def _twe(s: str):
        return s


class QuizBotClient:
    """Async context manager: открывает сессию + conversation с @QuizBot."""

    def __init__(
        self,
        *,
        session_name: str | None = None,
        api_id: int | None = None,
        api_hash: str | None = None,
        phone: str | None = None,
        timing_profile: config.TimingProfile | None = None,
        session_chmod_callback: Callable[[], None] | None = None,
    ):
        self.session_name = (
            session_name if session_name is not None else config.SESSION_NAME
        )
        self.api_id = api_id if api_id is not None else config.API_ID
        self.api_hash = api_hash if api_hash is not None else config.API_HASH
        self.phone = phone if phone is not None else config.PHONE
        self.timing_profile = timing_profile
        self._session_chmod_callback = session_chmod_callback
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        self._conv: Optional[Conversation] = None
        self.last_reply: Optional[Message] = None

    async def __aenter__(self) -> "QuizBotClient":
        try:
            await self.client.start(phone=self.phone)
        except BaseException:
            try:
                await self.client.disconnect()
            finally:
                self._chmod_session_files()
            raise

        try:
            self._chmod_session_files()
            log.info("Telegram session started")
            self._conv = self.client.conversation(
                config.BOT_USERNAME,
                timeout=config.WAIT_REPLY_TIMEOUT,
                exclusive=True,
            )
            await self._conv.__aenter__()
            log.info("Opened conversation with @%s", config.BOT_USERNAME)
            return self
        except BaseException:
            try:
                await self.client.disconnect()
            finally:
                self._chmod_session_files()
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if self._conv is not None:
                await self._conv.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            try:
                await self.client.disconnect()
            finally:
                self._chmod_session_files()
                log.info("Telegram session closed")

    def _chmod_session_files(self) -> None:
        if self._session_chmod_callback is not None:
            self._session_chmod_callback()

    def _delay_between_messages(self) -> tuple[float, float]:
        timing_profile = getattr(self, "timing_profile", None)
        if timing_profile is not None:
            return timing_profile.delay_between_messages
        return config.DELAY_BETWEEN_MESSAGES

    def _flood_wait_max_seconds(self) -> float:
        timing_profile = getattr(self, "timing_profile", None)
        if timing_profile is not None:
            return timing_profile.flood_wait_max_seconds
        return config.FLOOD_WAIT_MAX_SECONDS

    async def _handle_flood_wait(self, e: FloodWaitError, attempt: int, context: str) -> None:
        """Обрабатывает один FloodWait внутри retry-цикла.

        Выше порога — поднимает FloodWaitCapExceeded (без многочасового сна).
        Ниже порога — bounded-сон с джиттером, после чего цикл делает ретрай.
        """
        cap = self._flood_wait_max_seconds()
        if e.seconds > cap:
            log.warning(
                "FloodWait %ds exceeds cap %gs on %s — classifying as controlled pause",
                e.seconds, cap, context,
            )
            raise FloodWaitCapExceeded(e.seconds, cap, context=context) from e
        wait = e.seconds + config.rand_delay(config.FLOOD_WAIT_RETRY_JITTER)
        log.warning(
            "FloodWait %ds on %s (attempt %d/%d) — sleeping %.1fs",
            e.seconds, context, attempt + 1, config.MAX_RETRIES_ON_FLOOD, wait,
        )
        await asyncio.sleep(wait)

    async def send_text(self, text: str) -> Message:
        """Шлёт текст в @QuizBot с задержкой и FloodWait-обработкой."""
        await asyncio.sleep(config.rand_delay(self._delay_between_messages()))
        last_exc: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES_ON_FLOOD):
            try:
                msg = await self._conv.send_message(text)
                log.info("→ %s", _truncate(text, 100))
                return msg
            except FloodWaitError as e:
                last_exc = e
                await self._handle_flood_wait(e, attempt, "text")
        raise RuntimeError(f"FloodWait retries exhausted: {last_exc}")

    async def send_media(self, path: str, caption: str = "") -> Message:
        """Шлёт локальный медиафайл в @QuizBot как pre-question сообщение."""
        await asyncio.sleep(config.rand_delay(self._delay_between_messages()))
        if self._conv is None:
            raise RuntimeError("QuizBot conversation is not open")
        last_exc: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES_ON_FLOOD):
            try:
                msg = await self._conv.send_file(
                    file=path,
                    caption=caption or None,
                )
                log.info("→ [media] %s", path)
                return msg
            except FloodWaitError as e:
                last_exc = e
                await self._handle_flood_wait(e, attempt, "media")
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
        await asyncio.sleep(config.rand_delay(self._delay_between_messages()))
        if self._conv is None:
            raise RuntimeError("QuizBot conversation is not open")
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
        media_kwargs = {
            "poll": poll,
            "correct_answers": _correct_answers(normalized_correct_indexes),
        }
        if solution:
            media_kwargs["solution"] = solution
            media_kwargs["solution_entities"] = []
        media = InputMediaPoll(**media_kwargs)

        last_exc: Optional[Exception] = None
        for attempt in range(config.MAX_RETRIES_ON_FLOOD):
            try:
                msg = await self._conv.send_file(file=media)
                log.info(
                    "→ [poll] %s | %d options, correct=%s, solution=%r",
                    _truncate(question, 80), len(options), normalized_correct_indexes,
                    _truncate(solution, 40),
                )
                return msg
            except FloodWaitError as e:
                last_exc = e
                await self._handle_flood_wait(e, attempt, "poll")
        raise RuntimeError(f"FloodWait retries exhausted on poll: {last_exc}")

    async def vote_poll(self, poll_msg: Message, option_indexes: CorrectIndexes) -> None:
        """Голосует за option_indexes (0-based) в poll-сообщении poll_msg.

        Используется как fallback, если бот после отправки регулярного poll-а
        просит проголосовать за правильный ответ.
        """
        normalized_option_indexes = _normalize_correct_indexes(option_indexes)
        await asyncio.sleep(config.rand_delay(self._delay_between_messages()))
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
        await asyncio.sleep(config.rand_delay(self._delay_between_messages()))
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
