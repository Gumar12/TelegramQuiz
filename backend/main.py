"""CLI entry point.

Usage:
    python -m backend.main --file data/quizzes/example.json --name "My Quiz" [--debug]
"""
import argparse
import asyncio
import logging
import sys
import traceback
from typing import Callable

from backend import config
from backend.flow import UnexpectedBotState, create_quiz, finish_quiz, upload_questions
from backend.parser import load_json
from backend.quizbot_client import QuizBotClient
from backend.validator import validate_all


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        ],
    )
    # Telethon очень болтлив на DEBUG — приглушаем
    if not debug:
        logging.getLogger("telethon").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Upload a quiz to @QuizBot from a JSON file."
    )
    p.add_argument("--file", required=True, help="Path to questions.json")
    p.add_argument("--name", required=True, help="Quiz name shown in @QuizBot")
    p.add_argument(
        "--context-send-mode",
        choices=["once", "per-question"],
        default="once",
        help="How to send identical consecutive context/media; default: once",
    )
    p.add_argument(
        "--no-shuffle-options",
        action="store_true",
        help="Keep answer options in input order instead of shuffling before upload",
    )
    p.add_argument(
        "--speed",
        choices=["normal", "fast"],
        default="normal",
        help="Upload pacing preset. Use fast for demo/video runs.",
    )
    p.add_argument("--debug", action="store_true", help="Verbose logging")
    return p.parse_args()


async def run(
    file_path: str,
    quiz_name: str,
    context_send_mode: str = "once",
    shuffle_options: bool = True,
    speed: str = "normal",
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> int:
    log = logging.getLogger("main")
    config.apply_speed_mode(speed)
    log.info("Speed mode: %s", speed)
    log.info("Loading questions from %s", file_path)
    questions = load_json(file_path)
    validate_all(questions)
    log.info("Loaded and validated %d questions", len(questions))
    if progress_callback:
        progress_callback("loaded", 0, len(questions), f"Loaded {len(questions)} questions")
    if cancel_check:
        cancel_check()

    config.assert_credentials()
    log.info("Connecting to Telegram as %s …", config.PHONE)
    async with QuizBotClient() as client:
        try:
            if progress_callback:
                progress_callback("creating", 0, len(questions), "Creating quiz draft in @QuizBot")
            if cancel_check:
                cancel_check()
            await create_quiz(client, quiz_name)
            if progress_callback:
                progress_callback("uploading", 0, len(questions), "Quiz draft created, uploading questions")
            if cancel_check:
                cancel_check()
            await upload_questions(
                client,
                questions,
                context_send_mode=context_send_mode,
                shuffle_options=shuffle_options,
                progress_callback=lambda done, total, question: progress_callback(
                    "uploading",
                    done,
                    total,
                    f"Uploaded question {done}/{total}: {question.question[:60]}",
                ) if progress_callback else None,
                cancel_check=cancel_check,
            )
            if progress_callback:
                progress_callback("finishing", len(questions), len(questions), "Finishing quiz in @QuizBot")
            if cancel_check:
                cancel_check()
            share_link = await finish_quiz(client)
            if progress_callback:
                progress_callback("completed", len(questions), len(questions), f"Quiz uploaded: {share_link}")
        except UnexpectedBotState as e:
            log.error("Bot state mismatch: %s", e)
            log.error("Last steps logged above. Delete the draft quiz in @QuizBot and retry.")
            return 2
        except asyncio.TimeoutError:
            log.error("Timed out waiting for @QuizBot reply (>%.0fs)",
                      config.WAIT_REPLY_TIMEOUT)
            log.error("Bot did not respond. Possible causes: network, anti-spam throttle, bot changed.")
            return 3

    log.info("=" * 60)
    log.info("✅ Quiz uploaded: %d questions", len(questions))
    log.info("🔗 Share link: %s", share_link)
    log.info("=" * 60)
    return 0


def main() -> None:
    args = parse_args()
    setup_logging(args.debug)
    try:
        exit_code = asyncio.run(
            run(
                args.file,
                args.name,
                args.context_send_mode,
                not args.no_shuffle_options,
                args.speed,
            )
        )
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        # Validation / config errors — без traceback'а, понятное сообщение
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
