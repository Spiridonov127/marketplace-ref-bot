"""Планировщик: циклы парсинга, автопостинг, аналитика."""
import logging
import random
from datetime import datetime
from typing import Optional

import schedule
import telebot

from config import config
from database import Database
from models import Marketplace, Product
from content_generator import generate_post, generate_single_product_post

logger = logging.getLogger(__name__)


def run_parse_cycle(db: Database) -> int:
    """Полный цикл парсинга всех маркетплейсов."""
    from parsers.playwright_parsers import parse_all_playwright

    total_found = 0

    # Основной метод: Playwright (работает в GitHub Actions)
    logger.info("[Scheduler] Trying Playwright parsers...")
    try:
        products = parse_all_playwright(limit_per_mp=config.MAX_PRODUCTS_PER_PARSE)
        inserted = db.insert_products(products)
        total_found += inserted
        logger.info(f"[Scheduler] Playwright: {inserted} new products")
    except Exception as e:
        logger.error(f"[Scheduler] Playwright error: {e}")

    # Fallback: прямые API (могут не работать из-за антибот-защиты)
    if total_found < 10:
        logger.info("[Scheduler] Few products from Playwright, trying API fallback...")
        try:
            from parsers.wb_parser import WildberriesParser
            wb = WildberriesParser(affiliate_id=config.WB_AFFILIATE_ID)
            deals = wb.parse_deals(min_discount=config.MIN_DISCOUNT_PERCENT, limit=50)
            inserted = db.insert_products(deals)
            total_found += inserted
            logger.info(f"[Scheduler] WB API fallback: {inserted} products")
        except Exception as e:
            logger.warning(f"[Scheduler] WB API fallback error: {e}")

    logger.info(f"[Scheduler] Total found: {total_found}")
    return total_found


def run_post_cycle(db: Database, bot: telebot.TeleBot) -> bool:
    """Публикация одного поста в канал."""
    products = db.get_unposted_products(
        limit=config.MAX_PRODUCTS_PER_POST,
        min_discount=config.MIN_DISCOUNT_PERCENT,
    )

    if not products:
        logger.info("[Scheduler] No products to post")
        return False

    # Если 1 товар — подробный пост, иначе — подборка
    if len(products) == 1:
        post_text = generate_single_product_post(products[0])
    else:
        post_text = generate_post(products)

    try:
        sent = bot.send_message(
            config.TELEGRAM_CHANNEL_ID,
            post_text,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        db.mark_posted([p.id for p in products])
        db.record_post(
            config.TELEGRAM_CHANNEL_ID,
            sent.message_id,
            post_text,
            [p.id for p in products],
        )
        logger.info(f"[Scheduler] Posted {len(products)} products")
        return True
    except Exception as e:
        logger.error(f"[Scheduler] Post error: {e}")
        return False


def run_digest_cycle(db: Database, bot: telebot.TeleBot):
    """Публикация дайджеста с лучшими скидками по каждому маркетплейсу."""
    from content_generator import generate_digest_post

    top_by_mp = {}
    for mp in Marketplace:
        products = db.get_unposted_products(limit=1, min_discount=15)
        if products:
            top_by_mp[mp] = products

    if not top_by_mp:
        return False

    post_text = generate_digest_post(top_by_mp)
    try:
        bot.send_message(config.TELEGRAM_CHANNEL_ID, post_text, parse_mode="HTML")
        logger.info("[Scheduler] Digest posted")
        return True
    except Exception as e:
        logger.error(f"[Scheduler] Digest error: {e}")
        return False


def setup_schedule(db: Database, bot: telebot.TeleBot):
    """Настройка расписания автопилота."""
    # Парсинг: раз в 6 часов
    schedule.every(6).hours.do(run_parse_cycle, db=db)
    # Постинг: через равные интервалы
    schedule.every(config.POST_INTERVAL_HOURS).hours.do(run_post_cycle, db=db, bot=bot)
    # Дайджест: раз в день в 10:00
    schedule.every().day.at("10:00").do(run_digest_cycle, db=db, bot=bot)

    logger.info(
        f"[Scheduler] Schedule configured: parse every 6h, "
        f"post every {config.POST_INTERVAL_HOURS}h, "
        f"digest at 10:00"
    )


def run_scheduler():
    """Запуск цикла планировщика."""
    logger.info("[Scheduler] Running pending jobs...")
    schedule.run_pending()
