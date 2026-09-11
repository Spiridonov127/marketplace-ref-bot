"""Конфигурация: Яндекс Маркет + Яндекс Дистрибуция + Дзен."""
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # Telegram (для бота управления, не для постинга)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ADMIN_USER_IDS: list[int] = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
    ])

    # Яндекс Дистрибуция (CPA)
    YANDEX_DISTRIBUTION_PARTNER_ID: str = os.getenv("YANDEX_DISTRIBUTION_PARTNER_ID", "")
    YANDEX_DISTRIBUTION_API_KEY: str = os.getenv("YANDEX_DISTRIBUTION_API_KEY", "")

    # ОРД (Оператор рекламных данных) — рекламный идентификатор
    ORD_TOKEN: str = os.getenv("ORD_TOKEN", "")

    # Дзен
    DZEN_CHANNEL_URL: str = os.getenv("DZEN_CHANNEL_URL", "")
    DZEN_COOKIES_PATH: str = os.getenv("DZEN_COOKIES_PATH", "data/dzen_cookies.json")

    # Настройки постинга
    POSTS_PER_DAY: int = int(os.getenv("POSTS_PER_DAY", "2"))
    MIN_DISCOUNT_PERCENT: int = int(os.getenv("MIN_DISCOUNT_PERCENT", "20"))
    POST_INTERVAL_HOURS: float = float(os.getenv("POST_INTERVAL_HOURS", "8"))
    MAX_PRODUCTS_PER_POST: int = int(os.getenv("MAX_PRODUCTS_PER_POST", "3"))

    # База данных
    DB_PATH: str = os.getenv("DB_PATH", "data/marketplace.db")

    # Парсинг
    MAX_PRODUCTS_PER_PARSE: int = int(os.getenv("MAX_PRODUCTS_PER_PARSE", "50"))
    POST_LANGUAGE: str = "ru"

    @property
    def is_configured(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN and self.YANDEX_DISTRIBUTION_PARTNER_ID)


config = Config()
