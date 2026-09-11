"""Модели данных для marketplace-ref-bot."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Marketplace(str, Enum):
    WB = "wb"
    OZON = "ozon"
    ALIEXPRESS = "aliexpress"
    YANDEX_MARKET = "yandex_market"

    @property
    def display_name(self) -> str:
        names = {
            "wb": "Wildberries",
            "ozon": "Ozon",
            "aliexpress": "AliExpress",
            "yandex_market": "Яндекс Маркет",
        }
        return names[self.value]

    @property
    def emoji(self) -> str:
        emojis = {
            "wb": "\U0001F7E5",
            "ozon": "\U0001F7E3",
            "aliexpress": "\U0001F7E2",
            "yandex_market": "\U0001F7E1",
        }
        return emojis[self.value]


@dataclass
class Product:
    id: Optional[int] = None
    marketplace: Marketplace = Marketplace.WB
    external_id: str = ""
    name: str = ""
    url: str = ""
    referral_url: str = ""
    image_url: str = ""
    price_original: float = 0.0
    price_sale: float = 0.0
    discount_percent: int = 0
    rating: float = 0.0
    reviews_count: int = 0
    category: str = ""
    brand: str = ""
    is_posted: bool = False
    post_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def savings(self) -> float:
        return self.price_original - self.price_sale

    @property
    def price_original_fmt(self) -> str:
        return f"{self.price_original:,.0f}".replace(",", " ")

    @property
    def price_sale_fmt(self) -> str:
        return f"{self.price_sale:,.0f}".replace(",", " ")


@dataclass
class Post:
    id: Optional[int] = None
    channel_id: str = ""
    message_id: Optional[int] = None
    content: str = ""
    product_ids: list[int] = field(default_factory=list)
    posted_at: Optional[datetime] = None
    is_scheduled: bool = False
    scheduled_at: Optional[datetime] = None


@dataclass
class Click:
    id: Optional[int] = None
    product_id: int = 0
    user_id: Optional[int] = None
    ref_hash: str = ""
    ip_hash: str = ""
    user_agent: str = ""
    clicked_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DailyStats:
    date: str = ""
    clicks: int = 0
    posts: int = 0
    products_added: int = 0
    top_product_id: Optional[int] = None
    top_marketplace: Optional[str] = None
