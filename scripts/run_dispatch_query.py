"""Точка входа для GitHub Actions: обрабатывает ОДИН запрос пользователя,
пришедший из Telegram, когда компьютер пользователя выключен.

Раньше эту работу делал только Telegram-бот (bot/_run_category_post),
которому для этого нужно было постоянно работать на чьём-то компьютере.
Теперь вместо компьютера Telegram слушает облачный релей (Cloudflare
Worker) — как только пользователь после /start присылает боту категорию,
релей запускает этот workflow через GitHub API (repository_dispatch),
передавая текст запроса и chat_id в client_payload события. GitHub Actions
сам всё выполняет в облаке и сам же отчитывается в Telegram о результате —
компьютер пользователя для этого совершенно не нужен.

Переменные окружения (заполняются из client_payload в .github/workflows/
telegram_query.yml):
  QUERY    — что искать на Яндекс Маркете (категория/запрос от пользователя)
  CHAT_ID  — id чата в Telegram, куда отправить финальный результат
"""
import logging
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

_OFF_NOTICE = "Бот отключился — когда понадобится снова, нажмите /start."


def _send_telegram(chat_id: str, text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token or not chat_id:
        logger.error(
            "Нет TELEGRAM_BOT_TOKEN или chat_id — не могу отправить результат в Telegram"
        )
        return
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if not resp.ok:
            logger.error(f"Telegram sendMessage вернул {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в Telegram: {e}")


def main():
    query = os.getenv("QUERY", "").strip()
    chat_id = os.getenv("CHAT_ID", "").strip()

    logger.info(f"[Dispatch] query={query!r} chat_id={chat_id!r}")

    if not query:
        logger.error("QUERY пуст — нечего искать")
        if chat_id:
            _send_telegram(chat_id, f"❌ Пустой запрос.\n\n{_OFF_NOTICE}")
        return

    from config import config
    from database import Database
    from scheduler import run_category_post_cycle

    if not config.YANDEX_DISTRIBUTION_PARTNER_ID:
        logger.warning("YANDEX_DISTRIBUTION_PARTNER_ID не задан — CPA-ссылки будут обычными URL")

    os.makedirs("data", exist_ok=True)
    db = Database(config.DB_PATH)

    try:
        success = run_category_post_cycle(db, query, top_n=5)
    except Exception as e:
        logger.error(f"[Dispatch] Ошибка при обработке запроса {query!r}: {e}")
        _send_telegram(chat_id, f"❌ Ошибка: {e}\n\n{_OFF_NOTICE}")
        raise

    if success:
        _send_telegram(
            chat_id,
            f"✅ Статья по запросу «{query}» опубликована в Дзен "
            f"(с маркировкой рекламы erid)!\n\n{_OFF_NOTICE}",
        )
    else:
        _send_telegram(
            chat_id,
            f"⚠️ Не получилось опубликовать по запросу «{query}»: "
            f"либо ничего не нашлось на Яндекс Маркете, либо не удалось "
            f"получить erid через ОРД, либо ошибка публикации в Дзен. "
            f"Подробности — в логе запуска workflow на GitHub.\n\n{_OFF_NOTICE}",
        )


if __name__ == "__main__":
    main()
