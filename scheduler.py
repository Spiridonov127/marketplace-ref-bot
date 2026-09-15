"""Планировщик: Яндекс Маркет → Яндекс Дзен."""
import html
import logging
import telebot
import schedule

from config import config
from database import Database
from models import Marketplace, Product
from content_generator import generate_dzen_article, generate_dzen_post_text
from referral_builder import build_ym_cpa_link, add_erid_to_url
from distribution_erid import get_marked_link

logger = logging.getLogger(__name__)


def _apply_ad_marking(products: list, title: str, body_html: str):
    """Регистрирует пост как один рекламный креатив в ОРД Яндекса, получает
    erid, вписывает его во все ссылки на товары внутри body_html и
    добавляет официальные метку + дисклеймер в футер.

    По закону (см. обсуждение при внедрении) один креатив = один erid,
    который затем дублируется в каждую ссылку на рекламируемый ресурс — а
    не отдельная регистрация на каждый товар. Если зарегистрировать
    креатив не удалось (нет cookies Дистрибуции, не авторизован и т.п.) —
    возвращает None: публикация БЕЗ маркировки запрещена законом, поэтому
    вызывающий код должен в этом случае отменить пост, а не публиковать
    как есть.
    """
    if not products:
        return None

    marked = get_marked_link(products[0].referral_url, creative_text=title)
    if not marked or not marked.get("erid"):
        logger.error(
            "[Scheduler] Не удалось получить erid через ОРД Яндекса — "
            "публикация без маркировки рекламы запрещена законом, отменяю"
        )
        return None

    erid = marked["erid"]
    for p in products:
        old_url = p.referral_url
        new_url = add_erid_to_url(old_url, erid)
        body_html = body_html.replace(old_url, new_url)
        p.referral_url = new_url

    if marked.get("label"):
        body_html += f"\n<p>{html.escape(marked['label'])}</p>"
    if marked.get("disclaimer"):
        body_html += f"\n<p>{html.escape(marked['disclaimer'])}</p>"

    return body_html


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

    # Реальные отзывы покупателей — нужны, чтобы "Минусы" в статье были
    # настоящими словами покупателей, а не выдумкой (см. reviews_extractor.py).
    from reviews_extractor import get_reviews_for_products
    reviews_by_product = get_reviews_for_products(products)

    # Генерируем статью для Дзена
    title, body_html = generate_dzen_article(products, reviews_by_product)

    # Обязательная по закону маркировка рекламы (erid) — публикация без
    # неё отменяется, см. _apply_ad_marking.
    marked_body_html = _apply_ad_marking(products, title, body_html)
    if marked_body_html is None:
        return False
    body_html = marked_body_html

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


def run_category_post_cycle(db: Database, query: str, top_n: int = 5) -> bool:
    """По произвольному запросу/категории от пользователя (например, из
    Telegram) ищет товары на Яндекс Маркете, берёт топ-N по популярности
    (рейтинг → число отзывов → скидка), генерирует статью и публикует её в
    Дзен с обязательной маркировкой рекламы (erid).

    Полный аналог run_dzen_post_cycle, но источник товаров — не очередь
    неопубликованных из БД, а свежий поиск по тексту query прямо сейчас.
    """
    from dzen_poster import post_to_dzen
    from parsers.playwright_parsers import parse_ym_search_playwright

    query = (query or "").strip()
    if not query:
        return False

    logger.info(f"[Scheduler] Поиск по запросу «{query}»...")
    found = parse_ym_search_playwright(query, limit=max(config.MAX_PRODUCTS_PER_PARSE, top_n))
    if not found:
        logger.warning(f"[Scheduler] По запросу «{query}» ничего не найдено")
        return False

    # "Популярное" — сортируем по рейтингу и числу отзывов, скидка вторична
    # (в отличие от run_dzen_post_cycle/run_digest, где во главе угла скидка).
    found.sort(key=lambda p: (p.rating, p.reviews_count, p.discount_percent), reverse=True)
    top = found[:top_n]

    ids = db.insert_products_return_ids(top)
    for p, pid in zip(top, ids):
        if pid:
            p.id = pid

    for p in top:
        p.referral_url = build_ym_cpa_link(p.url)

    from reviews_extractor import get_reviews_for_products
    reviews_by_product = get_reviews_for_products(top)

    title, body_html = generate_dzen_article(top, reviews_by_product)

    # Обязательная по закону маркировка рекламы (erid) — публикация без неё
    # отменяется, см. _apply_ad_marking.
    marked_body_html = _apply_ad_marking(top, title, body_html)
    if marked_body_html is None:
        logger.error(f"[Scheduler] Публикация по запросу «{query}» отменена — не удалось получить erid")
        return False
    body_html = marked_body_html

    success = post_to_dzen(title, body_html)

    if success:
        posted_ids = [p.id for p in top if p.id]
        if posted_ids:
            db.mark_posted(posted_ids)
        logger.info(f"[Scheduler] Опубликовано по запросу «{query}»: {len(top)} товаров")
        return True

    logger.warning(f"[Scheduler] Публикация по запросу «{query}» не удалась (ошибка Дзена)")
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

    from reviews_extractor import get_reviews_for_products
    reviews_by_product = get_reviews_for_products(products[:3])

    title, body_html = generate_dzen_article(products[:3], reviews_by_product)

    marked_body_html = _apply_ad_marking(products[:3], title, body_html)
    if marked_body_html is None:
        return False
    body_html = marked_body_html

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
