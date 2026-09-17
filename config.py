"""Конфигурация: Яндекс Маркет + Яндекс Дистрибуция + Дзен."""
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote, urlsplit

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
    # С российских IP (в т.ч. наш VPS в Яндекс.Облаке — он нужен, чтобы
    # Яндекс Маркет не показывал капчу) api.telegram.org не отвечает —
    # Telegram заблокирован на уровне провайдера. Если задано, запросы к
    # Bot API идут через прокси на Cloudflare Worker (не блокируется),
    # см. cloudflare-worker/src/worker.js — маршрут /bot<token>/<method>.
    TELEGRAM_API_URL: str = os.getenv("TELEGRAM_API_URL", "")

    # Обратная сторона той же проблемы: Яндекс Маркет капчит датацентровые
    # IP, в т.ч. сам Yandex Cloud (проверено на бою — капча на запросе
    # «Часы» с этой же ВМ). Единственный "тихий" IP — домашний. Поэтому
    # трафик именно к market.yandex.ru заворачивается в SOCKS5-туннель до
    # домашнего компьютера (см. deploy/home-proxy-tunnel.service — reverse
    # ssh -R с домашней машины поднимает SOCKS5 на localhost:1080 этой ВМ).
    # На Дзен (dzen_poster.py) это не распространяется — там капчи не было.
    # Полная форма: socks5://user:pass@host:port или http://user:pass@host:port
    # (например, купленный резидентный/мобильный прокси). Логин/пароль
    # вынимаются в YM_PROXY (см. ниже) — Chromium не умеет авторизовываться
    # на SOCKS5-прокси на уровне браузера (Playwright падает с "Browser does
    # not support socks5 proxy authentication"), поэтому для прокси с логином
    #/паролем нужен именно http://, а не socks5:// — проверено на бою: тот
    # же прокси по HTTP открыл Маркет без капчи, а по SOCKS5 не запустился
    # вообще.
    YM_PROXY_URL: str = os.getenv("YM_PROXY_URL", "")
    # Анонимные (без входа) автоматизированные запросы к Маркету капчатся
    # заметно чаще, чем запросы от вошедшего в аккаунт браузера — обычная
    # практика антибот-систем доверять авторизованным сессиям больше.
    # Разовый вход через scripts/save_market_cookies.py (как и для Дзена и
    # Дистрибуции — своя, отдельная авторизация Яндекс Паспорта).
    MARKET_COOKIES_PATH: str = os.getenv("MARKET_COOKIES_PATH", "data/market_cookies.json")
    ADMIN_USER_IDS: list[int] = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()
    ])

    # MAX (российский мессенджер) — замена Telegram для управления ботом на
    # ВПС: platform-api2.max.ru не блокируется с российских IP, поэтому не
    # нужны ни Cloudflare-релей, ни ретраи на дырявую сеть, которые
    # понадобились для Telegram (см. TELEGRAM_API_URL выше). Если задан
    # MAX_BOT_TOKEN — main.py использует MAX вместо Telegram, см.
    # bot/max_bot.py. Токен создаётся в самом MAX через диалог с @MasterBot.
    MAX_BOT_TOKEN: str = os.getenv("MAX_BOT_TOKEN", "")
    MAX_ADMIN_USER_IDS: list[int] = field(default_factory=lambda: [
        int(x) for x in os.getenv("MAX_ADMIN_USER_IDS", "").split(",") if x.strip()
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
        return bool(
            (self.TELEGRAM_BOT_TOKEN or self.MAX_BOT_TOKEN)
            and self.YANDEX_DISTRIBUTION_PARTNER_ID
        )

    @property
    def YM_PROXY(self) -> Optional[dict]:
        """Готовый proxy-словарь для playwright.chromium.launch(proxy=...),
        с логином/паролем, вынутыми из YM_PROXY_URL (см. комментарий там).
        None, если YM_PROXY_URL не задан."""
        if not self.YM_PROXY_URL:
            return None
        parts = urlsplit(self.YM_PROXY_URL)
        proxy = {"server": f"{parts.scheme}://{parts.hostname}:{parts.port}"}
        if parts.username:
            proxy["username"] = unquote(parts.username)
        if parts.password:
            proxy["password"] = unquote(parts.password)
        return proxy


config = Config()
