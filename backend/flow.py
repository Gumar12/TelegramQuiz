"""Высокоуровневый сценарий заливки квиза в @QuizBot.

Сценарий выведен из реального probe-прогона (см. docs/probe-log.md). Бот
ожидает каждый вопрос как **native Telegram quiz-poll**, а не как текст +
кнопки. Также после /done бот спрашивает время на ответ и режим
перемешивания — оба задаются дефолтами (30 сек, по порядку).

Этапы:
1. create_quiz — /start → "Создать новый тест" → имя → /skip (описание)
2. upload_question — отправить quiz-poll, дождаться подтверждения
3. finish_quiz — /done → выбор времени → выбор перемешивания → share-link
"""
import asyncio
import logging
from pathlib import Path
import random
import re
from typing import Callable, Optional

from telethon.tl.custom.message import Message

from backend import config
from backend.models import Question
from backend.quizbot_client import QuizBotClient

log = logging.getLogger(__name__)

# --- Substring-якоря, скопированные из docs/probe-log.md ---
BOT_PROMPTS = {
    "start_menu":           "С помощью этого бота",
    "busy_draft":           "Пожалуйста, закончите его или отправьте /cancel",
    "ask_quiz_name":        "пришлите название Вашего теста",
    "ask_description":      "пришлите описание для Вашего теста",
    "ask_first_question":   "Отправьте мне первый вопрос",
    "ask_vote_for_correct": "проголосуйте за правильный ответ",
    "ask_next_question":    "Если Вы сделали ошибку",
    "prelude_create_question": "Нажмите на кнопку, чтобы создать новый вопрос",
    "prelude_already_set":  "Перед вопросом может быть показано только одно сообщение",
    "ask_time_limit":       "Укажите ограничение времени",
    "ask_shuffle_mode":     "случайном порядке",
    "quiz_ready":           "Тест готов",
    "final_share":          "External sharing link:",
}

# Подписи кнопок (точные из probe)
BTN_CREATE_NEW_QUIZ = "Создать новый тест"
BTN_CREATE_QUESTION = "Создать вопрос"
BTN_TIME_30S = "30 сек"
BTN_SHUFFLE_NONE = "По порядку"

CMD_START = "/start"
CMD_CANCEL = "/cancel"
CMD_SKIP = "/skip"
CMD_DONE = "/done"

# t.me/QuizBot?start=XXX — формат из probe; ловим и https://-вариант
SHARE_LINK_RE = re.compile(r"(https?://)?t\.me/QuizBot\?start=\S+", re.IGNORECASE)
MEDIA_CAPTION_LIMIT = 1024


class UnexpectedBotState(RuntimeError):
    """Бот ответил не тем, что мы ждали. Hard abort."""


def _has_button(msg: Message, text: str) -> bool:
    if not msg.buttons:
        return False
    needle = text.lower()
    for row in msg.buttons:
        for btn in row:
            if btn.text and needle in btn.text.lower():
                return True
    return False


def _text_contains(msg: Message, needle: str) -> bool:
    return needle.lower() in (msg.text or "").lower()


async def _wait_for_text(
    client: QuizBotClient,
    *needles: str,
    step: str,
    max_skip: int = 3,
) -> Message:
    """Ждёт следующее сообщение от бота, чей текст содержит одну из подстрок.

    Пропускает сообщения без текста (например, эхо poll-а от бота) до max_skip раз.
    Если получили сообщение с текстом, не подходящим ни под один needle, — abort.
    """
    skipped = 0
    while True:
        msg = await client.wait_reply()
        text = msg.text or ""

        if not text.strip():
            if skipped >= max_skip:
                raise UnexpectedBotState(
                    f"[{step}] too many empty-text messages "
                    f"(>{max_skip}); waiting for one of {needles!r}"
                )
            skipped += 1
            log.debug("[%s] skipping empty-text msg (%d/%d)",
                      step, skipped, max_skip)
            continue

        if any(n.lower() in text.lower() for n in needles):
            return msg

        raise UnexpectedBotState(
            f"[{step}] expected one of {needles!r}, got: {text!r}"
        )


async def create_quiz(client: QuizBotClient, quiz_name: str) -> None:
    """Старт + создание квиза + установка имени + пропуск описания."""
    log.info("=== Creating quiz: %s ===", quiz_name)

    await client.send_text(CMD_START)

    # Стартовое меню с кнопками "Создать новый тест" / "Мои тесты" / язык
    reply = await _wait_for_text(
        client,
        BOT_PROMPTS["start_menu"],
        BOT_PROMPTS["busy_draft"],
        step="start_menu",
    )
    if _text_contains(reply, BOT_PROMPTS["busy_draft"]):
        log.info("Existing draft quiz detected; cancelling it before retry")
        await client.send_text(CMD_CANCEL)
        reply = await _wait_for_text(
            client,
            BOT_PROMPTS["start_menu"],
            "отмен",
            "удален",
            step="cancel_draft",
        )
        if not _text_contains(reply, BOT_PROMPTS["start_menu"]):
            await client.send_text(CMD_START)
            reply = await _wait_for_text(
                client, BOT_PROMPTS["start_menu"], step="start_menu_after_cancel",
            )
    if not _has_button(reply, BTN_CREATE_NEW_QUIZ):
        raise UnexpectedBotState(
            f"start menu has no '{BTN_CREATE_NEW_QUIZ}' button. "
            f"Buttons: {[b.text for row in (reply.buttons or []) for b in row]}"
        )
    await client.click(reply, text=BTN_CREATE_NEW_QUIZ)

    # "пришлите название Вашего теста"
    await _wait_for_text(
        client, BOT_PROMPTS["ask_quiz_name"], step="ask_quiz_name",
    )
    await client.send_text(quiz_name)

    # "пришлите описание... /skip"
    await _wait_for_text(
        client, BOT_PROMPTS["ask_description"], step="ask_description",
    )
    await client.send_text(CMD_SKIP)

    # "Отправьте мне первый вопрос... в виде опроса"
    # У сообщения есть кнопка 'Создать вопрос' — это deep-link, мы её НЕ жмём,
    # а сразу отправляем poll в upload_question.
    await _wait_for_text(
        client, BOT_PROMPTS["ask_first_question"], step="ask_first_question",
    )


async def upload_question(
    client: QuizBotClient,
    q: Question,
    index_in_quiz: int,
    *,
    send_prelude: bool = True,
    shuffle_options: bool = False,
    shuffle_seed: int = 42,
) -> None:
    """Отправляет один вопрос как quiz-poll и дожидается подтверждения."""
    log.info("--- Question %d: %s ---", index_in_quiz, q.question[:60])

    if send_prelude:
        await _send_question_prelude(client, q, index_in_quiz)

    options, correct_indexes = _poll_options(q, index_in_quiz, shuffle_options, shuffle_seed)
    poll_msg = await client.send_quiz_poll(
        question=q.question,
        options=options,
        correct_indexes=correct_indexes,
        solution=q.explanation,
    )

    # Бот может ответить одним из двух способов:
    #   (а) сразу "теперь N вопрос..." → quiz-poll принят с correct внутри
    #   (б) "проголосуйте за правильный ответ" → poll принят как обычный,
    #       нужно проголосовать вручную через SendVote
    reply = await _wait_for_text(
        client,
        BOT_PROMPTS["ask_next_question"],
        BOT_PROMPTS["ask_vote_for_correct"],
        step="poll_ack",
    )

    if _text_contains(reply, BOT_PROMPTS["ask_vote_for_correct"]):
        log.info("Bot wants manual vote — voting for options %s", correct_indexes)
        await client.vote_poll(poll_msg, correct_indexes)
        # После голоса бот пишет "теперь N вопрос..."
        await _wait_for_text(
            client, BOT_PROMPTS["ask_next_question"], step="post_vote_ack",
        )

    # Пауза перед следующим вопросом (или перед /done)
    pause = config.rand_delay(config.DELAY_BETWEEN_QUESTIONS)
    log.info("Pausing %.1fs before next step", pause)
    await asyncio.sleep(pause)

    if index_in_quiz > 0 and index_in_quiz % config.LONG_PAUSE_EVERY_N_QUESTIONS == 0:
        long_pause = config.rand_delay(config.LONG_PAUSE_DURATION)
        log.info("Long pause: %.1fs (every %d questions)",
                 long_pause, config.LONG_PAUSE_EVERY_N_QUESTIONS)
        await asyncio.sleep(long_pause)


def _poll_options(
    q: Question,
    index_in_quiz: int,
    shuffle_options: bool,
    shuffle_seed: int,
) -> tuple[list[str], list[int]]:
    options = list(q.options)
    correct_values = q.correct if isinstance(q.correct, list) else [q.correct]
    correct_answers = [options[correct - 1] for correct in correct_values]
    if shuffle_options:
        random.Random(f"{shuffle_seed}:{index_in_quiz}:{q.question}").shuffle(options)
    correct_indexes = sorted(options.index(correct_answer) for correct_answer in correct_answers)
    return options, correct_indexes


def _context_key(q: Question) -> tuple[str, str, tuple[str, ...]] | None:
    context_title = q.context_title.strip()
    context = q.context.strip()
    media = tuple(q.media or [])
    if not context_title and not context and not media:
        return None
    return context_title, context, media


async def upload_questions(
    client: QuizBotClient,
    questions: list[Question],
    *,
    context_send_mode: str = "once",
    shuffle_options: bool = True,
    shuffle_seed: int = 42,
    progress_callback: Callable[[int, int, Question], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> None:
    if context_send_mode not in {"once", "per-question"}:
        raise ValueError("context_send_mode must be 'once' or 'per-question'")

    last_context_key: tuple[str, str, tuple[str, ...]] | None = None
    total = len(questions)
    for index, question in enumerate(questions, start=1):
        if cancel_check:
            cancel_check()
        context_key = _context_key(question)
        send_prelude = True
        if context_send_mode == "once":
            send_prelude = context_key is not None and context_key != last_context_key
            last_context_key = context_key

        await upload_question(
            client,
            question,
            index_in_quiz=index,
            send_prelude=send_prelude,
            shuffle_options=shuffle_options,
            shuffle_seed=shuffle_seed,
        )
        if progress_callback:
            progress_callback(index, total, question)
        if cancel_check:
            cancel_check()


def _context_message(q: Question) -> str:
    title = q.context_title.strip()
    if title.lower() == "контекст":  # выбросить авто-болванку, осмысленные заголовки оставить
        title = ""
    parts = [part for part in [title, q.context.strip()] if part]
    return "\n\n".join(parts)


def _caption_for_media(context: str) -> str:
    if len(context) <= MEDIA_CAPTION_LIMIT:
        return context
    return context[:MEDIA_CAPTION_LIMIT - 1].rstrip() + "…"


def _resolve_media_path(media_path: str) -> str:
    raw = str(media_path).strip()
    if not raw:
        return raw
    if re.match(r"^(https?://|tg://)", raw, re.IGNORECASE):
        return raw

    path = Path(raw).expanduser()
    candidates: list[Path] = [path]
    if not path.is_absolute():
        normalized = raw.replace("\\", "/").lstrip("/")
        relative = Path(normalized)
        candidates.extend(
            [
                config.PROJECT_ROOT / relative,
                config.DATA_DIR / relative,
                config.DATA_DIR / "media" / relative.name,
            ]
        )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return raw


def _find_create_question_button(msg: Message) -> str:
    if not msg.buttons:
        raise UnexpectedBotState("prelude prompt has no create-question button")
    for row in msg.buttons:
        for btn in row:
            text = btn.text or ""
            lowered = text.lower()
            if "создат" in lowered and "вопрос" in lowered:
                return text
    raise UnexpectedBotState(
        f"prelude prompt has no create-question button. "
        f"Buttons: {[b.text for row in (msg.buttons or []) for b in row]}"
    )


async def _wait_after_prelude(client: QuizBotClient, step: str) -> None:
    reply = await _wait_for_text(
        client,
        BOT_PROMPTS["ask_first_question"],
        BOT_PROMPTS["ask_next_question"],
        BOT_PROMPTS["prelude_create_question"],
        BOT_PROMPTS["prelude_already_set"],
        step=step,
    )
    if (
        _text_contains(reply, BOT_PROMPTS["prelude_create_question"])
        or _text_contains(reply, BOT_PROMPTS["prelude_already_set"])
    ):
        button_text = _find_create_question_button(reply)
        await client.click(reply, text=button_text)


async def _click_create_question_if_available(client: QuizBotClient) -> None:
    last_reply = getattr(client, "last_reply", None)
    if last_reply is None or not getattr(last_reply, "buttons", None):
        return
    try:
        button_text = _find_create_question_button(last_reply)
    except UnexpectedBotState:
        return

    await client.click(last_reply, text=button_text)


async def _send_question_prelude(
    client: QuizBotClient,
    q: Question,
    index_in_quiz: int,
) -> None:
    context = _context_message(q)
    media_paths = list(q.media or [])
    if context or media_paths:
        await _click_create_question_if_available(client)

    if media_paths:
        if len(media_paths) > 1:
            log.warning(
                "Question %d has %d media files; @QuizBot supports one pre-question message, using first",
                index_in_quiz,
                len(media_paths),
            )
        media_path = _resolve_media_path(media_paths[0])
        log.info("Sending media before question %d: %s", index_in_quiz, media_path)
        await client.send_media(media_path, caption=_caption_for_media(context))
        await _wait_after_prelude(client, step="media_ack")
        return

    if context:
        log.info("Sending context before question %d", index_in_quiz)
        await client.send_text(context)
        await _wait_after_prelude(client, step="context_ack")


async def finish_quiz(client: QuizBotClient) -> str:
    """/done → выбор времени → выбор режима перемешивания → share-link."""
    log.info("=== Finishing quiz ===")

    await client.send_text(CMD_DONE)

    # "Укажите ограничение времени" с кнопками 10/15/30 сек / 1мин / ...
    reply = await _wait_for_text(
        client, BOT_PROMPTS["ask_time_limit"], step="ask_time_limit",
    )
    if not _has_button(reply, BTN_TIME_30S):
        raise UnexpectedBotState(
            f"time-limit prompt has no '{BTN_TIME_30S}' button"
        )
    await client.click(reply, text=BTN_TIME_30S)

    # "в случайном порядке?" с кнопками перемешивания
    reply = await _wait_for_text(
        client, BOT_PROMPTS["ask_shuffle_mode"], step="ask_shuffle_mode",
    )
    if not _has_button(reply, BTN_SHUFFLE_NONE):
        raise UnexpectedBotState(
            f"shuffle prompt has no '{BTN_SHUFFLE_NONE}' button"
        )
    await client.click(reply, text=BTN_SHUFFLE_NONE)

    # Бот может прислать "Тест готов." и потом отдельно share-link, либо одним.
    # Сначала ищем share-link (более информативный маркер).
    final = await _wait_for_text(
        client,
        BOT_PROMPTS["final_share"],
        BOT_PROMPTS["quiz_ready"],
        step="quiz_ready_or_share",
    )

    if not _text_contains(final, BOT_PROMPTS["final_share"]):
        # Это было "Тест готов." — ждём следующее сообщение со share-link
        final = await _wait_for_text(
            client, BOT_PROMPTS["final_share"], step="final_share",
        )

    link_match = SHARE_LINK_RE.search(final.text or "")
    if not link_match:
        raise UnexpectedBotState(
            f"No share link found in final message: {final.text!r}"
        )
    link = link_match.group(0)
    # Нормализуем: добавим https:// если отсутствует
    if not link.startswith(("http://", "https://")):
        link = "https://" + link
    return link
