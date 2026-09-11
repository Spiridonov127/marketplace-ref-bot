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
from parsers.wb_parser import WildberriesParser
from parsers.ozon_parser import OzonParser
from parsers.aliexpress_parser import AliExpressParser
from parsers.ym_parser import YandexMarketParser

logger = logging.getLogger(__name__)


def create_parsers() -> dict:
    return {
        Marketplace.WB: WildberriesParser(affiliate_id=config.WB_AFFILIATE_ID),
        Marketplace.OZON: OzonParser(affiliate_id=config.OZON_AFFILIATE_ID),
        Marketplace.ALIEXPRESS: AliExpressParser(affiliate_id=config.ALIEXPRESS_AFFILIATE_ID),
        Marketplace.YANDEX_MARKET: YandexMarketParser(affiliate_id=config.YANDEX_MARKET_AFFILIATE_ID),
    }


def run_parse_cycle(db: Database) -> int:
    """Полный цикл парсинга всех маркетплейсов."""
    parsers = create_parsers()
    total_found = 0

    for mp, parser in parsers.items():
        logger.info(f"[Scheduler] Parsing {mp.display_name}...")
        try:
            deals = parser.parse_deals(
                min_discount=config.MIN_DISCOUNT_PERCENT,
                limit=config.MAX_PRODUCTS_PER_PARSE,
            )
            inserted = db.insert_products(deals)
            total_found += inserted
            logger.info(f"[Scheduler] {mp.display_name}: {inserted} new products")
        except Exception as e:
            logger.error(f"[Scheduler] {mp.display_name} error: {e}")

        try:
            popular = parser.parse_popular(limit=config.MAX_PRODUCTS_PER_PARSE // 2)
            inserted = db.insert_products(popular)
            total_found += inserted
            logger.info(f"[Scheduler] {mp.display_name} popular: {inserted} new products")
        except Exception as e:
            logger.error(f"[Scheduler] {mp.display_name} popular error: {e}")

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
