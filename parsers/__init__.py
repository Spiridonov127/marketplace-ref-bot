"""Базовый класс для парсеров маркетплейсов."""
import logging
import time
import random
from abc import ABC, abstractmethod

import requests
from bs4 import BeautifulSoup

from models import Product, Marketplace

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    marketplace: Marketplace
    base_url: str

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    def __init__(self, affiliate_id: str = ""):
        self.affiliate_id = affiliate_id
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _get(self, url: str, params: dict = None, **kwargs) -> requests.Response:
        delay = random.uniform(1.0, 3.0)
        time.sleep(delay)
        try:
            resp = self.session.get(url, params=params, timeout=30, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.warning(f"[{self.marketplace.value}] Request failed: {e}")
            raise

    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def build_referral_url(self, product_url: str) -> str:
        if not self.affiliate_id:
            return product_url
        return self._build_referral(product_url)

    @abstractmethod
    def _build_referral(self, product_url: str) -> str:
        pass

    @abstractmethod
    def parse_popular(self, category: str = "", limit: int = 50) -> list[Product]:
        pass

    @abstractmethod
    def parse_deals(self, min_discount: int = 20, limit: int = 50) -> list[Product]:
        pass
