"""Парсер Wildberries — популярные товары и скидки через публичный JSON API."""
import logging
import re
from typing import Optional

from parsers import BaseParser
from models import Product, Marketplace

logger = logging.getLogger(__name__)

# Категории Wildberries (cat IDs)
WB_CATEGORIES = {
    "electronics": 14409,
    "home": 14386,
    "beauty": 14397,
    "clothing": 629,
    "sports": 14430,
    "toys": 14443,
    "food": 14399,
}

# Шарды каталога WB
WB_SHARDS = {
    "electronics": "beauty",
    "home": "beauty",
    "beauty": "beauty",
    "clothing": "beauty",
    "sports": "beauty",
    "toys": "beauty",
    "food": "beauty",
}


class WildberriesParser(BaseParser):
    marketplace = Marketplace.WB
    base_url = "https://www.wildberries.ru"

    SEARCH_API = "https://search.wb.ru/exactmatch/ru/common/v7/search"
    CATALOG_API = "https://catalog-ru.wb.ru/catalog/brutal2/catalog"
    POPULAR_API = "https://catalog-ru.wb.ru/catalog/brutal2/popular"

    def _build_referral(self, product_url: str) -> str:
        if self.affiliate_id and "wb.ru" in product_url:
            sep = "&" if "?" in product_url else "?"
            return f"{product_url}{sep}partner={self.affiliate_id}"
        return product_url

    def parse_popular(self, category: str = "", limit: int = 50) -> list[Product]:
        products = []
        for cat_name, cat_id in WB_CATEGORIES.items():
            if category and cat_name != category:
                continue
            try:
                items = self._fetch_catalog(cat_id, cat_name, limit // len(WB_CATEGORIES))
                products.extend(items)
            except Exception as e:
                logger.error(f"[WB] Error parsing category {cat_name}: {e}")
        return products[:limit]

    def parse_deals(self, min_discount: int = 20, limit: int = 50) -> list[Product]:
        products = []
        for cat_name, cat_id in WB_CATEGORIES.items():
            try:
                items = self._fetch_catalog(cat_id, cat_name, limit, sale=True)
                discounted = [p for p in items if p.discount_percent >= min_discount]
                products.extend(discounted)
            except Exception as e:
                logger.error(f"[WB] Error parsing deals in {cat_name}: {e}")
        products.sort(key=lambda p: p.discount_percent, reverse=True)
        return products[:limit]

    def _fetch_catalog(self, cat_id: int, cat_name: str, limit: int,
                       sale: bool = False) -> list[Product]:
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": "-1257786",
            "sort": "sale" if sale else "popular",
            "page": 1,
            "cat": cat_id,
            "resultset": "catalog",
        }
        resp = self._get(self.CATALOG_API, params=params)
        data = resp.json()
        products_raw = data.get("data", {}).get("products", [])
        products = []
        for item in products_raw[:limit]:
            p = self._parse_product_item(item, cat_name)
            if p:
                products.append(p)
        return products

    def _parse_product_item(self, item: dict, category: str) -> Optional[Product]:
        try:
            product_id = str(item.get("id", ""))
            name = item.get("name", "")
            brand = item.get("brand", "")
            price_sale = item.get("salePriceU", 0) / 100 if item.get("salePriceU") else 0
            price_original = item.get("priceU", 0) / 100 if item.get("priceU") else 0
            if price_original <= 0 or price_sale <= 0:
                return None
            discount = int((1 - price_sale / price_original) * 100) if price_original > 0 else 0
            rating = item.get("reviewRating", 0) or 0
            reviews = item.get("feedbacks", 0) or 0
            vol = item.get("vol", 0)
            part = item.get("part", 0)
            img_url = self._build_image_url(product_id, vol, part)
            url = f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx"
            return Product(
                marketplace=Marketplace.WB,
                external_id=product_id,
                name=f"{brand} {name}".strip(),
                url=url,
                referral_url=self.build_referral_url(url),
                image_url=img_url,
                price_original=price_original,
                price_sale=price_sale,
                discount_percent=discount,
                rating=rating,
                reviews_count=reviews,
                category=category,
                brand=brand,
            )
        except Exception as e:
            logger.debug(f"[WB] Skip product: {e}")
            return None

    @staticmethod
    def _build_image_url(product_id: str, vol: int, part: int) -> str:
        pid = int(product_id)
        basket = vol // 100000
        if basket <= 143:
            host = "//basket-01.wbbasket.ru"
        elif basket <= 287:
            host = "//basket-02.wbbasket.ru"
        elif basket <= 431:
            host = "//basket-03.wbbasket.ru"
        elif basket <= 719:
            host = "//basket-04.wbbasket.ru"
        elif basket <= 1007:
            host = "//basket-05.wbbasket.ru"
        elif basket <= 1061:
            host = "//basket-06.wbbasket.ru"
        elif basket <= 1115:
            host = "//basket-07.wbbasket.ru"
        elif basket <= 1169:
            host = "//basket-08.wbbasket.ru"
        elif basket <= 1223:
            host = "//basket-09.wbbasket.ru"
        elif basket <= 1367:
            host = "//basket-10.wbbasket.ru"
        else:
            host = "//basket-11.wbbasket.ru"
        return f"https:{host}/vol{vol}/part{part}/{product_id}/images/big/1.webp"

    def search(self, query: str, limit: int = 20) -> list[Product]:
        params = {
            "appType": 1,
            "curr": "rub",
            "dest": "-1257786",
            "query": query,
            "resultset": "catalog",
            "sort": "popular",
        }
        resp = self._get(self.SEARCH_API, params=params)
        data = resp.json()
        products_raw = data.get("data", {}).get("products", [])
        return [p for item in products_raw[:limit]
                if (p := self._parse_product_item(item, "search"))]
