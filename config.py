"""Конфигурация системы marketplace-ref-bot."""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHANNEL_ID: str = os.getenv("TELEGRAM_CHANNEL_ID", "")
    ADMIN_USER_IDS: list[int] = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
    ])

    # Реферальные параметры маркетплейсов
    WB_AFFILIATE_ID: str = os.getenv("WB_AFFILIATE_ID", "")
    OZON_AFFILIATE_ID: str = os.getenv("OZON_AFFILIATE_ID", "")
    ALIEXPRESS_AFFILIATE_ID: str = os.getenv("ALIEXPRESS_AFFILIATE_ID", "")
    YANDEX_MARKET_AFFILIATE_ID: str = os.getenv("YANDEX_MARKET_AFFILIATE_ID", "")

    # Настройки постинга
    POSTS_PER_DAY: int = int(os.getenv("POSTS_PER_DAY", "4"))
    MIN_DISCOUNT_PERCENT: int = int(os.getenv("MIN_DISCOUNT_PERCENT", "20"))
    POST_INTERVAL_HOURS: float = float(os.getenv("POST_INTERVAL_HOURS", "4"))
    MAX_PRODUCTS_PER_POST: int = int(os.getenv("MAX_PRODUCTS_PER_POST", "3"))

    # База данных
    DB_PATH: str = os.getenv("DB_PATH", "data/marketplace.db")

    # Настройки трекинга
    TRACKER_BASE_URL: str = os.getenv("TRACKER_BASE_URL", "")

    # Настройки парсинга
    PARSING_CATEGORIES: list[str] = field(default_factory=lambda: [
        "electronics", "home", "beauty", "clothing", "sports", "toys", "food",
    ])
    MAX_PRODUCTS_PER_PARSE: int = int(os.getenv("MAX_PRODUCTS_PER_PARSE", "50"))

    # Язык постов
    POST_LANGUAGE: str = "ru"

    @property
    def is_configured(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHANNEL_ID)


config = Config()
