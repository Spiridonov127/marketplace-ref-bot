"""Планировщик: Яндекс Маркет → Яндекс Дзен."""
import html
import logging
import re
import time

import telebot
import schedule

from config import config
from database import Database
from models import Marketplace, Product
from content_generator import (
    generate_dzen_article,
    generate_dzen_post_text,
    generate_single_product_article,
)
from referral_builder import build_ym_cpa_link, add_erid_to_url
from distribution_erid import get_marked_link

logger = logging.getLogger(__name__)

# Слова, по которым запрос пользователя считается просьбой собрать ПОДБОРКУ
# (топ с ценами, рейтингами, плюсами и минусами из отзывов). Всё остальное —
# например просто "шапка" — это просьба написать обычную статью про предмет,
# без отзывов и оценок.
_TOP_WORDS_RE = re.compile(
    # топ\d* — чтобы сработало и "топ-5", и слитное "топ10".
    r"(^|\W)(топ\d*|подборк\w*|лучш\w+|рейтинг\w*|сравн\w+|собер\w+|подбер\w+)(\W|$)",
    re.IGNORECASE,
)

# "топ-5", "топ 3", "топ10" — сколько товаров брать в подборку.
_TOP_N_RE = re.compile(r"топ[\s\-–—]*(\d{1,2})", re.IGNORECASE)

# Служебные слова, которые нужны для понимания задачи, но мешают поиску на
# Яндекс Маркете: искать там буквально "собери топ-5 наушников" — значит не
# найти ничего. Вырезаем их и ищем по тому, что осталось ("наушников").
_QUERY_NOISE_RE = re.compile(
    r"(^|\W)(топ[\s\-–—]*\d*|подборк\w*|лучш\w+|рейтинг\w*|сравн\w+|собер\w+|"
    r"подбер\w+|сделай|составь|напиши|создай|статью|статья|пост|про|об|о)(\W|$)",
    re.IGNORECASE,
)


def wants_top_selection(query: str) -> bool:
    """Просил ли пользователь именно подборку, а не статью про один предмет."""
    return bool(_TOP_WORDS_RE.search(query or ""))


def extract_top_n(query: str, default: int = 5) -> int:
    """Сколько товаров в подборке: из "топ-5" берём 5, иначе значение по
    умолчанию. Ограничиваем сверху, чтобы "топ-100" не превратился в статью
    на сто позиций и час работы Playwright."""
    m = _TOP_N_RE.search(query or "")
    if m:
        return max(2, min(int(m.group(1)), 10))
    return default


def clean_search_query(query: str) -> str:
    """Оставляет от запроса только то, что имеет смысл искать на Маркете."""
    q = query or ""
    prev = None
    # Несколько проходов: соседние служебные слова делят общий разделитель,
    # и за один проход регулярка съедает только через одно ("напиши статью
    # про шапку" -> "статью шапку" -> "шапку").
    while prev != q:
        prev = q
        q = _QUERY_NOISE_RE.sub(" ", q)
    q = re.sub(r"\s+", " ", q).strip(" \t\n-–—,.:;!?")
    return q or (query or "").strip()


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


# Сколько раз повторять каждый этап, прежде чем сдаться. Разные этапы
# ломаются по-разному, поэтому и повторов у них разное количество:
#
#  - поиск на Маркете: Playwright иногда возвращает пустой список из-за
#    таймаута или не прогрузившейся страницы, и отличить это от честного
#    "ничего не нашлось" изнутри нельзя — поэтому один повтор оправдан;
#  - erid: КАЖДЫЙ УСПЕШНЫЙ вызов кабинета Дистрибуции регистрирует новый
#    рекламный креатив в ОРД (см. distribution_erid). Повторяем только после
#    неудачи (когда регистрации, как правило, не произошло) и максимально
#    скупо, чтобы не наплодить лишних регистраций;
#  - публикация в Дзен: самый капризный этап (модалка, сеть, ре-рендеры
#    редактора) и при этом полностью безвредный для повтора — статья с уже
#    полученным erid просто отправляется заново, новый erid не запрашивается.
_SEARCH_ATTEMPTS = 2
_ERID_ATTEMPTS = 2
_POST_ATTEMPTS = 3
_RETRY_PAUSE_SECONDS = 10


def _search_with_retries(search_query: str, limit: int) -> list:
    from parsers.playwright_parsers import parse_ym_search_playwright

    for attempt in range(1, _SEARCH_ATTEMPTS + 1):
        try:
            found = parse_ym_search_playwright(search_query, limit=limit)
        except Exception as e:
            logger.warning(
                f"[Scheduler] Поиск «{search_query}» упал "
                f"(попытка {attempt}/{_SEARCH_ATTEMPTS}): {e}"
            )
            found = None
        if found:
            return found
        if attempt < _SEARCH_ATTEMPTS:
            logger.info(
                f"[Scheduler] По «{search_query}» пусто — повтор через "
                f"{_RETRY_PAUSE_SECONDS} с"
            )
            time.sleep(_RETRY_PAUSE_SECONDS)
    return []


def _publish_with_retries(
    db: Database, products: list, title: str, body_html: str
) -> tuple:
    """Маркировка + публикация с повторами. Возвращает (успех, причина).

    Причина — короткий человеческий текст для сообщения в Telegram: раньше
    бот на любую неудачу отвечал одинаковым "либо не нашлось, либо erid, либо
    Дзен", и понять, что чинить, было нельзя.
    """
    from dzen_poster import post_to_dzen

    marked_body = None
    for attempt in range(1, _ERID_ATTEMPTS + 1):
        # При неудаче _apply_ad_marking ничего не меняет ни в products, ни в
        # body_html (выходит раньше мутаций), поэтому повтор безопасен и
        # каждый раз стартует с исходного текста статьи.
        marked_body = _apply_ad_marking(products, title, body_html)
        if marked_body:
            break
        logger.warning(
            f"[Scheduler] erid не получен (попытка {attempt}/{_ERID_ATTEMPTS})"
        )
        if attempt < _ERID_ATTEMPTS:
            time.sleep(_RETRY_PAUSE_SECONDS)

    if not marked_body:
        return False, (
            "не удалось получить erid в кабинете Яндекс Дистрибуции — "
            "публиковать рекламу без маркировки запрещено законом, поэтому "
            "пост отменён. Обычно причина в протухших куках Дистрибуции"
        )

    for attempt in range(1, _POST_ATTEMPTS + 1):
        if post_to_dzen(title, marked_body):
            posted_ids = [p.id for p in products if p.id]
            if posted_ids:
                db.mark_posted(posted_ids)
            if attempt > 1:
                logger.info(f"[Scheduler] Опубликовано с {attempt}-й попытки")
            return True, ""
        logger.warning(
            f"[Scheduler] Дзен не принял статью "
            f"(попытка {attempt}/{_POST_ATTEMPTS})"
        )
        if attempt < _POST_ATTEMPTS:
            time.sleep(_RETRY_PAUSE_SECONDS)

    return False, (
        f"Дзен не принял статью после {_POST_ATTEMPTS} попыток. "
        f"erid при этом получен, так что дело в самой публикации — "
        f"чаще всего в протухших куках Дзена"
    )


def run_category_post_cycle(db: Database, query: str, top_n: int = 5) -> tuple:
    """По произвольному запросу/категории от пользователя (например, из
    Telegram) ищет товары на Яндекс Маркете, берёт топ-N по популярности
    (рейтинг → число отзывов → скидка), генерирует статью и публикует её в
    Дзен с обязательной маркировкой рекламы (erid).

    Полный аналог run_dzen_post_cycle, но источник товаров — не очередь
    неопубликованных из БД, а свежий поиск по тексту query прямо сейчас.
    """
    query = (query or "").strip()
    if not query:
        return False, "пустой запрос"

    search_query = clean_search_query(query)
    logger.info(f"[Scheduler] Поиск подборки по запросу «{query}» (ищу: «{search_query}»)...")
    found = _search_with_retries(
        search_query, limit=max(config.MAX_PRODUCTS_PER_PARSE, top_n)
    )
    if not found:
        logger.warning(f"[Scheduler] По запросу «{search_query}» ничего не найдено")
        return False, (
            f"на Яндекс Маркете ничего не нашлось по запросу «{search_query}» "
            f"(проверено {_SEARCH_ATTEMPTS} раза). Попробуйте другую "
            f"формулировку"
        )

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

    # Обязательная по закону маркировка рекламы (erid) и сама публикация —
    # оба этапа с повторами, см. _publish_with_retries.
    ok, reason = _publish_with_retries(db, top, title, body_html)
    if ok:
        logger.info(f"[Scheduler] Опубликовано по запросу «{query}»: {len(top)} товаров")
        return True, ""

    logger.warning(f"[Scheduler] Подборка по запросу «{query}» не опубликована: {reason}")
    return False, reason


def run_single_product_post_cycle(db: Database, query: str) -> tuple:
    """Обычный запрос ("шапка", "напиши про кофемашину") — статья-обзор об
    ОДНОМ товаре: живой текст, фото, ссылка. Без отзывов покупателей, без
    рейтингов и без списков плюсов/минусов — они показываются только в режиме
    подборки (run_category_post_cycle), когда пользователь прямо об этом
    просит.

    Маркировка рекламы (erid) обязательна точно так же, как в подборке: без
    неё публикация отменяется.
    """
    query = (query or "").strip()
    if not query:
        return False, "пустой запрос"

    search_query = clean_search_query(query)
    logger.info(f"[Scheduler] Статья по запросу «{query}» (ищу: «{search_query}»)...")
    found = _search_with_retries(
        search_query, limit=max(config.MAX_PRODUCTS_PER_PARSE, 10)
    )
    if not found:
        logger.warning(f"[Scheduler] По запросу «{search_query}» ничего не найдено")
        return False, (
            f"на Яндекс Маркете ничего не нашлось по запросу «{search_query}» "
            f"(проверено {_SEARCH_ATTEMPTS} раза). Попробуйте другую "
            f"формулировку"
        )

    # Берём один самый "надёжный" товар: рейтинг → число отзывов → скидка.
    # Сами отзывы в статью не попадут, но как признак того, что товар живой и
    # не случайный, рейтинг здесь по-прежнему полезен.
    found.sort(key=lambda p: (p.rating, p.reviews_count, p.discount_percent), reverse=True)
    product = found[0]

    ids = db.insert_products_return_ids([product])
    if ids and ids[0]:
        product.id = ids[0]

    product.referral_url = build_ym_cpa_link(product.url)

    title, body_html = generate_single_product_article(product, topic=search_query)
    if not title or not body_html:
        logger.error(f"[Scheduler] Не удалось собрать статью по запросу «{query}»")
        return False, "не удалось собрать текст статьи"

    ok, reason = _publish_with_retries(db, [product], title, body_html)
    if ok:
        logger.info(f"[Scheduler] Опубликована статья по запросу «{query}»")
        return True, ""

    logger.warning(f"[Scheduler] Статья по запросу «{query}» не опубликована: {reason}")
    return False, reason


def run_post_cycle_for_query(db: Database, query: str) -> tuple:
    """Единая точка входа для запроса пользователя из Telegram.

    Сама решает, что именно он попросил: подборку (топ с ценами, рейтингами,
    плюсами и минусами из реальных отзывов) или обычную статью про предмет.
    Используется и локальным ботом, и облачным запуском в GitHub Actions
    (scripts/run_dispatch_query.py), чтобы поведение в обоих случаях было
    гарантированно одинаковым.
    """
    if wants_top_selection(query):
        top_n = extract_top_n(query)
        logger.info(f"[Scheduler] Режим подборки (топ-{top_n}) для запроса «{query}»")
        return run_category_post_cycle(db, query, top_n=top_n)

    logger.info(f"[Scheduler] Режим статьи об одном товаре для запроса «{query}»")
    return run_single_product_post_cycle(db, query)


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
