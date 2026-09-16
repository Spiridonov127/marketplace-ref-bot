"""Точка входа: Яндекс Маркет → Яндекс Дзен.

По просьбе пользователя автоматических постов по расписанию больше нет —
никакого фонового парсинга/постинга/дайджеста. Единственный способ что-то
опубликовать — нажать /start в Telegram, ответить на вопрос "о чём хотите
написать" текстом с категорией, после чего бот сам ищет топ-5 на Яндекс
Маркете, генерирует статью и публикует в Дзен, а затем "отключается" до
следующего /start. Код планировщика
(scheduler.setup_schedule/run_scheduler/run_parse_cycle/run_dzen_post_cycle/
run_digest) не удалён и по-прежнему рабочий — на случай, если расписание
понадобится снова, — но здесь больше не запускается.
"""
import logging
import os
import time

from config import config
from database import Database

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
    os.makedirs("data/drafts", exist_ok=True)


def main():
    ensure_dirs()
    logger.info("=" * 50)
    logger.info("YM → Dzen Bot starting (только по /start, без расписания)...")
    logger.info("=" * 50)

    if not config.is_configured:
        logger.error(
            "Missing config! Set TELEGRAM_BOT_TOKEN or MAX_BOT_TOKEN, plus "
            "YANDEX_DISTRIBUTION_PARTNER_ID, in .env or environment variables."
        )
        return

    db = Database(config.DB_PATH)

    # MAX не блокируется с российских IP (в отличие от Telegram — см.
    # TELEGRAM_API_URL в config.py), поэтому на ВПС предпочитается он, если
    # настроен. Telegram остаётся рабочим вариантом (например, для запуска
    # на домашнем компьютере, где блокировки нет).
    if config.MAX_BOT_TOKEN:
        from bot.max_bot import create_bot
        platform_name = "MAX"
    else:
        from bot import create_bot
        platform_name = "Telegram"
    bot = create_bot(db)

    # Запуск бота — единственный источник задач теперь /start в Telegram,
    # никакого фонового парсинга/постинга/дайджеста по таймеру.
    #
    # bot.infinity_polling() у pyTelegramBotAPI в теории сам должен
    # переживать сетевые обрывы, но на практике при разрыве сети ("Network
    # is unreachable") он всё равно иногда полностью завершается с
    # исключением — после чего процесс main.py просто умирал, и бот переставал
    # отвечать на /start до тех пор, пока кто-то вручную не перезапустит
    # main.py. Оборачиваем вызов в свой собственный бесконечный цикл с
    # перезапуском, чтобы разовый сбой сети не убивал бота насовсем.
    logger.info(f"[Startup] Bot started ({platform_name})")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"[Startup] Опрос {platform_name} упал с ошибкой: {e}")
        else:
            logger.warning(f"[Startup] Опрос {platform_name} завершился без ошибки (неожиданно)")
        logger.info(f"[Startup] Перезапускаю опрос {platform_name} через 15 секунд...")
        time.sleep(15)


if __name__ == "__main__":
    main()
