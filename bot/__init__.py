"""Telegram-бот для управления каналом и отслеживания кликов."""
import logging
import json
from typing import Optional

import telebot
from telebot import types

from config import config
from database import Database
from content_generator import generate_post, generate_single_product_post

logger = logging.getLogger(__name__)


def create_bot(db: Database) -> telebot.TeleBot:
    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, parse_mode="HTML")

    def is_admin(user_id: int) -> bool:
        return user_id in config.ADMIN_USER_IDS

    @bot.message_handler(commands=["start"])
    def cmd_start(message: types.Message):
        bot.reply_to(
            message,
            "\U0001F44B <b>Привет!</b>\n\n"
            "\U0001F4CA Я бот для управления каналом скидок.\n\n"
            "<b>Команды:</b>\n"
            "/stats \u2014 Статистика\n"
            "/post \u2014 Опубликовать пост вручную\n"
            "/digest \u2014 Дайджест дня\n"
            "/search <query> \u2014 Поиск товаров\n"
            "/help \u2014 Помощь",
            parse_mode="HTML",
        )

    @bot.message_handler(commands=["help"])
    def cmd_help(message: types.Message):
        text = (
            "<b>\U0001F4D6 Команды бота:</b>\n\n"
            "<b>\U0001F4CA Аналитика:</b>\n"
            "/stats \u2014 Общая статистика\n"
            "/stats_clicks \u2014 Клики за 7 дней\n"
            "/top \u2014 Топ товаров по кликам\n\n"
            "<b>\U0001F4E2 Управление:</b>\n"
            "/post \u2014 Опубликовать 1 пост\n"
            "/digest \u2014 Дайджест лучших скидок\n"
            "/parse \u2014 Запустить парсинг\n\n"
            "<b>\U0001F50D Поиск:</b>\n"
            "/search <запрос> \u2014 Найти товар\n\n"
            "<b>\U2699\ufe0f Настройки:</b>\n"
            "/setposts <N> \u2014 Постов в день\n"
            "/setdiscount <N> \u2014 Мин. скидка (%)"
        )
        bot.reply_to(message, text, parse_mode="HTML")

    @bot.message_handler(commands=["stats"])
    def cmd_stats(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        total = db.get_product_count()
        mp_stats = db.get_marketplace_stats()
        daily = db.get_daily_stats(7)

        lines = ["<b>\U0001F4CA Статистика системы</b>\n"]
        lines.append(f"\U0001F4E6 Всего товаров: <b>{total}</b>\n")

        lines.append("<b>По маркетплейсам:</b>")
        for s in mp_stats:
            mp_name = s["marketplace"].upper()
            lines.append(
                f"  \u2022 {mp_name}: {s['total_products']} товаров, "
                f"опубликовано {s['posted']}, "
                f"ср. скидка {s['avg_discount']:.0f}%"
            )

        total_clicks = sum(d["clicks"] for d in daily)
        total_posts = sum(d["posts"] for d in daily)
        lines.append(f"\n\U0001F4C4 За 7 дней: <b>{total_clicks}</b> кликов, <b>{total_posts}</b> постов")

        bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

    @bot.message_handler(commands=["stats_clicks"])
    def cmd_stats_clicks(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        daily = db.get_daily_stats(7)
        if not daily:
            bot.reply_to(message, "\U0001F4CA Пока нет данных о кликах.")
            return
        lines = ["<b>\U0001F4C8 Клики за 7 дней:</b>\n"]
        for d in daily:
            bar = "\u2588" * min(d["clicks"], 30)
            lines.append(f"  {d['date']}: {d['clicks']} {bar}")
        bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

    @bot.message_handler(commands=["top"])
    def cmd_top(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        top = db.get_top_products(5)
        if not top:
            bot.reply_to(message, "\U0001F4CA Пока нет данных.")
            return
        lines = ["<b>\U0001F3C6 Топ товаров по кликам:</b>\n"]
        for i, p in enumerate(top, 1):
            lines.append(
                f"{i}. {p['name'][:50]} \u2014 {p['total_clicks']} кликов"
            )
        bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

    @bot.message_handler(commands=["post"])
    def cmd_post(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        products = db.get_unposted_products(
            limit=config.MAX_PRODUCTS_PER_POST,
            min_discount=config.MIN_DISCOUNT_PERCENT,
        )
        if not products:
            bot.reply_to(message, "\u26a0\ufe0f Нет товаров для публикации. Запустите /parse")
            return
        post_text = generate_post(products)
        try:
            sent = bot.send_message(
                config.TELEGRAM_CHANNEL_ID,
                post_text,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            db.mark_posted([p.id for p in products])
            db.record_post(
                config.TELEGRAM_CHANNEL_ID,
                sent.message_id,
                post_text,
                [p.id for p in products],
            )
            bot.reply_to(
                message,
                f"\u2705 Пост опубликован! Товаров: {len(products)}",
            )
        except Exception as e:
            logger.error(f"Post error: {e}")
            bot.reply_to(message, f"\u274c Ошибка: {e}")

    @bot.message_handler(commands=["digest"])
    def cmd_digest(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        from models import Marketplace
        top_by_mp = {}
        for mp in Marketplace:
            prods = db.get_unposted_products(limit=1, min_discount=15)
            if prods:
                top_by_mp[mp] = prods
        if not top_by_mp:
            bot.reply_to(message, "\u26a0\ufe0f Нет данных для дайджеста.")
            return
        from content_generator import generate_digest_post
        post_text = generate_digest_post(top_by_mp)
        try:
            sent = bot.send_message(
                config.TELEGRAM_CHANNEL_ID,
                post_text,
                parse_mode="HTML",
            )
            bot.reply_to(message, "\u2705 Дайджест опубликован!")
        except Exception as e:
            bot.reply_to(message, f"\u274c Ошибка: {e}")

    @bot.message_handler(commands=["search"])
    def cmd_search(message: types.Message):
        query = message.text.replace("/search", "").strip()
        if not query:
            bot.reply_to(message, "\U0001F50D Введите запрос: /search <товар>")
            return
        bot.reply_to(message, f"\U0001F50D Ищу: {query}...")
        # Search is delegated to the scheduler / run_pipeline
        bot.reply_to(
            message,
            f"\u2139\ufe0f Поиск по запросу '{query}' будет выполнен при следующем запуске парсера.\n"
            f"Используйте /parse для немед запуска.",
        )

    @bot.message_handler(commands=["parse"])
    def cmd_parse(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        bot.reply_to(message, "\U0001F680 Запуск парсинга...")
        try:
            from scheduler import run_parse_cycle
            count = run_parse_cycle(db)
            bot.reply_to(message, f"\u2705 Парсинг завершён! Найдено: <b>{count}</b> товаров", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Parse error: {e}")
            bot.reply_to(message, f"\u274c Ошибка парсинга: {e}")

    @bot.message_handler(commands=["setposts"])
    def cmd_setposts(message: types.Message):
        if not is_admin(message.from_user.id):
            return
        try:
            n = int(message.text.split()[1])
            config.POSTS_PER_DAY = n
            bot.reply_to(message, f"\u2705 Постов в день: {n}")
        except (IndexError, ValueError):
            bot.reply_to(message, "\u274c Формат: /setposts 4")

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

    # Обработка inline-кнопок (трекинг кликов)
    @bot.callback_query_handler(func=lambda call: call.data.startswith("click_"))
    def handle_click(call: types.CallbackQuery):
        try:
            product_id = int(call.data.split("_")[1])
            db.record_click(product_id, user_id=call.from_user.id)
            products = db.get_products_by_ids([product_id])
            if products:
                url = products[0].referral_url or products[0].url
                bot.answer_callback_query(call.id, url=url)
            else:
                bot.answer_callback_query(call.id, "\u26a0\ufe0f Товар не найден")
        except Exception as e:
            logger.error(f"Click tracking error: {e}")
            bot.answer_callback_query(call.id, "\u274c Ошибка")

    return bot
