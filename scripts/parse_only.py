"""Скрипт: только парсинг (для GitHub Actions)."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from database import Database
from scheduler import run_parse_cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    os.makedirs("data", exist_ok=True)
    db = Database(config.DB_PATH)
    count = run_parse_cycle(db)
    print(f"Parsed {count} products")


if __name__ == "__main__":
    main()
