"""Telegram-бот управления: Яндекс Маркет → Дзен."""
import logging
import threading

import telebot
from telebot import types

from config import config
from database import Database

logger = logging.getLogger(__name__)

# Хвост, который добавляется к финальному сообщению после публикации (или
# неудачи) — напоминает, что бот "отключился" и для следующего запроса нужно
# заново нажать /start.
_OFF_NOTICE = "Бот отключился — когда понадобится снова, нажмите /start."


def create_bot(db: Database) -> telebot.TeleBot:
    if config.TELEGRAM_API_URL:
        telebot.apihelper.API_URL = config.TELEGRAM_API_URL.rstrip("/") + "/bot{0}/{1}"
        # Путь Яндекс.Облако -> Cloudflare (см. TELEGRAM_API_URL в config.py)
        # ощутимо "дырявый" — до ~30% запросов не проходят с первой попытки
        # (не блокировка, а просто потери на маршруте). apihelper по
        # умолчанию не ретраит вообще, а падает с одной ошибки — из-за чего
        # наш собственный цикл перезапуска в main.py отваливался на каждую
        # мелкую сетевую потерю. Включаем встроенный ретрай telebot: с 30%
        # успеха на попытку 15 попыток дают уже >99.5% шанс достучаться.
        telebot.apihelper.RETRY_ON_ERROR = True
        telebot.apihelper.CONNECT_TIMEOUT = 8
    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, parse_mode="HTML")

    def is_admin(user_id: int) -> bool:
        return user_id in config.ADMIN_USER_IDS

    # Чаты, которые сейчас "включены" и ждут от пользователя категорию/запрос
    # (после /start, до того как запрос принят в обработку). Свободный текст
    # вне этого состояния бот молча игнорирует — это и есть реализация
    # "нажал /start -> бот спросил, о чём написать -> после публикации сам
    # отключился, для следующего раза снова нужен /start".
    awaiting_query: set = set()

    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message):
        awaiting_query.add(message.chat.id)
        bot.reply_to(
            message,
            "\U0001F44B <b>Яндекс Маркет → Дзен Бот</b>\n\n"
            "О чём хотите написать? Пришлите запрос \u2014 например: "
            "<i>шапка</i>, <i>кофемашина</i>, <i>детские коляски</i>. "
            "Найду товар на Яндекс Маркете, напишу статью и опубликую в "
            "Дзен с маркировкой рекламы (erid).\n\n"
            "Нужна подборка с ценами, рейтингами и плюсами-минусами из "
            "отзывов \u2014 попросите явно: <i>топ-5 наушников</i>, "
            "<i>лучшие кофемашины</i>, <i>подборка колясок</i>.\n\n"
            "После публикации бот отключается \u2014 когда понадобится "
            "снова, просто нажмите /start ещё раз.\n\n"
            "Остальные команды \u2014 /help.",
            parse_mode="HTML",
        )

    @bot.message_handler(commands=["help"])
    def cmd_help(message: types.Message):
        text = (
            "<b>\U0001F4D6 Как пользоваться:</b>\n\n"
            "1. Нажмите /start.\n"
            "2. Напишите, о чём статья — что угодно, не только электроника:\n"
            "   • <i>шапка</i>, <i>кофемашина</i> — статья про сам предмет "
            "с фото и ссылкой;\n"
            "   • <i>топ-5 наушников</i>, <i>лучшие пылесосы</i>, "
            "<i>подборка колясок</i> — подборка товаров с ценами, "
            "рейтингами и плюсами-минусами из реальных отзывов покупателей.\n"
            "3. Бот опубликует статью в Дзен с маркировкой рекламы (erid), "
            "после чего отключится — для следующего раза снова нужен "
            "/start.\n\n"
            "<b>\U0001F4CA Аналитика:</b>\n"
            "/stats — Статистика\n"
            "/top — Топ товаров по кликам\n\n"
            "<b>⚙️ Прочее:</b>\n"
            "/cookies — Обновить cookies Дзена"
        )
        bot.reply_to(message, text, parse_mode="HTML")

    @bot.message_handler(commands=["stats"])
    def cmd_stats(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        total = db.get_product_count()
        mp_stats = db.get_marketplace_stats()
        daily = db.get_daily_stats(7)

        lines = ["<b>\U0001F4CA Статистика</b>\n"]
        lines.append(f"\U0001F4E6 Товаров в базе: <b>{total}</b>\n")

        for s in mp_stats:
            lines.append(
                f"  \u2022 {s['marketplace'].upper()}: {s['total_products']} товаров, "
                f"опубликовано {s['posted']}, ср. скидка {s['avg_discount']:.0f}%"
            )

        total_clicks = sum(d["clicks"] for d in daily)
        total_posts = sum(d["posts"] for d in daily)
        lines.append(f"\n\U0001F4C4 За 7 дней: {total_clicks} кликов, {total_posts} постов")

        # Статус ОРИ
        if config.ORD_TOKEN:
            lines.append(f"\n\u2705 ОРИ: настроен")
        else:
            lines.append(f"\n\u274c ОРИ: не настроен")

        bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

    @bot.message_handler(commands=["top"])
    def cmd_top(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        top = db.get_top_products(5)
        if not top:
            bot.reply_to(message, "\U0001F4CA Пока нет данных.")
            return
        lines = ["<b>\U0001F3C6 Топ товаров:</b>\n"]
        for i, p in enumerate(top, 1):
            lines.append(f"{i}. {p['name'][:50]} \u2014 {p['total_clicks']} кликов")
        bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

    @bot.message_handler(commands=["cookies"])
    def cmd_cookies(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        bot.reply_to(
            message,
            "Для обновления cookies Дзена запустите локально:\n"
            "<code>python -c \"from dzen_poster import save_dzen_cookies; save_dzen_cookies()\"</code>",
            parse_mode="HTML",
        )

    def _run_category_post(chat_id: int, query: str):
        """Фоновый воркер: поиск по запросу → статья → erid → публикация в
        Дзен. Запускается отдельным потоком, чтобы long polling бота не
        блокировался на несколько минут, пока крутится Playwright.

        Что именно публиковать, решает scheduler.run_post_cycle_for_query по
        тексту запроса: "шапка" — обычная статья про предмет, "топ-5 шапок" —
        подборка с ценами, рейтингами и плюсами/минусами из отзывов.
        """
        try:
            from scheduler import run_post_cycle_for_query
            success, reason = run_post_cycle_for_query(db, query)
            if success:
                bot.send_message(
                    chat_id,
                    f"\u2705 Статья по запросу «{query}» опубликована в Дзен "
                    f"(с маркировкой рекламы erid)!\n\n{_OFF_NOTICE}",
                )
            else:
                bot.send_message(
                    chat_id,
                    f"\u26a0\ufe0f Не получилось опубликовать по запросу «{query}»: "
                    f"{reason}.\n\nПодробности \u2014 в bot.log.\n\n{_OFF_NOTICE}",
                )
        except Exception as e:
            logger.error(f"[Bot] Category post error for {query!r}: {e}")
            bot.send_message(chat_id, f"\u274c Ошибка: {e}\n\n{_OFF_NOTICE}")

    def _handle_category_request(message: types.Message, query: str):
        query = query.strip()
        if not query:
            return
        # Текст ожидания честно отражает выбранный режим — иначе на запрос
        # "шапка" бот обещал бы топ-5, которого не будет.
        from scheduler import wants_top_selection, extract_top_n

        if wants_top_selection(query):
            what = f"беру топ-{extract_top_n(query)} и готовлю подборку"
        else:
            what = "готовлю статью"
        bot.reply_to(
            message,
            f"\U0001F50D Ищу «{query}» на Яндекс Маркете, {what} "
            f"для Дзена (с получением erid) \u2014 это займёт пару минут...",
        )
        threading.Thread(
            target=_run_category_post,
            args=(message.chat.id, query),
            daemon=True,
        ).start()

    # Свободный текст без "/" в начале — трактуем как категорию/запрос для
    # поиска на Яндекс Маркете, но ТОЛЬКО пока бот "включён" (после /start и
    # до того, как запрос принят в обработку) — иначе бот "отключён" и молча
    # игнорирует случайные сообщения. Единственный способ включить бота —
    # команда /start, отдельной команды для поиска (раньше была /find)
    # больше нет. Регистрируется последним: pyTelegramBotAPI проверяет
    # обработчики по порядку и выполняет первый подошедший, так что все
    # команды выше (/start, /stats и т.д.) перехватываются раньше.
    @bot.message_handler(
        func=lambda m: m.content_type == "text" and not m.text.startswith("/")
    )
    def handle_free_text(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        if message.chat.id not in awaiting_query:
            return
        awaiting_query.discard(message.chat.id)
        _handle_category_request(message, message.text)

    return bot
