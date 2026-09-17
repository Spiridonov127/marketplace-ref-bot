"""Извлечение РЕАЛЬНЫХ отзывов покупателей со страницы товара Яндекс
Маркета — чтобы "плюсы"/"минусы" в статье были настоящими словами
покупателей, а не выдумкой модели.

Формат страницы отзывов Маркета — недокументированный и может отличаться от
товара к товару. То, что здесь разобрано, основано на реальном дампе
страницы (см. debug_ym_reviews.py): каждый отзыв на странице идёт в порядке
[Достоинства: ...] [Недостатки: ...] [Комментарий: ...] Автор Дата — поля
могут отсутствовать (не каждый покупатель заполняет "Недостатки").

Принцип: если у товара реально нет ни одного заполненного покупателями
"Недостатки" — get_reviews_for_products() честно вернёт для него пустой
список отзывов с cons, а вызывающий код должен просто не показывать блок
"Минусы", а не подставлять придуманную фразу. Это ожидаемое и нормальное
состояние для товаров, где все отзывы положительные.
"""
import logging
import re

from config import config

logger = logging.getLogger(__name__)

_MONTHS_RE = re.compile(
    r"^\d{1,2}\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|"
    r"октябр|ноябр|декабр)",
    re.IGNORECASE,
)


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def _create_context(p):
    browser = p.chromium.launch(
        headless=True,
        proxy={"server": config.YM_PROXY_URL} if config.YM_PROXY_URL else None,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        locale="ru-RU",
        viewport={"width": 1920, "height": 1080},
        timezone_id="Europe/Moscow",
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en'] });
        window.chrome = { runtime: {} };
    """)
    from parsers.playwright_parsers import _load_market_cookies
    _load_market_cookies(context)
    return browser, context


def _parse_reviews_from_text(body_text: str) -> list[dict]:
    """Разбирает текст страницы на отдельные отзывы. Эвристика по реально
    наблюдаемому порядку полей — см. docstring модуля.
    """
    lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
    reviews: list[dict] = []
    current: dict = {}

    for ln in lines:
        if ln.startswith("Достоинства:"):
            current["pros"] = ln[len("Достоинства:"):].strip()
        elif ln.startswith("Недостатки:"):
            current["cons"] = ln[len("Недостатки:"):].strip()
        elif ln.startswith("Комментарий:"):
            current["comment"] = ln[len("Комментарий:"):].strip()
        elif _MONTHS_RE.match(ln):
            # Строка с датой отзыва — конец текущего отзыва (если в нём
            # реально было хоть одно поле, а не случайное совпадение).
            if current:
                reviews.append(current)
                current = {}
    if current:
        reviews.append(current)
    return reviews


def _fetch_reviews_on_page(page, product_url: str, max_reviews: int) -> list[dict]:
    page.goto(product_url, timeout=25000, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    title = page.title()
    if "robot" in title.lower() or "captcha" in title.lower():
        logger.warning(f"[Reviews] CAPTCHA для {product_url}")
        return []

    clicked = False
    try:
        candidates = page.locator("a, button, [role='tab']")
        count = candidates.count()
        for i in range(min(count, 400)):
            try:
                text = candidates.nth(i).inner_text(timeout=300).strip()
            except Exception:
                continue
            if re.search(r"отзыв", text, re.IGNORECASE) and len(text) < 40:
                candidates.nth(i).click(force=True, timeout=5000)
                clicked = True
                break
    except Exception:
        pass

    if clicked:
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
    else:
        for _ in range(4):
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(400)

    try:
        body_text = page.inner_text("body")
    except Exception:
        return []

    return _parse_reviews_from_text(body_text)[:max_reviews]


def get_reviews_for_products(products: list, max_reviews: int = 10) -> list[list[dict]]:
    """Возвращает реальные отзывы для каждого товара (в том же порядке, что
    products) — список списков {"pros": str?, "cons": str?, "comment": str?}.

    Одна общая браузерная сессия на все товары (не по одной на каждый) —
    иначе это было бы в N раз медленнее без необходимости.
    """
    sp = _try_playwright()
    if not sp:
        return [[] for _ in products]

    results: list[list[dict]] = []
    try:
        with sp() as p:
            browser, context = _create_context(p)
            for prod in products:
                reviews: list[dict] = []
                try:
                    page = context.new_page()
                    reviews = _fetch_reviews_on_page(page, prod.url, max_reviews)
                    page.close()
                except Exception as e:
                    logger.warning(f"[Reviews] Не удалось получить отзывы для {prod.url}: {e}")
                results.append(reviews)
            browser.close()
    except Exception as e:
        logger.error(f"[Reviews] Общая ошибка получения отзывов: {e}")
        return [[] for _ in products]

    return results


def real_cons_from_reviews(reviews: list[dict], max_cons: int = 3) -> list[str]:
    """Только реально написанные покупателями "Недостатки" — без выдумок.
    Пустой список, если ни один покупатель не написал недостаток (нормальная
    честная ситуация для товаров с хорошими отзывами).
    """
    cons: list[str] = []
    for r in reviews or []:
        c = (r.get("cons") or "").strip()
        if c and c not in cons:
            cons.append(c)
        if len(cons) >= max_cons:
            break
    return cons


def real_pros_from_reviews(reviews: list[dict], max_pros: int = 3) -> list[str]:
    """Реально написанные покупателями "Достоинства" — используется как
    более честное дополнение к общим плюсам (скидка/рейтинг/бренд)."""
    pros: list[str] = []
    for r in reviews or []:
        pr = (r.get("pros") or "").strip()
        if pr and pr not in pros:
            pros.append(pr)
        if len(pros) >= max_pros:
            break
    return pros
