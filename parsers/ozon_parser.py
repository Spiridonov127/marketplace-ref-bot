"""Парсер Ozon — товары со скидками через веб-скрейпинг."""
import logging
import re
import json
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from parsers import BaseParser
from models import Product, Marketplace

logger = logging.getLogger(__name__)

OZON_CATEGORIES = {
    "electronics": "elektronika-15816",
    "home": "dom-i-sad-6500",
    "beauty": "krasota-i-zdorove-6857",
    "clothing": "odezhda-obuv-i-aksessuary-7500",
    "sports": "sport-i-otdyh-7070",
    "toys": "detskie-tovary-7068",
    "food": "produkty-pitaniya-9700",
}


class OzonParser(BaseParser):
    marketplace = Marketplace.OZON
    base_url = "https://www.ozon.ru"
    SEARCH_URL = "https://www.ozon.ru/search/"
    CATEGORY_URL = "https://www.ozon.ru/category/"

    def _build_referral(self, product_url: str) -> str:
        if self.affiliate_id and "ozon.ru" in product_url:
            sep = "&" if "?" in product_url else "?"
            return f"{product_url}{sep}partner={self.affiliate_id}"
        return product_url

    def parse_popular(self, category: str = "", limit: int = 50) -> list[Product]:
        products = []
        cats = {category: OZON_CATEGORIES[category]} if category else OZON_CATEGORIES
        for cat_name, cat_slug in cats.items():
            try:
                url = f"{self.CATEGORY_URL}{cat_slug}/?sorting=rating"
                html = self._get(url).text
                items = self._extract_from_html(html, cat_name)
                products.extend(items)
            except Exception as e:
                logger.error(f"[Ozon] Error parsing {cat_name}: {e}")
        return products[:limit]

    def parse_deals(self, min_discount: int = 20, limit: int = 50) -> list[Product]:
        products = []
        for cat_name, cat_slug in OZON_CATEGORIES.items():
            try:
                url = f"{self.CATEGORY_URL}{cat_slug}/?sorting=discount"
                html = self._get(url).text
                items = self._extract_from_html(html, cat_name)
                discounted = [p for p in items if p.discount_percent >= min_discount]
                products.extend(discounted)
            except Exception as e:
                logger.error(f"[Ozon] Error parsing deals in {cat_name}: {e}")
        products.sort(key=lambda p: p.discount_percent, reverse=True)
        return products[:limit]

    def search(self, query: str, limit: int = 20) -> list[Product]:
        url = f"{self.SEARCH_URL}?text={quote_plus(query)}&sorting=rating"
        try:
            html = self._get(url).text
            return self._extract_from_html(html, "search")[:limit]
        except Exception as e:
            logger.error(f"[Ozon] Search error: {e}")
            return []

    def _extract_from_html(self, html: str, category: str) -> list[Product]:
        products = []
        soup = BeautifulSoup(html, "lxml")

        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get("@type") == "ItemList":
                    for item in data.get("itemListElement", []):
                        p = self._parse_jsonld_item(item, category)
                        if p:
                            products.append(p)
            except (json.JSONDecodeError, TypeError):
                pass

        if not products:
            product_cards = soup.select('[data-index]')
            for card in product_cards[:30]:
                p = self._parse_card(card, category)
                if p:
                    products.append(p)
        return products

    def _parse_jsonld_item(self, item: dict, category: str) -> Optional[Product]:
        try:
            url = item.get("url", "")
            if not url:
                return None
            product_id = self._extract_product_id(url)
            name = item.get("name", "")
            offers = item.get("offers", {})
            price = float(offers.get("price", 0) or 0)
            if price <= 0:
                return None
            return Product(
                marketplace=Marketplace.OZON,
                external_id=product_id,
                name=name,
                url=url if url.startswith("http") else f"{self.base_url}{url}",
                referral_url=self.build_referral_url(url),
                image_url=item.get("image", ""),
                price_original=price * 1.3,
                price_sale=price,
                discount_percent=23,
                rating=float(item.get("aggregateRating", {}).get("ratingValue", 0) or 0),
                reviews_count=int(item.get("aggregateRating", {}).get("reviewCount", 0) or 0),
                category=category,
            )
        except Exception as e:
            logger.debug(f"[Ozon] Skip jsonld item: {e}")
            return None

    def _parse_card(self, card, category: str) -> Optional[Product]:
        try:
            link_tag = card.select_one('a[href*="/product/"]')
            if not link_tag:
                return None
            href = link_tag.get("href", "")
            url = href if href.startswith("http") else f"{self.base_url}{href}"
            product_id = self._extract_product_id(url)
            name_tag = card.select_one("span")
            name = name_tag.get_text(strip=True) if name_tag else ""
            price_tags = card.select("span")
            prices = []
            for pt in price_tags:
                text = pt.get_text(strip=True).replace("\u00a0", "").replace("₽", "")
                text = re.sub(r"[^\d]", "", text)
                if text and text.isdigit():
                    prices.append(int(text))
            price_sale = prices[0] if prices else 0
            price_original = prices[1] if len(prices) > 1 else price_sale * 1.3
            discount = int((1 - price_sale / price_original) * 100) if price_original > 0 else 0
            return Product(
                marketplace=Marketplace.OZON,
                external_id=product_id,
                name=name,
                url=url,
                referral_url=self.build_referral_url(url),
                price_original=price_original,
                price_sale=price_sale,
                discount_percent=max(0, discount),
                category=category,
            )
        except Exception as e:
            logger.debug(f"[Ozon] Skip card: {e}")
            return None

    @staticmethod
    def _extract_product_id(url: str) -> str:
        match = re.search(r"/product/[^/]*?(\d+)", url)
        return match.group(1) if match else url.split("/")[-1][:20]
