"""Конфигурация: Яндекс Маркет + Яндекс Дистрибуция + Дзен."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# .env нигде в проекте раньше не подключался — os.getenv() видел только то, что
# реально экспортировано в shell, а не то, что лежит в файле .env. load_dotenv()
# подтягивает переменные из .env в окружение процесса до того, как ниже
# начнётся чтение через os.getenv().
load_dotenv()


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

    # Groq (бесплатный API) — генерация живого текста статьи вместо сухого
    # шаблона. Ключ: console.groq.com -> API Keys. Если не задан, используется
    # запасной шаблонный текст (см. content_generator.py).
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

    # Дзен
    DZEN_CHANNEL_URL: str = os.getenv("DZEN_CHANNEL_URL", "")
    DZEN_COOKIES_PATH: str = os.getenv("DZEN_COOKIES_PATH", "data/dzen_cookies.json")
    # Отдельная авторизация — куки от Дзена сюда не подходят (проверено: это
    # разные области Яндекс Паспорта). Нужен отдельный один раз выполненный
    # вход через save_distribution_cookies.py.
    DISTRIBUTION_COOKIES_PATH: str = os.getenv("DISTRIBUTION_COOKIES_PATH", "data/distribution_cookies.json")
    # Ссылка на любой (в т.ч. старый) черновик в Дзен-студии — сама она для
    # публикации больше не используется, но из неё берётся id канала, чтобы
    # зайти в Студию и создать НОВЫЙ черновик через "+" на каждый запуск
    # (см. dzen_poster._extract_channel_id/_create_new_draft).
    DZEN_DRAFT_URL: str = os.getenv("DZEN_DRAFT_URL", "")

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
