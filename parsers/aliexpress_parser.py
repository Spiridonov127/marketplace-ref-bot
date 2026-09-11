"""Парсер AliExpress — товары со скидками через API и веб-скрейпинг."""
import logging
import re
import json
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from parsers import BaseParser
from models import Product, Marketplace

logger = logging.getLogger(__name__)

ALI_CATEGORIES = {
    "electronics": "44",
    "home": "15",
    "beauty": "66",
    "clothing": "100003070",
    "sports": "18",
    "toys": "26",
    "food": "food",
}


class AliExpressParser(BaseParser):
    marketplace = Marketplace.ALIEXPRESS
    base_url = "https://aliexpress.ru"
    SEARCH_URL = "https://aliexpress.ru/glosearch/Search/ajax/SearchProduct"
    DEALS_URL = "https://aliexpress.ru/glosearch/api/marketing/superDeal"

    def _build_referral(self, product_url: str) -> str:
        if self.affiliate_id and "aliexpress" in product_url:
            sep = "&" if "?" in product_url else "?"
            return f"{product_url}{sep}aff_fcid={self.affiliate_id}"
        return product_url

    def parse_popular(self, category: str = "", limit: int = 50) -> list[Product]:
        products = []
        cats = {category: ALI_CATEGORIES[category]} if category else ALI_CATEGORIES
        for cat_name, cat_id in cats.items():
            try:
                items = self._fetch_search("hit", cat_id, cat_name)
                products.extend(items)
            except Exception as e:
                logger.error(f"[AliExpress] Error parsing {cat_name}: {e}")
        return products[:limit]

    def parse_deals(self, min_discount: int = 20, limit: int = 50) -> list[Product]:
        products = []
        for cat_name, cat_id in ALI_CATEGORIES.items():
            try:
                items = self._fetch_search("sale", cat_id, cat_name)
                discounted = [p for p in items if p.discount_percent >= min_discount]
                products.extend(discounted)
            except Exception as e:
                logger.error(f"[AliExpress] Error parsing deals in {cat_name}: {e}")
        products.sort(key=lambda p: p.discount_percent, reverse=True)
        return products[:limit]

    def search(self, query: str, limit: int = 20) -> list[Product]:
        try:
            return self._fetch_search(query=query, limit=limit)
        except Exception as e:
            logger.error(f"[AliExpress] Search error: {e}")
            return []

    def _fetch_search(self, keyword: str = "", cat_id: str = "",
                      category: str = "", limit: int = 20,
                      query: str = "") -> list[Product]:
        search_text = query or keyword
        params = {
            "SearchText": search_text,
            "catId": cat_id,
            "sortType": "total_tranpro_desc",
            "page": 1,
        }
        try:
            resp = self._get(self.SEARCH_URL, params=params)
            data = resp.json()
            items = data.get("items", []) or data.get("result", {}).get("items", [])
        except (json.JSONDecodeError, Exception):
            html = self._get(
                f"{self.base_url}/glosearch/result",
                params={"SearchText": search_text, "catId": cat_id}
            ).text
            return self._extract_from_html(html, category or search_text)[:limit]

        products = []
        for item in items[:limit]:
            p = self._parse_api_item(item, category or search_text)
            if p:
                products.append(p)
        return products

    def _parse_api_item(self, item: dict, category: str) -> Optional[Product]:
        try:
            product_id = str(item.get("productId", item.get("itemId", "")))
            title = item.get("title", item.get("productTitle", ""))
            price = float(item.get("price", {}).get("minPrice", 0) or
                          item.get("minPrice", 0) or 0)
            original = float(item.get("price", {}).get("maxPrice", 0) or
                             item.get("oriMinPrice", 0) or price * 1.4)
            if price <= 0:
                return None
            discount = int((1 - price / original) * 100) if original > 0 else 0
            image = item.get("image", item.get("imageUrl", ""))
            if isinstance(image, dict):
                image = image.get("url", "")
            url = item.get("productDetailUrl", item.get("itemUrl", ""))
            if not url.startswith("http"):
                url = f"{self.base_url}/item/{product_id}.html"
            rating = float(item.get("averageStar", item.get("starRating", 0)) or 0)
            orders = int(item.get("tradeDesc", "0").replace("+", "").replace(" sold", "")
                         or item.get("totalTranpro", 0) or 0)
            return Product(
                marketplace=Marketplace.ALIEXPRESS,
                external_id=product_id,
                name=re.sub(r"<[^>]+>", "", title)[:200],
                url=url,
                referral_url=self.build_referral_url(url),
                image_url=image if isinstance(image, str) else "",
                price_original=original,
                price_sale=price,
                discount_percent=max(0, discount),
                rating=rating,
                reviews_count=orders,
                category=category,
            )
        except Exception as e:
            logger.debug(f"[AliExpress] Skip item: {e}")
            return None

    def _extract_from_html(self, html: str, category: str) -> list[Product]:
        products = []
        soup = BeautifulSoup(html, "lxml")
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            p = self._jsonld_to_product(item, category)
                            if p:
                                products.append(p)
            except (json.JSONDecodeError, TypeError):
                pass
        if not products:
            cards = soup.select(".search-card-item, ._1OUGS, .product-card")
            for card in cards[:30]:
                p = self._parse_html_card(card, category)
                if p:
                    products.append(p)
        return products

    def _jsonld_to_product(self, data: dict, category: str) -> Optional[Product]:
        try:
            offers = data.get("offers", {})
            price = float(offers.get("price", 0) or 0)
            if price <= 0:
                return None
            url = data.get("url", "")
            product_id = re.search(r"/item/(\d+)", url)
            pid = product_id.group(1) if product_id else url
            return Product(
                marketplace=Marketplace.ALIEXPRESS,
                external_id=str(pid),
                name=data.get("name", ""),
                url=url,
                referral_url=self.build_referral_url(url),
                image_url=data.get("image", ""),
                price_original=price * 1.4,
                price_sale=price,
                discount_percent=28,
                rating=float(data.get("aggregateRating", {}).get("ratingValue", 0) or 0),
                reviews_count=int(data.get("aggregateRating", {}).get("reviewCount", 0) or 0),
                category=category,
            )
        except Exception:
            return None

    def _parse_html_card(self, card, category: str) -> Optional[Product]:
        try:
            link = card.select_one("a[href*='/item/']")
            if not link:
                return None
            href = link.get("href", "")
            url = href if href.startswith("http") else f"{self.base_url}{href}"
            match = re.search(r"/item/(\d+)", url)
            pid = match.group(1) if match else url[-20:]
            name = card.select_one(".title, ._18_85, h3")
            name_text = name.get_text(strip=True)[:200] if name else ""
            price_el = card.select_one(".price, ._12A8D, .aWhSM")
            price = 0
            if price_el:
                price_text = re.sub(r"[^\d.,]", "", price_el.get_text())
                price_text = price_text.replace(",", ".")
                try:
                    price = float(price_text)
                except ValueError:
                    pass
            return Product(
                marketplace=Marketplace.ALIEXPRESS,
                external_id=pid,
                name=name_text,
                url=url,
                referral_url=self.build_referral_url(url),
                price_original=price * 1.4,
                price_sale=price,
                discount_percent=28,
                category=category,
            )
        except Exception:
            return None
