"""Скрипт: только постинг (для GitHub Actions)."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from database import Database
from bot import create_bot
from scheduler import run_post_cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    if not config.is_configured:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID")
        sys.exit(1)

    os.makedirs("data", exist_ok=True)
    db = Database(config.DB_PATH)
    bot = create_bot(db)
    success = run_post_cycle(db, bot)
    print(f"Post {'succeeded' if success else 'skipped (no products)'}")


if __name__ == "__main__":
    main()
