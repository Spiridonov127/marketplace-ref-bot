"""Парсер Яндекс Маркета через Playwright с anti-detect настройками."""
import logging
import re
import json
from typing import Optional
from urllib.parse import quote_plus
from models import Product, Marketplace
from referral_builder import build_referral_url

logger = logging.getLogger(__name__)


class YandexCaptchaError(Exception):
    """Яндекс показал SmartCaptcha вместо запрошенной страницы.

    Отдельный тип ошибки, а не пустой список, потому что это принципиально
    другая ситуация: "товаров не нашлось" лечится другим запросом и повтором,
    а капча — нет, её повторять бессмысленно, надо менять IP. Раньше капча
    молча выглядела как "ничего не нашлось", и бот советовал пользователю
    переформулировать запрос, хотя запрос был ни при чём.
    """


def _is_captcha(page) -> bool:
    """Определяет страницу SmartCaptcha по трём независимым признакам.

    Проверять только заголовок мало: раньше здесь искали "robot"/"captcha"
    латиницей, а Яндекс отдаёт заголовок "Вы не робот?" кириллицей — и капча
    проходила незамеченной (подтверждено логом боевого запуска).
    """
    try:
        if "showcaptcha" in (page.url or "").lower():
            return True
        title = (page.title() or "").lower()
        if any(w in title for w in ("robot", "робот", "captcha", "капча")):
            return True
        try:
            body = page.inner_text("body")[:1000].lower()
        except Exception:
            return False
        return "smartcaptcha" in body or "вы не робот" in body
    except Exception:
        return False


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def _create_browser_context(playwright):
    """Создаёт контекст браузера с anti-detect настройками."""
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        locale="ru-RU",
        viewport={"width": 1920, "height": 1080},
        java_script_enabled=True,
        timezone_id="Europe/Moscow",
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en'] });
        window.chrome = { runtime: {} };
    """)
    return browser, context


def _dump_empty_result_debug(page, tag: str):
    """Сохраняет, что реально показал Маркет, когда товаров не нашлось.

    Снаружи "ничего не найдено" выглядит одинаково в трёх очень разных
    случаях: товаров правда нет; Яндекс показал капчу (её ловим по заголовку,
    но у разных заглушек заголовки разные); Яндекс просто не отдал выдачу
    этому IP — так бывает с дата-центровыми адресами, с которых ходит GitHub
    Actions. Скриншот и текст страницы отвечают на это сразу, без гадания.
    Файлы кладём в data/, откуда workflow забирает их артефактом.
    """
    import os

    try:
        os.makedirs("data", exist_ok=True)
        url = page.url
        title = page.title()
        try:
            text = page.inner_text("body")[:2000]
        except Exception:
            text = "(не удалось прочитать текст страницы)"

        logger.warning(f"[YM debug/{tag}] Пусто. URL: {url}")
        logger.warning(f"[YM debug/{tag}] Заголовок: {title!r}")
        logger.warning(f"[YM debug/{tag}] Начало текста: {text[:500]!r}")

        page.screenshot(path=f"data/ym_debug_{tag}.png", full_page=False)
        with open(f"data/ym_debug_{tag}.txt", "w", encoding="utf-8") as f:
            f.write(f"URL: {url}\nTITLE: {title}\n\n{text}")
    except Exception as e:
        logger.warning(f"[YM debug/{tag}] Не удалось снять диагностику: {e}")


def parse_ym_playwright(limit: int = 30) -> list[Product]:
    """Яндекс Маркет через Playwright."""
    sp = _try_playwright()
    if not sp:
        return []

    products = []
    try:
        with sp() as p:
            browser, context = _create_browser_context(p)
            page = context.new_page()

            try:
                page.goto(
                    "https://market.yandex.ru/catalog--elektronika/54439/list?hid=90555&glfilter=offer-shippable:1&how=discount",
                    timeout=25000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(5000)
            except Exception as e:
                logger.warning(f"[YM] Page load error: {e}")

            # Проверяем CAPTCHA
            title = page.title()
            if _is_captcha(page) or "robot" in title.lower() or "captcha" in title.lower():
                logger.warning("[YM] CAPTCHA detected")
                browser.close()
                return products

            # Реальные цены "было/стало" достаём из внутренних apiary-patch блоков —
            # в JSON-LD страницы старой цены нет вообще, только текущая.
            price_patches = _extract_price_patches(page)

            # Парсим JSON-LD
            scripts = page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    data = json.loads(script.inner_text())
                    if isinstance(data, dict) and data.get("@type") == "ItemList":
                        for entry in data.get("itemListElement", []):
                            item = entry.get("item", entry)
                            p = _ym_jsonld_to_product(item, price_patches)
                            if p:
                                products.append(p)
                except:
                    pass

            # HTML fallback
            if not products:
                cards = page.query_selector_all(
                    '[data-autotest-id="offer-snippet"], [class*="n-snippet-card"], '
                    'article, [class*="snippet"], a[href*="/product/"]'
                )
                seen = set()
                for card in cards[:limit * 2]:
                    try:
                        link = card.query_selector('a[href*="/product/"]') or (
                            card if "/product/" in (card.get_attribute("href") or "") else None
                        )
                        if not link:
                            continue
                        href = link.get_attribute("href") or ""
                        match = re.search(r"/product/[^/]*(\d{5,})", href)
                        if not match:
                            continue
                        pid = match.group(1)
                        if pid in seen:
                            continue
                        seen.add(pid)

                        name = card.inner_text().split("\n")[0].strip()[:200]
                        url = href if href.startswith("http") else f"https://market.yandex.ru{href}"

                        products.append(Product(
                            marketplace=Marketplace.YANDEX_MARKET,
                            external_id=pid,
                            name=name,
                            url=url,
                            referral_url=build_referral_url(url, Marketplace.YANDEX_MARKET),
                            category="electronics",
                        ))
                        if len(products) >= limit:
                            break
                    except Exception:
                        continue

            browser.close()
    except Exception as e:
        logger.error(f"[YM Playwright] Error: {e}")

    return products


def _extract_price_patches(page) -> dict:
    """Достаёт реальные пары (цена, старая цена) из внутренних apiary-patch блоков страницы.

    В публичной JSON-LD разметке Маркета старой цены нет вообще — только текущая.
    Она реально показывается пользователю (в виде "было/стало"), но зашита во
    внутреннее состояние React-приложения, которое попадает в HTML для гидратации,
    в блоках <noframes data-apiary="patch">{...json...}</noframes>. Это не публичный
    и не документированный формат — Яндекс может поменять его в любой момент без
    предупреждения, — но сейчас это единственное место на странице каталога, где
    реально есть honest старая цена, а не выдумка.

    Возвращает {sku_id (str): {"price": float, "old_price": float}} только для тех
    товаров, где old_price > price > 0 (то есть скидка реально подтверждена).
    """
    patches: dict = {}
    try:
        blocks = page.query_selector_all('noframes[data-apiary="patch"]')
    except Exception:
        blocks = []

    def walk(obj):
        if isinstance(obj, dict):
            price = obj.get("price")
            old_price = obj.get("oldPrice")
            sku_id = obj.get("skuId")
            if sku_id and old_price and isinstance(price, dict):
                try:
                    value_fmt = price.get("valueFmt")
                    price_val = float(value_fmt) if value_fmt is not None else float(price.get("value", 0)) / 1e7
                    old_val = float(old_price) / 1e7
                    if old_val > price_val > 0:
                        patches[str(sku_id)] = {"price": price_val, "old_price": old_val}
                except (TypeError, ValueError):
                    pass
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    for block in blocks:
        try:
            walk(json.loads(block.inner_text()))
        except Exception:
            continue

    return patches


def _extract_image_url(item: dict) -> str:
    """Достаёт URL картинки из поля "image" JSON-LD.

    По спецификации schema.org "image" может быть простой строкой, списком
    строк, объектом ImageObject ({"url": ...}) или списком таких объектов —
    Яндекс Маркет отдаёт разные варианты для разных товаров. Раньше бралось
    только "как есть" (item.get("image", "")), и для товаров, где это был
    список/объект, картинка терялась (пустая строка вместо реальной ссылки).
    """
    img = item.get("image")
    if isinstance(img, str):
        return img
    if isinstance(img, dict):
        return img.get("url") or img.get("contentUrl") or ""
    if isinstance(img, list):
        for entry in img:
            if isinstance(entry, str) and entry:
                return entry
            if isinstance(entry, dict):
                url = entry.get("url") or entry.get("contentUrl")
                if url:
                    return url
    return ""


def _ym_jsonld_to_product(item: dict, price_patches: dict = None) -> Optional[Product]:
    try:
        url = item.get("url", "")
        if not url:
            return None
        match = re.search(r"/product/[^/]*(\d{5,})", url)
        pid = match.group(1) if match else url[-20:]
        offers = item.get("offers", {})
        price = float(offers.get("price", 0) or 0)
        if price <= 0:
            return None

        sku = str(item.get("sku") or pid)
        patch = (price_patches or {}).get(sku)

        if patch:
            # Подтверждённая реальная скидка — берём обе цены из одного и того же
            # источника, чтобы проценты честно сходились.
            price_sale = patch["price"]
            price_original = patch["old_price"]
            discount_percent = round((price_original - price_sale) / price_original * 100)
        else:
            # Данных о старой цене нет — не выдумываем скидку. discount_percent=0
            # означает, что товар не пройдёт фильтр MIN_DISCOUNT_PERCENT и не
            # попадёт в пост как "товар со скидкой".
            price_sale = price
            price_original = price
            discount_percent = 0

        agg = item.get("aggregateRating") or {}
        # У части товаров в JSON-LD Маркета заполнено только ratingCount
        # (число оценок), а reviewCount (число текстовых отзывов) — 0 или
        # отсутствует, хотя в интерфейсе показывается именно ratingCount как
        # "N отзывов". Раньше бралось только reviewCount, из-за чего в статье
        # писалось "0 отзывов" при реально существующих тысячах оценок.
        reviews_count = agg.get("reviewCount") or agg.get("ratingCount") or 0

        return Product(
            marketplace=Marketplace.YANDEX_MARKET,
            external_id=pid,
            name=item.get("name", "")[:200],
            url=url if url.startswith("http") else f"https://market.yandex.ru{url}",
            referral_url=build_referral_url(url, Marketplace.YANDEX_MARKET),
            image_url=_extract_image_url(item),
            price_original=price_original,
            price_sale=price_sale,
            discount_percent=discount_percent,
            rating=float(agg.get("ratingValue", 0) or 0),
            reviews_count=int(reviews_count or 0),
            category="electronics",
        )
    except Exception:
        return None


def parse_ym_search_playwright(query: str, limit: int = 30) -> list[Product]:
    """Ищет товары на Яндекс Маркете по свободному запросу/категории (например,
    "наушники", "детские игрушки на улицу") — используется для ручного постинга
    по команде из Telegram-бота, в отличие от parse_ym_playwright(), который
    всегда ходит в одну и ту же зашитую категорию "Электроника" по расписанию.

    Логика идентична parse_ym_playwright() (тот же anti-detect контекст, тот же
    разбор JSON-LD с реальными "было/стало" ценами из apiary-patch, тот же
    HTML fallback), только URL — не каталог, а поиск по тексту.
    """
    sp = _try_playwright()
    if not sp:
        return []

    products = []
    try:
        with sp() as p:
            browser, context = _create_browser_context(p)
            page = context.new_page()

            search_url = f"https://market.yandex.ru/search?text={quote_plus(query)}&how=discount"
            try:
                page.goto(search_url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
            except Exception as e:
                logger.warning(f"[YM search] Page load error for {query!r}: {e}")

            if _is_captcha(page):
                logger.error(
                    f"[YM search] Яндекс показал капчу вместо выдачи по {query!r} "
                    f"(URL: {page.url[:120]})"
                )
                _dump_empty_result_debug(page, "captcha")
                browser.close()
                raise YandexCaptchaError(
                    "Яндекс Маркет показал капчу вместо результатов поиска"
                )

            price_patches = _extract_price_patches(page)

            scripts = page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    data = json.loads(script.inner_text())
                    if isinstance(data, dict) and data.get("@type") == "ItemList":
                        for entry in data.get("itemListElement", []):
                            item = entry.get("item", entry)
                            prod = _ym_jsonld_to_product(item, price_patches)
                            if prod:
                                prod.category = query
                                products.append(prod)
                except Exception:
                    pass

            if not products:
                cards = page.query_selector_all(
                    '[data-autotest-id="offer-snippet"], [class*="n-snippet-card"], '
                    'article, [class*="snippet"], a[href*="/product/"]'
                )
                seen = set()
                for card in cards[:limit * 2]:
                    try:
                        link = card.query_selector('a[href*="/product/"]') or (
                            card if "/product/" in (card.get_attribute("href") or "") else None
                        )
                        if not link:
                            continue
                        href = link.get_attribute("href") or ""
                        match = re.search(r"/product/[^/]*(\d{5,})", href)
                        if not match:
                            continue
                        pid = match.group(1)
                        if pid in seen:
                            continue
                        seen.add(pid)

                        name = card.inner_text().split("\n")[0].strip()[:200]
                        url = href if href.startswith("http") else f"https://market.yandex.ru{href}"

                        products.append(Product(
                            marketplace=Marketplace.YANDEX_MARKET,
                            external_id=pid,
                            name=name,
                            url=url,
                            referral_url=build_referral_url(url, Marketplace.YANDEX_MARKET),
                            category=query,
                        ))
                        if len(products) >= limit:
                            break
                    except Exception:
                        continue

            if not products:
                _dump_empty_result_debug(page, "search")

            browser.close()
    except Exception as e:
        logger.error(f"[YM search Playwright] Error for query {query!r}: {e}")

    return products[:limit]

