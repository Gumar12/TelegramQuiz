"""Докачка квиза в @QuizBot с произвольного вопроса.

Используется, когда обычная заливка оборвалась на середине (например, Telegram
выдал «Too many incoming messages») и в боте уже остался черновик с частью
вопросов. Скрипт НЕ создаёт новый тест — он подхватывает существующий черновик
(бот ждёт следующий вопрос) и досылает только оставшиеся вопросы, затем
завершает квиз.

Перед запуском:
  • дождись, пока Telegram снимет анти-флуд лимит (15–60 мин), иначе оборвётся снова;
  • НЕ удаляй черновик в боте — скрипт дописывает именно в него.

Пример:
    # сначала безопасно проверить, что и с какого вопроса полетит:
    python resume_upload.py --file quizzes/my_quiz.json --start 74 --dry-run

    # реальная докачка с 74-го вопроса (медленный режим — рекомендуется):
    python resume_upload.py --file quizzes/my_quiz.json --start 74 --speed normal
"""
import argparse
import asyncio
import logging
import sys
import traceback

from backend import config
from backend.flow import (
    UnexpectedBotState,
    _context_key,
    finish_quiz,
    upload_question,
)
from backend.main import setup_logging
from backend.parser import load_json
from backend.validator import validate_all


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Resume an interrupted @QuizBot upload from a given question."
    )
    p.add_argument("--file", required=True, help="Path to questions.json")
    p.add_argument(
        "--start",
        required=True,
        type=int,
        help="1-based number of the FIRST not-yet-uploaded question (e.g. 74)",
    )
    p.add_argument(
        "--context-send-mode",
        choices=["once", "per-question"],
        default="once",
    )
    p.add_argument(
        "--no-shuffle-options",
        action="store_true",
        help="Keep answer options in input order instead of shuffling",
    )
    p.add_argument(
        "--no-finish",
        action="store_true",
        help="Do NOT send /done at the end (leave the draft open)",
    )
    p.add_argument(
        "--speed",
        choices=["normal", "fast"],
        default="normal",
        help="Pacing preset. Keep 'normal' to avoid the flood limit again.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print which questions would be sent; do not connect to Telegram",
    )
    p.add_argument("--debug", action="store_true", help="Verbose logging")
    return p.parse_args()


async def run(
    file_path: str,
    start: int,
    *,
    context_send_mode: str = "once",
    shuffle_options: bool = True,
    finish: bool = True,
    speed: str = "normal",
) -> int:
    log = logging.getLogger("resume")
    config.apply_speed_mode(speed)
    log.info("Speed mode: %s", speed)

    questions = load_json(file_path)
    validate_all(questions)
    total = len(questions)

    if start < 1 or start > total:
        log.error("--start %d out of range (file has %d questions)", start, total)
        return 1

    remaining = questions[start - 1:]
    log.info(
        "Loaded %d questions; resuming from #%d → sending %d remaining",
        total, start, len(remaining),
    )

    config.assert_credentials()
    log.info("Connecting to Telegram as %s …", config.PHONE)

    # Импорт здесь, чтобы --dry-run не требовал telethon-сессии.
    from backend.quizbot_client import QuizBotClient

    async with QuizBotClient() as client:
        try:
            # ВАЖНО: create_quiz НЕ вызываем — черновик уже существует и бот
            # ждёт следующий вопрос. Сразу досылаем оставшиеся.
            #
            # Чтобы не дублировать пролог (контекст/медиа), если у вопроса #start
            # тот же контекст, что у предыдущего, — инициализируем last_context_key
            # значением предыдущего вопроса.
            last_context_key = (
                _context_key(questions[start - 2]) if start > 1 else None
            )

            for offset, question in enumerate(remaining):
                index = start + offset  # абсолютный номер вопроса в квизе

                context_key = _context_key(question)
                send_prelude = True
                if context_send_mode == "once":
                    send_prelude = (
                        context_key is not None and context_key != last_context_key
                    )
                    last_context_key = context_key

                await upload_question(
                    client,
                    question,
                    index_in_quiz=index,
                    send_prelude=send_prelude,
                    shuffle_options=shuffle_options,
                )
                log.info("Uploaded question %d/%d", index, total)

            if finish:
                share_link = await finish_quiz(client)
                log.info("=" * 60)
                log.info("✅ Resume complete: questions %d–%d uploaded", start, total)
                log.info("🔗 Share link: %s", share_link)
                log.info("=" * 60)
            else:
                log.info("Remaining questions sent; draft left open (--no-finish).")
        except UnexpectedBotState as e:
            log.error("Bot state mismatch: %s", e)
            log.error(
                "Бот ответил не тем, что ожидалось. Возможно, снова анти-флуд "
                "лимит или черновик в другом состоянии. Подожди и повтори "
                "с того вопроса, на котором оборвалось."
            )
            return 2
        except asyncio.TimeoutError:
            log.error("Timed out waiting for @QuizBot reply (>%.0fs)", config.WAIT_REPLY_TIMEOUT)
            return 3

    return 0


def main() -> None:
    args = parse_args()
    setup_logging(args.debug)
    log = logging.getLogger("resume")

    if args.dry_run:
        questions = load_json(args.file)
        validate_all(questions)
        total = len(questions)
        if args.start < 1 or args.start > total:
            print(f"ERROR: --start {args.start} out of range (file has {total})", file=sys.stderr)
            sys.exit(1)
        remaining = questions[args.start - 1:]
        print(f"[dry-run] Файл: {args.file}")
        print(f"[dry-run] Всего вопросов: {total}")
        print(f"[dry-run] Докачка с #{args.start} → отправится {len(remaining)} вопрос(ов):")
        for offset, q in enumerate(remaining[:5]):
            print(f"  #{args.start + offset}: {q.question[:70]}")
        if len(remaining) > 5:
            print(f"  … и ещё {len(remaining) - 5}")
        print(f"[dry-run] Последний: #{total}: {remaining[-1].question[:70]}")
        print("[dry-run] Реальная отправка НЕ выполнялась.")
        sys.exit(0)

    try:
        exit_code = asyncio.run(
            run(
                args.file,
                args.start,
                context_send_mode=args.context_send_mode,
                shuffle_options=not args.no_shuffle_options,
                finish=not args.no_finish,
                speed=args.speed,
            )
        )
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        exit_code = 130
    except Exception:
        traceback.print_exc()
        exit_code = 99
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
