"""Скрипт: только постинг в Дзен (для GitHub Actions)."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from database import Database
from scheduler import run_dzen_post_cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    if not config.YANDEX_DISTRIBUTION_PARTNER_ID:
        print("Missing YANDEX_DISTRIBUTION_PARTNER_ID — CPA links will be plain URLs")

    os.makedirs("data", exist_ok=True)
    db = Database(config.DB_PATH)
    success = run_dzen_post_cycle(db)
    print(f"Post {'succeeded' if success else 'skipped (no products or Dzen auth missing)'}")


if __name__ == "__main__":
    main()
