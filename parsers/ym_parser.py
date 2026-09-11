"""Парсер Яндекс Маркет — товары со скидками через веб-скрейпинг."""
import logging
import re
import json
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from parsers import BaseParser
from models import Product, Marketplace

logger = logging.getLogger(__name__)

YM_CATEGORIES = {
    "electronics": "elektronika",
    "home": "dom-i-dacha",
    "beauty": "krasota",
    "clothing": "odezhda-obuv-i-aksessuary",
    "sports": "sport-i-razvlecheniya",
    "toys": "detskie-tovary",
    "food": "produkty",
}


class YandexMarketParser(BaseParser):
    marketplace = Marketplace.YANDEX_MARKET
    base_url = "https://market.yandex.ru"
    SEARCH_URL = "https://market.yandex.ru/search"
    CATALOG_URL = "https://market.yandex.ru/catalog"

    def _build_referral(self, product_url: str) -> str:
        if self.affiliate_id and "market.yandex" in product_url:
            sep = "&" if "?" in product_url else "?"
            return f"{product_url}{sep}clid={self.affiliate_id}"
        return product_url

    def parse_popular(self, category: str = "", limit: int = 50) -> list[Product]:
        products = []
        cats = {category: YM_CATEGORIES[category]} if category else YM_CATEGORIES
        for cat_name, cat_slug in cats.items():
            try:
                url = f"{self.CATALOG_URL}/{cat_slug}?how=opinions&glfilter=offer-shippable:1"
                html = self._get(url).text
                items = self._extract_products(html, cat_name)
                products.extend(items)
            except Exception as e:
                logger.error(f"[YM] Error parsing {cat_name}: {e}")
        return products[:limit]

    def parse_deals(self, min_discount: int = 20, limit: int = 50) -> list[Product]:
        products = []
        for cat_name, cat_slug in YM_CATEGORIES.items():
            try:
                url = f"{self.CATALOG_URL}/{cat_slug}?how=discount&glfilter=offer-shippable:1"
                html = self._get(url).text
                items = self._extract_products(html, cat_name)
                discounted = [p for p in items if p.discount_percent >= min_discount]
                products.extend(discounted)
            except Exception as e:
                logger.error(f"[YM] Error parsing deals in {cat_name}: {e}")
        products.sort(key=lambda p: p.discount_percent, reverse=True)
        return products[:limit]

    def search(self, query: str, limit: int = 20) -> list[Product]:
        try:
            url = f"{self.SEARCH_URL}?text={quote_plus(query)}&how=opinions"
            html = self._get(url).text
            return self._extract_products(html, "search")[:limit]
        except Exception as e:
            logger.error(f"[YM] Search error: {e}")
            return []

    def _extract_products(self, html: str, category: str) -> list[Product]:
        soup = BeautifulSoup(html, "lxml")
        products = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get("@type") == "ItemList":
                    for entry in data.get("itemListElement", []):
                        p = self._parse_jsonld(entry, category)
                        if p:
                            products.append(p)
                elif isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict) and entry.get("@type") == "Product":
                            p = self._parse_product_jsonld(entry, category)
                            if p:
                                products.append(p)
            except (json.JSONDecodeError, TypeError):
                pass

        if not products:
            product_cards = soup.select(
                '[data-autotest-id="offer-snippet"],'
                '[data-zone-name="snippetList"] article,'
                '.n-snippet-card,._3N0fP'
            )
            for card in product_cards[:30]:
                p = self._parse_card(card, category)
                if p:
                    products.append(p)
        return products

    def _parse_jsonld(self, entry: dict, category: str) -> Optional[Product]:
        try:
            item = entry.get("item", entry)
            return self._parse_product_jsonld(item, category)
        except Exception:
            return None

    def _parse_product_jsonld(self, item: dict, category: str) -> Optional[Product]:
        try:
            url = item.get("url", "")
            if not url:
                return None
            if not url.startswith("http"):
                url = f"{self.base_url}{url}"
            product_id = self._extract_id(url)
            name = item.get("name", "")
            offers = item.get("offers", {})
            price = float(offers.get("price", 0) or 0)
            if price <= 0:
                return None
            low_price = float(item.get("lowPrice", price))
            high_price = float(item.get("highPrice", price * 1.3))
            discount = int((1 - low_price / high_price) * 100) if high_price > 0 else 0
            image = item.get("image", "")
            if isinstance(image, list):
                image = image[0] if image else ""
            rating = float(item.get("aggregateRating", {}).get("ratingValue", 0) or 0)
            reviews = int(item.get("aggregateRating", {}).get("reviewCount", 0) or 0)
            return Product(
                marketplace=Marketplace.YANDEX_MARKET,
                external_id=product_id,
                name=name[:200],
                url=url,
                referral_url=self.build_referral_url(url),
                image_url=image,
                price_original=high_price,
                price_sale=low_price,
                discount_percent=max(0, discount),
                rating=rating,
                reviews_count=reviews,
                category=category,
            )
        except Exception as e:
            logger.debug(f"[YM] Skip jsonld product: {e}")
            return None

    def _parse_card(self, card, category: str) -> Optional[Product]:
        try:
            link = card.select_one(
                'a[href*="/product/"], a[href*="/product--"], a[href*="/card/"]'
            )
            if not link:
                return None
            href = link.get("href", "")
            url = href if href.startswith("http") else f"{self.base_url}{href}"
            product_id = self._extract_id(url)
            name_el = card.select_one(
                '[data-auto="snippet-title"], .n-snippet-card__title, h3'
            )
            name = name_el.get_text(strip=True)[:200] if name_el else ""
            price_el = card.select_one('[data-auto="price-value"], .price')
            price = 0
            if price_el:
                price_text = re.sub(r"[^\d]", "", price_el.get_text())
                price = int(price_text) if price_text.isdigit() else 0
            old_price_el = card.select_one('[data-auto="price-old"], .price-old')
            old_price = price * 1.3
            if old_price_el:
                old_text = re.sub(r"[^\d]", "", old_price_el.get_text())
                old_price = int(old_text) if old_text.isdigit() else old_price
            discount = int((1 - price / old_price) * 100) if old_price > 0 and price > 0 else 0
            img_el = card.select_one("img")
            img_url = img_el.get("src", "") if img_el else ""
            return Product(
                marketplace=Marketplace.YANDEX_MARKET,
                external_id=product_id,
                name=name,
                url=url,
                referral_url=self.build_referral_url(url),
                image_url=img_url,
                price_original=old_price,
                price_sale=price if price > 0 else old_price * 0.7,
                discount_percent=max(0, discount),
                category=category,
            )
        except Exception as e:
            logger.debug(f"[YM] Skip card: {e}")
            return None

    @staticmethod
    def _extract_id(url: str) -> str:
        match = re.search(r"/product/[^/]*(\d{5,})", url)
        if match:
            return match.group(1)
        match = re.search(r"/product--([^/]+)", url)
        if match:
            return match.group(1)
        return url.split("?")[0].rstrip("/").split("/")[-1][:30]
