"""Точка входа: запуск бота + планировщика автопилота."""
import logging
import os
import threading
import time

from config import config
from database import Database
from bot import create_bot
from scheduler import setup_schedule, run_parse_cycle, run_post_cycle, run_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def ensure_dirs():
    os.makedirs("data", exist_ok=True)


def main():
    ensure_dirs()
    logger.info("=" * 50)
    logger.info("Marketplace Ref Bot starting...")
    logger.info("=" * 50)

    if not config.is_configured:
        logger.error(
            "Missing config! Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID "
            "in .env or environment variables."
        )
        return

    db = Database(config.DB_PATH)
    bot = create_bot(db)

    # Первый парсинг при старте
    logger.info("[Startup] Initial parse cycle...")
    try:
        count = run_parse_cycle(db)
        logger.info(f"[Startup] Parsed {count} products")
    except Exception as e:
        logger.error(f"[Startup] Parse error: {e}")

    # Настройка расписания
    setup_schedule(db, bot)

    # Поток планировщика
    def scheduler_loop():
        while True:
            try:
                run_scheduler()
            except Exception as e:
                logger.error(f"[Scheduler] Error: {e}")
            time.sleep(60)

    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()
    logger.info("[Startup] Scheduler thread started")

    # Запуск бота
    logger.info("[Startup] Bot polling started")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)


if __name__ == "__main__":
    main()
