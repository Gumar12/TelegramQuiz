"""CLI entry point.

Usage:
    python main.py --file questions.json --name "My Quiz" [--debug]
"""
import argparse
import asyncio
import logging
import sys
import traceback

import config
from flow import UnexpectedBotState, create_quiz, finish_quiz, upload_question
from parser import load_json
from quizbot_client import QuizBotClient
from validator import validate_all


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("quizbot_uploader.log", encoding="utf-8"),
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
    p.add_argument("--debug", action="store_true", help="Verbose logging")
    return p.parse_args()


async def run(file_path: str, quiz_name: str) -> int:
    log = logging.getLogger("main")
    log.info("Loading questions from %s", file_path)
    questions = load_json(file_path)
    validate_all(questions)
    log.info("Loaded and validated %d questions", len(questions))

    config.assert_credentials()
    log.info("Connecting to Telegram as %s …", config.PHONE)
    async with QuizBotClient() as client:
        try:
            await create_quiz(client, quiz_name)
            for i, q in enumerate(questions, start=1):
                await upload_question(client, q, index_in_quiz=i)
            share_link = await finish_quiz(client)
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
        exit_code = asyncio.run(run(args.file, args.name))
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
