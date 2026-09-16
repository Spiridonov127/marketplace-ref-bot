"""MAX-бот управления: Яндекс Маркет → Дзен.

Замена Telegram-бота (см. bot/__init__.py): MAX — российский мессенджер,
его Bot API (platform-api2.max.ru) не блокируется с российских IP, в
отличие от api.telegram.org. Поэтому здесь не нужно ничего из того, что
понадобилось для Telegram на ВПС — ни Cloudflare-релей, ни агрессивные
ретраи на дырявую сеть: обычный long polling работает напрямую.

Схема API восстановлена по официальной документации (dev.max.ru/docs-api) —
она на момент написания неполная в деталях объекта Update, поэтому
_handle_update() логирует сырой JSON при неожиданной структуре, чтобы можно
было быстро подправить разбор по факту первого реального апдейта.
"""
import logging
import threading
import time

import requests

from config import config
from database import Database

logger = logging.getLogger(__name__)

API_URL = "https://platform-api2.max.ru"

_OFF_NOTICE = "Бот отключился — когда понадобится снова, нажмите /start."

_START_TEXT = (
    "\U0001F44B Яндекс Маркет → Дзен Бот\n\n"
    "О чём хотите написать? Пришлите запрос — например: шапка, "
    "кофемашина, детские коляски. Найду товар на Яндекс Маркете, "
    "напишу статью и опубликую в Дзен с маркировкой рекламы (erid).\n\n"
    "Нужна подборка с ценами, рейтингами и плюсами-минусами из отзывов — "
    "попросите явно: топ-5 наушников, лучшие кофемашины, подборка "
    "колясок.\n\n"
    "После публикации бот отключается — когда понадобится снова, просто "
    "нажмите /start ещё раз.\n\n"
    "Остальные команды — /help."
)

_HELP_TEXT = (
    "\U0001F4D6 Как пользоваться:\n\n"
    "1. Нажмите /start.\n"
    "2. Напишите, о чём статья — что угодно, не только электроника:\n"
    "   • шапка, кофемашина — статья про сам предмет с фото и ссылкой;\n"
    "   • топ-5 наушников, лучшие пылесосы, подборка колясок — подборка "
    "товаров с ценами, рейтингами и плюсами-минусами из реальных отзывов "
    "покупателей.\n"
    "3. Бот опубликует статью в Дзен с маркировкой рекламы (erid), после "
    "чего отключится — для следующего раза снова нужен /start.\n\n"
    "\U0001F4CA Аналитика:\n"
    "/stats — Статистика\n"
    "/top — Топ товаров по кликам\n\n"
    "⚙️ Прочее:\n"
    "/cookies — Обновить cookies Дзена"
)


class MaxBot:
    def __init__(self, db: Database):
        self.db = db
        self.token = config.MAX_BOT_TOKEN
        self.session = requests.Session()
        # Аналог awaiting_query в Telegram-версии — чаты, которые сейчас
        # "включены" и ждут от пользователя категорию/запрос после /start.
        self.awaiting_query: set = set()

    def _headers(self) -> dict:
        return {"Authorization": self.token}

    def _get(self, method: str, **params):
        r = self.session.get(
            f"{API_URL}/{method}", headers=self._headers(), params=params, timeout=100
        )
        r.raise_for_status()
        return r.json()

    def _post(self, method: str, params: dict = None, json_body: dict = None):
        r = self.session.post(
            f"{API_URL}/{method}",
            headers=self._headers(),
            params=params or {},
            json=json_body or {},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def send_message(self, chat_id, text: str):
        try:
            self._post("messages", params={"chat_id": chat_id}, json_body={"text": text})
        except requests.RequestException as e:
            logger.error(f"[MaxBot] Не удалось отправить сообщение в чат {chat_id}: {e}")

    def is_admin(self, user_id) -> bool:
        return user_id in config.MAX_ADMIN_USER_IDS

    def _stats_text(self) -> str:
        total = self.db.get_product_count()
        mp_stats = self.db.get_marketplace_stats()
        daily = self.db.get_daily_stats(7)

        lines = ["\U0001F4CA Статистика\n"]
        lines.append(f"\U0001F4E6 Товаров в базе: {total}\n")
        for s in mp_stats:
            lines.append(
                f"  • {s['marketplace'].upper()}: {s['total_products']} товаров, "
                f"опубликовано {s['posted']}, ср. скидка {s['avg_discount']:.0f}%"
            )
        total_clicks = sum(d["clicks"] for d in daily)
        total_posts = sum(d["posts"] for d in daily)
        lines.append(f"\n\U0001F4C4 За 7 дней: {total_clicks} кликов, {total_posts} постов")
        lines.append(f"\n{'✅ ОРИ: настроен' if config.ORD_TOKEN else '❌ ОРИ: не настроен'}")
        return "\n".join(lines)

    def _top_text(self) -> str:
        top = self.db.get_top_products(5)
        if not top:
            return "\U0001F4CA Пока нет данных."
        lines = ["\U0001F3C6 Топ товаров:\n"]
        for i, p in enumerate(top, 1):
            lines.append(f"{i}. {p['name'][:50]} — {p['total_clicks']} кликов")
        return "\n".join(lines)

    def _run_category_post(self, chat_id, query: str):
        """Фоновый воркер — см. bot/__init__.py._run_category_post, логика та же."""
        try:
            from scheduler import run_post_cycle_for_query
            success, reason = run_post_cycle_for_query(self.db, query)
            if success:
                self.send_message(
                    chat_id,
                    f"✅ Статья по запросу «{query}» опубликована в Дзен "
                    f"(с маркировкой рекламы erid)!\n\n{_OFF_NOTICE}",
                )
            else:
                self.send_message(
                    chat_id,
                    f"⚠️ Не получилось опубликовать по запросу «{query}»: "
                    f"{reason}.\n\nПодробности — в bot.log.\n\n{_OFF_NOTICE}",
                )
        except Exception as e:
            logger.error(f"[MaxBot] Category post error for {query!r}: {e}")
            self.send_message(chat_id, f"❌ Ошибка: {e}\n\n{_OFF_NOTICE}")

    def _handle_category_request(self, chat_id, query: str):
        query = query.strip()
        if not query:
            return
        from scheduler import wants_top_selection, extract_top_n

        if wants_top_selection(query):
            what = f"беру топ-{extract_top_n(query)} и готовлю подборку"
        else:
            what = "готовлю статью"
        self.send_message(
            chat_id,
            f"\U0001F50D Ищу «{query}» на Яндекс Маркете, {what} для Дзена "
            f"(с получением erid) — это займёт пару минут...",
        )
        threading.Thread(
            target=self._run_category_post, args=(chat_id, query), daemon=True
        ).start()

    def _handle_update(self, update: dict):
        if update.get("update_type") != "message_created":
            return
        message = update.get("message") or {}
        body = message.get("body") or {}
        text = (body.get("text") or "").strip()
        sender = message.get("sender") or {}
        user_id = sender.get("user_id")
        recipient = message.get("recipient") or {}
        chat_id = recipient.get("chat_id")

        if chat_id is None or user_id is None:
            logger.warning(f"[MaxBot] Не смог разобрать update, пропускаю: {update}")
            return

        if not config.MAX_ADMIN_USER_IDS:
            # Первый запуск: MAX_ADMIN_USER_IDS ещё не заполнен — чтобы не
            # заставлять гадать свой user_id, просто печатаем его в лог при
            # любом входящем сообщении, пока список пуст.
            logger.info(
                f"[MaxBot] MAX_ADMIN_USER_IDS не задан — ваш user_id: {user_id} "
                f"(впишите его в .env, чтобы бот вас узнавал)"
            )

        if text == "/start":
            self.awaiting_query.add(chat_id)
            self.send_message(chat_id, _START_TEXT)
            return
        if text == "/help":
            self.send_message(chat_id, _HELP_TEXT)
            return
        if text == "/stats":
            if self.is_admin(user_id):
                self.send_message(chat_id, self._stats_text())
            return
        if text == "/top":
            if self.is_admin(user_id):
                self.send_message(chat_id, self._top_text())
            return
        if text == "/cookies":
            if self.is_admin(user_id):
                self.send_message(
                    chat_id,
                    "Для обновления cookies Дзена запустите локально:\n"
                    'python -c "from dzen_poster import save_dzen_cookies; save_dzen_cookies()"',
                )
            return
        if text.startswith("/"):
            return
        if not self.is_admin(user_id):
            return
        if chat_id not in self.awaiting_query:
            return
        self.awaiting_query.discard(chat_id)
        self._handle_category_request(chat_id, text)

    def infinity_polling(self, **_ignored_telebot_kwargs):
        """Аналог telebot.infinity_polling — вызывается из main.py в таком же
        цикле-обёртке с перезапуском при сбоях, так что здесь достаточно
        просто дать исключению всплыть наружу при затяжной сетевой проблеме.
        Принимает и игнорирует kwargs вроде timeout/long_polling_timeout —
        main.py вызывает bot.infinity_polling(...) одинаково для обоих
        ботов, а у MAX свой long-polling таймаут задан ниже через API.
        """
        marker = None
        logger.info("[MaxBot] Опрос запущен")
        while True:
            params = {"timeout": 90, "limit": 100}
            if marker is not None:
                params["marker"] = marker
            data = self._get("updates", **params)
            for update in data.get("updates", []):
                try:
                    self._handle_update(update)
                except Exception:
                    logger.exception(f"[MaxBot] Ошибка обработки update: {update}")
            new_marker = data.get("marker")
            if new_marker is not None:
                marker = new_marker


def create_bot(db: Database) -> MaxBot:
    return MaxBot(db)
