"""Высокоуровневый сценарий заливки квиза в @QuizBot.

Состоит из трёх этапов:
1. create_quiz — /start → создать квиз → дать имя
2. upload_question — для каждого вопроса: текст → варианты → правильный → пояснение
3. finish_quiz — завершить, получить share-link

Тексты бота вынесены в BOT_PROMPTS из docs/probe-log.md. Если @QuizBot
поменяет UI, чинить здесь.
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

# --- Тексты, скопированные из docs/probe-log.md ---
# Используются как substring-маркеры (а не точное равенство), чтобы
# мелкие правки бота не ломали матчинг.
BOT_PROMPTS = {
    "start_menu":         "Create a new quiz",   # FROM_PROBE — подпись кнопки в стартовом меню
    "ask_quiz_name":      "send me the name",     # FROM_PROBE — текст после "Create a new quiz"
    "ask_question_text":  "send me the question", # FROM_PROBE — после имени или после "next question"
    "ask_option":         "Send the options",     # FROM_PROBE — после текста вопроса
    "ask_correct":        "which option is correct", # FROM_PROBE — после всех опций
    "ask_explanation":    "explanation",          # FROM_PROBE — после выбора правильного
    "ask_next_or_done":   "Add the next question", # FROM_PROBE — после пояснения / skip
    "finished":           "your quiz is ready",   # FROM_PROBE — финальное сообщение
}

# Подписи кнопок (точные, из probe). Регистр имеет значение.
BTN_CREATE_QUIZ = "Create a new quiz"     # FROM_PROBE
BTN_SKIP_EXPLANATION = "Skip"             # FROM_PROBE — или команда /skip если кнопки нет
BTN_DONE_WITH_OPTIONS = "/done"           # FROM_PROBE — команда или кнопка
BTN_NEXT_QUESTION = "Next question"       # FROM_PROBE
BTN_FINISH_QUIZ = "Done"                  # FROM_PROBE
SHARE_LINK_RE = re.compile(r"https?://t\.me/\S+")  # FROM_PROBE — формат ссылки


class UnexpectedBotState(RuntimeError):
    """Бот ответил не тем, что мы ждали. Hard abort."""


def assert_contains(text: Optional[str], expected_substr: str, step: str) -> None:
    haystack = (text or "").lower()
    needle = expected_substr.lower()
    if needle not in haystack:
        raise UnexpectedBotState(
            f"[{step}] expected to contain {expected_substr!r}, "
            f"got: {text!r}"
        )


async def create_quiz(client: QuizBotClient, quiz_name: str) -> None:
    """Старт + создание квиза + установка имени."""
    log.info("=== Creating quiz: %s ===", quiz_name)
    await client.send_text("/start")
    reply = await client.wait_reply()

    # @QuizBot может прислать несколько сообщений подряд — нам нужно то,
    # где есть кнопка "Create a new quiz".
    target = reply
    if not _has_button(target, BTN_CREATE_QUIZ):
        target = await client.wait_reply()
        if not _has_button(target, BTN_CREATE_QUIZ):
            raise UnexpectedBotState(
                f"No '{BTN_CREATE_QUIZ}' button found in first two replies"
            )

    await client.click(target, text=BTN_CREATE_QUIZ)
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_quiz_name"], "ask_quiz_name")

    await client.send_text(quiz_name)


async def upload_question(client: QuizBotClient, q: Question, index_in_quiz: int) -> None:
    """Заливает один вопрос. index_in_quiz нужен для пауз между вопросами."""
    log.info("--- Question %d: %s ---", index_in_quiz, q.question[:60])

    # 1. Текст вопроса
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_question_text"], "ask_question_text")
    await client.send_text(q.question)

    # 2. Варианты — отправляем по одному (точное поведение из probe)
    for opt in q.options:
        reply = await client.wait_reply()
        assert_contains(reply.text, BOT_PROMPTS["ask_option"], "ask_option")
        await client.send_text(opt)

    # 3. Команда "опции закончились" — если в probe выяснилось, что нужна
    await client.send_text(BTN_DONE_WITH_OPTIONS)

    # 4. Выбор правильного ответа — это inline-кнопки 0..N-1
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_correct"], "ask_correct")
    await client.click(reply, index=q.correct - 1)

    # 5. Пояснение
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_explanation"], "ask_explanation")
    if q.explanation:
        await client.send_text(q.explanation)
    else:
        # Если кнопка Skip есть — кликаем. Если нет — отправляем /skip.
        if _has_button(reply, BTN_SKIP_EXPLANATION):
            await client.click(reply, text=BTN_SKIP_EXPLANATION)
        else:
            await client.send_text("/skip")

    # 6. Пауза между вопросами + длинная пауза каждые N
    pause = config.rand_delay(config.DELAY_BETWEEN_QUESTIONS)
    log.info("Pausing %.1fs before next question", pause)
    await asyncio.sleep(pause)

    if index_in_quiz > 0 and index_in_quiz % config.LONG_PAUSE_EVERY_N_QUESTIONS == 0:
        long_pause = config.rand_delay(config.LONG_PAUSE_DURATION)
        log.info("Long pause: %.1fs (every %d questions)",
                 long_pause, config.LONG_PAUSE_EVERY_N_QUESTIONS)
        await asyncio.sleep(long_pause)


async def finish_quiz(client: QuizBotClient) -> str:
    """Завершает квиз и возвращает share-link."""
    log.info("=== Finishing quiz ===")
    # После последнего пояснения бот спрашивает "next or done?"
    reply = await client.wait_reply()
    assert_contains(reply.text, BOT_PROMPTS["ask_next_or_done"], "ask_next_or_done")

    if _has_button(reply, BTN_FINISH_QUIZ):
        await client.click(reply, text=BTN_FINISH_QUIZ)
    else:
        await client.send_text("/done")

    # Ждём финального сообщения со ссылкой
    final = await client.wait_reply()
    assert_contains(final.text, BOT_PROMPTS["finished"], "finished")

    link_match = SHARE_LINK_RE.search(final.text or "")
    if not link_match:
        raise UnexpectedBotState(
            f"No share link found in final message: {final.text!r}"
        )
    return link_match.group(0)


def _has_button(msg: Message, text: str) -> bool:
    if not msg.buttons:
        return False
    for row in msg.buttons:
        for btn in row:
            if btn.text and text.lower() in btn.text.lower():
                return True
    return False
