"""Парсеры через Playwright с anti-detect настройками."""
import logging
import re
import json
import time
from typing import Optional
from models import Product, Marketplace
from referral_builder import build_referral_url

logger = logging.getLogger(__name__)


def _ref(url: str, mp: Marketplace) -> str:
    """Helper: build referral URL."""
    return build_referral_url(url, mp)


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
    # Убираем WebDriver флаг
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en'] });
        window.chrome = { runtime: {} };
    """)
    return browser, context


def parse_wb_playwright(limit: int = 30) -> list[Product]:
    """WB через Playwright — перехват JSON API ответов."""
    sp = _try_playwright()
    if not sp:
        return []

    products = []
    try:
        with sp() as p:
            browser, context = _create_browser_context(p)
            page = context.new_page()

            # Перехватываем JSON API ответы от WB
            api_responses = []

            def handle_response(response):
                url = response.url
                if any(x in url for x in ["search.wb.ru", "catalog.wb.ru", "card.wb.ru"]):
                    try:
                        data = response.json()
                        api_responses.append({"url": url, "data": data})
                    except:
                        pass

            page.on("response", handle_response)

            # Загружаем страницу каталога электроники
            try:
                page.goto(
                    "https://www.wildberries.ru/catalog/elektronika",
                    timeout=25000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(3000)

                # Прокручиваем для загрузки lazy content
                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1000)")
                    page.wait_for_timeout(500)
            except Exception as e:
                logger.warning(f"[WB] Page load error: {e}")

            # Парсим перехваченные API ответы
            for resp in api_responses:
                data = resp["data"]
                prods_raw = data.get("data", {}).get("products", [])
                for item in prods_raw[:limit]:
                    p = _wb_api_item_to_product(item)
                    if p:
                        products.append(p)

            # Если API не дал результатов, парсим HTML
            if not products:
                cards = page.query_selector_all(
                    '[class*="product-card"], [class*="j-card-item"], '
                    '[class*="card-product"], a[href*="/catalog/"][href*="/detail"]'
                )
                for card in cards[:limit]:
                    try:
                        link = card.query_selector('a[href*="/catalog/"]') or card
                        href = link.get_attribute("href") or ""
                        if not href or "/catalog/" not in href:
                            continue

                        name_el = card.query_selector(
                            '[class*="product-name"], [class*="goods-name"], '
                            '[class*="j-card-name"], span[class*="name"]'
                        )
                        name = name_el.inner_text().strip() if name_el else ""
                        if not name:
                            name = card.inner_text().split("\n")[0].strip()[:200]

                        pid_match = re.search(r"/catalog/(\d+)/", href)
                        pid = pid_match.group(1) if pid_match else href.split("/")[-2]

                        url = href if href.startswith("http") else f"https://www.wildberries.ru{href}"

                        products.append(Product(
                            marketplace=Marketplace.WB,
                            external_id=pid,
                            name=name[:200],
                            url=url,
                            referral_url=_ref(url, Marketplace.WB),
                            category="electronics",
                        ))
                    except Exception:
                        continue

            browser.close()
    except Exception as e:
        logger.error(f"[WB Playwright] Error: {e}")

    return products


def _wb_api_item_to_product(item: dict) -> Optional[Product]:
    try:
        pid = str(item.get("id", ""))
        name = f"{item.get('brand', '')} {item.get('name', '')}".strip()
        sale_price = item.get("salePriceU", 0) / 100
        orig_price = item.get("priceU", 0) / 100
        if orig_price <= 0 or sale_price <= 0 or not name:
            return None
        discount = int((1 - sale_price / orig_price) * 100)
        vol = item.get("vol", 0)
        part = item.get("part", 0)
        basket = vol // 100000
        if basket <= 143:
            host = "basket-01.wbbasket.ru"
        elif basket <= 287:
            host = "basket-02.wbbasket.ru"
        elif basket <= 431:
            host = "basket-03.wbbasket.ru"
        elif basket <= 719:
            host = "basket-04.wbbasket.ru"
        elif basket <= 1007:
            host = "basket-05.wbbasket.ru"
        else:
            host = "basket-10.wbbasket.ru"
        img = f"https://{host}/vol{vol}/part{part}/{pid}/images/big/1.webp"
        url = f"https://www.wildberries.ru/catalog/{pid}/detail.aspx"
        return Product(
            marketplace=Marketplace.WB,
            external_id=pid,
            name=name[:200],
            url=url,
            referral_url=_ref(url, Marketplace.WB),
            image_url=img,
            price_sale=sale_price,
            discount_percent=discount,
            rating=float(item.get("reviewRating", 0) or 0),
            reviews_count=int(item.get("feedbacks", 0) or 0),
            category="electronics",
            brand=item.get("brand", ""),
        )
    except Exception:
        return None


def parse_ozon_playwright(limit: int = 30) -> list[Product]:
    """Ozon через Playwright — перехват API ответов."""
    sp = _try_playwright()
    if not sp:
        return []

    products = []
    try:
        with sp() as p:
            browser, context = _create_browser_context(p)
            page = context.new_page()

            api_responses = []

            def handle_response(response):
                url = response.url
                if "api/composer" in url or "search" in url:
                    try:
                        data = response.json()
                        api_responses.append(data)
                    except:
                        pass

            page.on("response", handle_response)

            try:
                page.goto(
                    "https://www.ozon.ru/category/elektronika-15816/?sorting=discount",
                    timeout=25000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(5000)

                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1000)")
                    page.wait_for_timeout(500)
            except Exception as e:
                logger.warning(f"[Ozon] Page load error: {e}")

            # Парсим HTML если API не сработал
            cards = page.query_selector_all(
                '[class*="tile"], [class*="product"], [data-index], '
                'a[href*="/product/"]'
            )
            seen = set()
            for card in cards[:limit * 2]:
                try:
                    link = card.query_selector('a[href*="/product/"]') or (
                        card if "product" in (card.get_attribute("href") or "") else None
                    )
                    if not link:
                        continue
                    href = link.get_attribute("href") or ""
                    match = re.search(r"/product/[^/]*?(\d+)", href)
                    if not match:
                        continue
                    pid = match.group(1)
                    if pid in seen:
                        continue
                    seen.add(pid)

                    name = card.inner_text().split("\n")[0].strip()[:200]
                    url = href if href.startswith("http") else f"https://www.ozon.ru{href}"

                    products.append(Product(
                        marketplace=Marketplace.OZON,
                        external_id=pid,
                        name=name,
                        url=url,
                        referral_url=_ref(url, Marketplace.OZON),
                        category="electronics",
                    ))
                    if len(products) >= limit:
                        break
                except Exception:
                    continue

            browser.close()
    except Exception as e:
        logger.error(f"[Ozon Playwright] Error: {e}")

    return products


def parse_aliexpress_playwright(limit: int = 30) -> list[Product]:
    """AliExpress через Playwright."""
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
                    "https://aliexpress.ru/category/phones-telecommunications.html?catId=5090301",
                    timeout=25000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(5000)
            except Exception as e:
                logger.warning(f"[AliExpress] Page load error: {e}")

            # Парсим JSON-LD
            scripts = page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    text = script.inner_text()
                    data = json.loads(text)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get("@type") == "Product":
                                p = _ali_jsonld_to_product(item)
                                if p:
                                    products.append(p)
                except:
                    pass

            # HTML fallback
            if not products:
                cards = page.query_selector_all(
                    '[class*="product-card"], [class*="search-item"], '
                    'a[href*="/item/"]'
                )
                seen = set()
                for card in cards[:limit * 2]:
                    try:
                        link = card.query_selector('a[href*="/item/"]') or (
                            card if "/item/" in (card.get_attribute("href") or "") else None
                        )
                        if not link:
                            continue
                        href = link.get_attribute("href") or ""
                        match = re.search(r"/item/(\d+)", href)
                        if not match:
                            continue
                        pid = match.group(1)
                        if pid in seen:
                            continue
                        seen.add(pid)

                        name = card.inner_text().split("\n")[0].strip()[:200]
                        url = href if href.startswith("http") else f"https://aliexpress.ru{href}"

                        products.append(Product(
                            marketplace=Marketplace.ALIEXPRESS,
                            external_id=pid,
                            name=name,
                            url=url,
                            referral_url=_ref(url, Marketplace.ALIEXPRESS),
                            category="electronics",
                        ))
                        if len(products) >= limit:
                            break
                    except Exception:
                        continue

            browser.close()
    except Exception as e:
        logger.error(f"[AliExpress Playwright] Error: {e}")

    return products


def _ali_jsonld_to_product(item: dict) -> Optional[Product]:
    try:
        offers = item.get("offers", {})
        price = float(offers.get("price", 0) or 0)
        if price <= 0:
            return None
        url = item.get("url", "")
        match = re.search(r"/item/(\d+)", url)
        pid = match.group(1) if match else url[-20:]
        return Product(
            marketplace=Marketplace.ALIEXPRESS,
            external_id=pid,
            name=item.get("name", "")[:200],
            url=url,
            referral_url=_ref(url, Marketplace.ALIEXPRESS),
            image_url=item.get("image", ""),
            price_sale=price,
            discount_percent=28,
            rating=float(item.get("aggregateRating", {}).get("ratingValue", 0) or 0),
            reviews_count=int(item.get("aggregateRating", {}).get("reviewCount", 0) or 0),
            category="electronics",
        )
    except Exception:
        return None


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
            if "robot" in title.lower() or "captcha" in title.lower():
                logger.warning("[YM] CAPTCHA detected")
                browser.close()
                return products

            # Парсим JSON-LD
            scripts = page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    data = json.loads(script.inner_text())
                    if isinstance(data, dict) and data.get("@type") == "ItemList":
                        for entry in data.get("itemListElement", []):
                            item = entry.get("item", entry)
                            p = _ym_jsonld_to_product(item)
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
                            referral_url=_ref(url, Marketplace.YANDEX_MARKET),
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


def _ym_jsonld_to_product(item: dict) -> Optional[Product]:
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
        return Product(
            marketplace=Marketplace.YANDEX_MARKET,
            external_id=pid,
            name=item.get("name", "")[:200],
            url=url if url.startswith("http") else f"https://market.yandex.ru{url}",
            referral_url=_ref(url, Marketplace.YANDEX_MARKET),
            image_url=item.get("image", ""),
            price_sale=price,
            discount_percent=23,
            rating=float(item.get("aggregateRating", {}).get("ratingValue", 0) or 0),
            reviews_count=int(item.get("aggregateRating", {}).get("reviewCount", 0) or 0),
            category="electronics",
        )
    except Exception:
        return None


def parse_all_playwright(limit_per_mp: int = 20) -> list[Product]:
    """Парсинг всех маркетплейсов через Playwright."""
    all_products = []

    for name, parser in [
        ("WB", parse_wb_playwright),
        ("Ozon", parse_ozon_playwright),
        ("AliExpress", parse_aliexpress_playwright),
        ("YM", parse_ym_playwright),
    ]:
        try:
            items = parser(limit=limit_per_mp)
            logger.info(f"[Playwright] {name}: {len(items)} products")
            all_products.extend(items)
        except Exception as e:
            logger.error(f"[Playwright] {name} error: {e}")

    return all_products
