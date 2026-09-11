"""Парсеры через Playwright (для GitHub Actions) + fallback."""
import logging
import re
import json
import time
from typing import Optional
from models import Product, Marketplace

logger = logging.getLogger(__name__)


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def parse_wb_playwright(limit: int = 30) -> list[Product]:
    """WB через Playwright — обходит антибот."""
    sp = _try_playwright()
    if not sp:
        logger.info("[WB] Playwright not available, skipping")
        return []

    products = []
    try:
        with sp() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="ru-RU",
            )
            page = context.new_page()

            # Перехватываем API-ответы
            api_data = {"products": []}

            def handle_response(response):
                url = response.url
                if "search.wb.ru" in url and "/search" in url:
                    try:
                        data = response.json()
                        api_data["products"] = data.get("data", {}).get("products", [])
                    except:
                        pass

            page.on("response", handle_response)

            # Загружаем страницу поиска
            page.goto("https://www.wildberries.ru/catalog/elektronika/aksessuary-i-zapchasti/dlya-telefonov-i-planshetov/naushniki-i-garnitury", timeout=30000)
            time.sleep(5)

            # Если API не сработал, пробуем парсить HTML
            if not api_data["products"]:
                items = page.query_selector_all('[class*="product-card"]')
                for item in items[:limit]:
                    try:
                        name_el = item.query_selector('[class*="product-name"]')
                        price_el = item.query_selector('[class*="price"]')
                        link_el = item.query_selector('a[href*="/catalog/"]')

                        name = name_el.inner_text() if name_el else ""
                        link = link_el.get_attribute("href") if link_el else ""

                        if name and link:
                            url = f"https://www.wildberries.ru{link}" if link.startswith("/") else link
                            products.append(Product(
                                marketplace=Marketplace.WB,
                                external_id=link.split("/")[-2] if "/" in link else "",
                                name=name[:200],
                                url=url,
                                referral_url=url,
                                category="electronics",
                            ))
                    except Exception:
                        continue

            # Если API сработал
            for item in api_data["products"][:limit]:
                try:
                    pid = str(item.get("id", ""))
                    name = f"{item.get('brand', '')} {item.get('name', '')}".strip()
                    sale_price = item.get("salePriceU", 0) / 100
                    orig_price = item.get("priceU", 0) / 100
                    if orig_price <= 0 or sale_price <= 0:
                        continue
                    discount = int((1 - sale_price / orig_price) * 100)
                    vol = item.get("vol", 0)
                    part = item.get("part", 0)
                    # Build image URL
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
                    products.append(Product(
                        marketplace=Marketplace.WB,
                        external_id=pid,
                        name=name[:200],
                        url=url,
                        referral_url=url,
                        image_url=img,
                        price_original=orig_price,
                        price_sale=sale_price,
                        discount_percent=discount,
                        rating=float(item.get("reviewRating", 0) or 0),
                        reviews_count=int(item.get("feedbacks", 0) or 0),
                        category="electronics",
                        brand=item.get("brand", ""),
                    ))
                except Exception:
                    continue

            browser.close()
    except Exception as e:
        logger.error(f"[WB Playwright] Error: {e}")

    return products


def parse_ozon_playwright(limit: int = 30) -> list[Product]:
    """Ozon через Playwright."""
    sp = _try_playwright()
    if not sp:
        logger.info("[Ozon] Playwright not available, skipping")
        return []

    products = []
    try:
        with sp() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="ru-RU",
            )
            page = context.new_page()
            page.goto("https://www.ozon.ru/category/elektronika-15816/?sorting=discount", timeout=30000)
            time.sleep(5)

            cards = page.query_selector_all('[class*="tile"], [class*="product"], [data-index]')
            for card in cards[:limit]:
                try:
                    link = card.query_selector('a[href*="/product/"]')
                    if not link:
                        continue
                    href = link.get_attribute("href")
                    name = card.inner_text().split("\n")[0][:200]
                    url = f"https://www.ozon.ru{href}" if href and href.startswith("/") else href

                    match = re.search(r"/product/[^/]*?(\d+)", url or "")
                    pid = match.group(1) if match else ""

                    if name and url:
                        products.append(Product(
                            marketplace=Marketplace.OZON,
                            external_id=pid,
                            name=name,
                            url=url,
                            referral_url=url,
                            category="electronics",
                        ))
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
        logger.info("[AliExpress] Playwright not available, skipping")
        return []

    products = []
    try:
        with sp() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="ru-RU",
            )
            page = context.new_page()
            page.goto("https://aliexpress.ru/popular/wireless-earphones.html", timeout=30000)
            time.sleep(5)

            cards = page.query_selector_all('[class*="product-card"], [class*="search-item"], [class*="_1OUGS"]')
            for card in cards[:limit]:
                try:
                    link = card.query_selector('a[href*="/item/"]')
                    if not link:
                        continue
                    href = link.get_attribute("href")
                    name = card.inner_text().split("\n")[0][:200]
                    url = href if href and href.startswith("http") else f"https://aliexpress.ru{href}"

                    match = re.search(r"/item/(\d+)", url)
                    pid = match.group(1) if match else ""

                    if name and url:
                        products.append(Product(
                            marketplace=Marketplace.ALIEXPRESS,
                            external_id=pid,
                            name=name,
                            url=url,
                            referral_url=url,
                            category="electronics",
                        ))
                except Exception:
                    continue

            browser.close()
    except Exception as e:
        logger.error(f"[AliExpress Playwright] Error: {e}")

    return products


def parse_ym_playwright(limit: int = 30) -> list[Product]:
    """Яндекс Маркет через Playwright."""
    sp = _try_playwright()
    if not sp:
        logger.info("[YM] Playwright not available, skipping")
        return []

    products = []
    try:
        with sp() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="ru-RU",
            )
            page = context.new_page()
            page.goto("https://market.yandex.ru/search?text=наушники&how=discount", timeout=30000)
            time.sleep(5)

            # Проверяем CAPTCHA
            if "robot" in page.title().lower() or "captcha" in page.url.lower():
                logger.warning("[YM] CAPTCHA detected, skipping")
                browser.close()
                return products

            cards = page.query_selector_all('[data-autotest-id="offer-snippet"], [class*="n-snippet-card"], article')
            for card in cards[:limit]:
                try:
                    link = card.query_selector('a[href*="/product/"]')
                    if not link:
                        continue
                    href = link.get_attribute("href")
                    name = card.inner_text().split("\n")[0][:200]
                    url = f"https://market.yandex.ru{href}" if href and href.startswith("/") else href

                    match = re.search(r"/product/[^/]*(\d{5,})", url or "")
                    pid = match.group(1) if match else ""

                    if name and url:
                        products.append(Product(
                            marketplace=Marketplace.YANDEX_MARKET,
                            external_id=pid,
                            name=name,
                            url=url,
                            referral_url=url,
                            category="electronics",
                        ))
                except Exception:
                    continue

            browser.close()
    except Exception as e:
        logger.error(f"[YM Playwright] Error: {e}")

    return products


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
