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
import re
from typing import Optional

from telethon.tl.custom.message import Message

import config
from models import Question
from quizbot_client import QuizBotClient

log = logging.getLogger(__name__)

# --- Substring-якоря, скопированные из docs/probe-log.md ---
BOT_PROMPTS = {
    "start_menu":           "С помощью этого бота",
    "ask_quiz_name":        "пришлите название Вашего теста",
    "ask_description":      "пришлите описание для Вашего теста",
    "ask_first_question":   "Отправьте мне первый вопрос",
    "ask_vote_for_correct": "проголосуйте за правильный ответ",
    "ask_next_question":    "Если Вы сделали ошибку",
    "ask_time_limit":       "Укажите ограничение времени",
    "ask_shuffle_mode":     "случайном порядке",
    "quiz_ready":           "Тест готов",
    "final_share":          "External sharing link:",
}

# Подписи кнопок (точные из probe)
BTN_CREATE_NEW_QUIZ = "Создать новый тест"
BTN_TIME_30S = "30 сек"
BTN_SHUFFLE_NONE = "По порядку"

CMD_START = "/start"
CMD_SKIP = "/skip"
CMD_DONE = "/done"

# t.me/QuizBot?start=XXX — формат из probe; ловим и https://-вариант
SHARE_LINK_RE = re.compile(r"(https?://)?t\.me/QuizBot\?start=\S+", re.IGNORECASE)


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
        client, BOT_PROMPTS["start_menu"], step="start_menu",
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
    client: QuizBotClient, q: Question, index_in_quiz: int,
) -> None:
    """Отправляет один вопрос как quiz-poll и дожидается подтверждения."""
    log.info("--- Question %d: %s ---", index_in_quiz, q.question[:60])

    poll_msg = await client.send_quiz_poll(
        question=q.question,
        options=q.options,
        correct_index=q.correct - 1,
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
        log.info("Bot wants manual vote — voting for option %d", q.correct - 1)
        await client.vote_poll(poll_msg, q.correct - 1)
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
