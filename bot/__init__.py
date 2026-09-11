"""Telegram-бот управления: Яндекс Маркет → Дзен."""
import logging
import json
from typing import Optional

import telebot
from telebot import types

from config import config
from database import Database
from content_generator import generate_dzen_article, generate_dzen_post_text

logger = logging.getLogger(__name__)


def create_bot(db: Database) -> telebot.TeleBot:
    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, parse_mode="HTML")

    def is_admin(user_id: int) -> bool:
        return user_id in config.ADMIN_USER_IDS

    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message):
        bot.reply_to(
            message,
            "\U0001F44B <b>Яндекс Маркет → Дзен Бот</b>\n\n"
            "Система автоматизации: парсинг Яндекс Маркета, "
            "генерация статей с CPA-ссылками, публикация в Дзен.\n\n"
            "<b>Команды:</b>\n"
            "/parse \u2014 Парсинг Яндекс Маркета\n"
            "/post \u2014 Сгенерировать и опубликовать\n"
            "/draft \u2014 Сгенерировать черновик\n"
            "/stats \u2014 Статистика\n"
            "/cookies \u2014 Обновить cookies Дзена\n"
            "/help \u2014 Помощь",
            parse_mode="HTML",
        )

    @bot.message_handler(commands=["help"])
    def cmd_help(message: types.Message):
        text = (
            "<b>\U0001F4D6 Команды:</b>\n\n"
            "<b>\U0001F4E1 Парсинг:</b>\n"
            "/parse \u2014 Запустить парсинг YM\n\n"
            "<b>\U0001F4DD Постинг:</b>\n"
            "/post \u2014 Опубликовать статью в Дзен\n"
            "/draft \u2014 Сгенерировать черновик\n\n"
            "<b>\U0001F4CA Аналитика:</b>\n"
            "/stats \u2014 Статистика\n"
            "/top \u2014 Топ товаров\n\n"
            "<b>\U2699\ufe0f Настройки:</b>\n"
            "/setposts N \u2014 Постов в день\n"
            "/setdiscount N \u2014 Мин. скидка (%)\n"
            "/cookies \u2014 Обновить cookies Дзена"
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

    @bot.message_handler(commands=["parse"])
    def cmd_parse(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        bot.reply_to(message, "\U0001F680 Парсинг Яндекс Маркета...")
        try:
            from scheduler import run_parse_cycle
            count = run_parse_cycle(db)
            bot.reply_to(message, f"\u2705 Найдено: <b>{count}</b> товаров", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Parse error: {e}")
            bot.reply_to(message, f"\u274c Ошибка: {e}")

    @bot.message_handler(commands=["post"])
    def cmd_post(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        bot.reply_to(message, "\U0001F4DD Генерация статьи для Дзена...")
        try:
            from scheduler import run_dzen_post_cycle
            success = run_dzen_post_cycle(db)
            if success:
                bot.reply_to(message, "\u2705 Статья опубликована в Дзен!")
            else:
                bot.reply_to(message, "\u26a0\ufe0f Черновик сохранён в data/drafts/")
        except Exception as e:
            logger.error(f"Post error: {e}")
            bot.reply_to(message, f"\u274c Ошибка: {e}")

    @bot.message_handler(commands=["draft"])
    def cmd_draft(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        products = db.get_unposted_products(limit=3, min_discount=config.MIN_DISCOUNT_PERCENT)
        if not products:
            bot.reply_to(message, "\u26a0\ufe0f Нет товаров. Запустите /parse")
            return

        from referral_builder import build_ym_cpa_link
        for p in products:
            p.referral_url = build_ym_cpa_link(p.url)

        title, body = generate_dzen_article(products)
        text = generate_dzen_post_text(products)

        # Отправляем заголовок и текст
        bot.reply_to(
            message,
            f"<b>Заголовок:</b>\n{title}\n\n"
            f"<b>Текст (скопируй для Дзена):</b>\n\n{text}",
            parse_mode="HTML",
        )

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

    @bot.message_handler(commands=["setposts"])
    def cmd_setposts(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        try:
            n = int(message.text.split()[1])
            config.POSTS_PER_DAY = n
            bot.reply_to(message, f"\u2705 Постов в день: {n}")
        except (IndexError, ValueError):
            bot.reply_to(message, "\u274c Формат: /setposts 2")

    @bot.message_handler(commands=["setdiscount"])
    def cmd_setdiscount(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        try:
            n = int(message.text.split()[1])
            config.MIN_DISCOUNT_PERCENT = n
            bot.reply_to(message, f"\u2705 Мин. скидка: {n}%")
        except (IndexError, ValueError):
            bot.reply_to(message, "\u274c Формат: /setdiscount 20")

    return bot
