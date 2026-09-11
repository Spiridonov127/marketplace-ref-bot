"""Планировщик: Яндекс Маркет → Яндекс Дзен."""
import logging
import telebot
import schedule

from config import config
from database import Database
from models import Marketplace, Product
from content_generator import generate_dzen_article, generate_dzen_post_text
from referral_builder import build_ym_cpa_link

logger = logging.getLogger(__name__)


def run_parse_cycle(db: Database) -> int:
    """Парсинг Яндекс Маркета."""
    from parsers.playwright_parsers import parse_ym_playwright

    total_found = 0
    logger.info("[Scheduler] Parsing Yandex Market...")

    try:
        products = parse_ym_playwright(limit=config.MAX_PRODUCTS_PER_PARSE)
        inserted = db.insert_products(products)
        total_found += inserted
        logger.info(f"[Scheduler] YM: {inserted} products")
    except Exception as e:
        logger.error(f"[Scheduler] YM error: {e}")

    logger.info(f"[Scheduler] Total: {total_found}")
    return total_found


def run_dzen_post_cycle(db: Database) -> bool:
    """Генерация и публикация статьи в Дзен."""
    from dzen_poster import post_to_dzen

    products = db.get_unposted_products(
        limit=config.MAX_PRODUCTS_PER_POST,
        min_discount=config.MIN_DISCOUNT_PERCENT,
    )

    if not products:
        logger.info("[Scheduler] No products to post")
        return False

    # Обновляем CPA-ссылки
    for p in products:
        p.referral_url = build_ym_cpa_link(p.url)

    # Генерируем статью для Дзена
    title, body_html = generate_dzen_article(products)

    # Публикуем в Дзен
    success = post_to_dzen(title, body_html)

    if success:
        from database import Database as DB
        db.mark_posted([p.id for p in products])
        logger.info(f"[Scheduler] Posted to Dzen: {len(products)} products")
        return True
    else:
        # Если автопостинг не удался, сохраняем текст для ручной публикации
        post_text = generate_dzen_post_text(products)
        _save_draft(title, body_html, post_text)
        logger.warning("[Scheduler] Dzen auto-post failed, draft saved")
        return False


def _save_draft(title: str, body_html: str, text: str):
    """Сохраняет черновик для ручной публикации."""
    import os
    from datetime import datetime

    draft_dir = "data/drafts"
    os.makedirs(draft_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(draft_dir, f"draft_{timestamp}.md")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"## HTML (для Дзена)\n\n{body_html}\n\n")
        f.write(f"## Текст (для копирования)\n\n{text}\n\n")
        f.write(f"---\nСоздано: {datetime.now().isoformat()}\n")

    logger.info(f"[Scheduler] Draft saved: {filepath}")


def run_digest(db: Database) -> bool:
    """Дайджест лучших скидок."""
    from dzen_poster import post_to_dzen

    products = db.get_unposted_products(limit=5, min_discount=25)
    if not products:
        return False

    for p in products:
        p.referral_url = build_ym_cpa_link(p.url)

    title, body_html = generate_dzen_article(products[:3])
    success = post_to_dzen(title, body_html)

    if success:
        db.mark_posted([p.id for p in products[:3]])
        return True
    return False


def setup_schedule(db: Database, bot: telebot.TeleBot = None):
    """Настройка расписания."""
    schedule.every(6).hours.do(run_parse_cycle, db=db)
    schedule.every(config.POST_INTERVAL_HOURS).hours.do(run_dzen_post_cycle, db=db)
    schedule.every().day.at("10:00").do(run_digest, db=db)

    logger.info(
        f"[Scheduler] YM → Dzen schedule: parse 6h, post {config.POST_INTERVAL_HOURS}h, digest 10:00"
    )


def run_scheduler():
    schedule.run_pending()
