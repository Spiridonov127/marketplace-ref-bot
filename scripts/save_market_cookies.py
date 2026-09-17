"""Одноразовый интерактивный вход в Яндекс Маркет и сохранение cookies.

Анонимные (без входа в аккаунт) автоматизированные запросы к Маркету
капчатся заметно чаще — обычная практика антибот-систем больше доверять
уже авторизованным сессиям. Как и для Дзена/Дистрибуции — вход руками
один раз, cookies сохраняются и дальше переиспользуются автоматически.

ВАЖНО: этот скрипт открывает видимый браузер (headless=False) — запускать
нужно локально, на компьютере с экраном (не на ВПС по SSH). После входа
файл data/market_cookies.json нужно скопировать на ВПС:
    scp data/market_cookies.json yc-user@<VPS_IP>:~/marketplace-ref-bot/data/

Запускать из корня marketplace-ref-bot:
    python3 scripts/save_market_cookies.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config

MARKET_URL = "https://market.yandex.ru/"


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def main():
    sp = _try_playwright()
    if not sp:
        print("Playwright не установлен")
        return

    path = config.MARKET_COOKIES_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with sp() as p:
        browser = p.chromium.launch(headless=False)  # Видимый браузер для входа
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="ru-RU",
        )
        page = context.new_page()

        page.goto(MARKET_URL, timeout=30000)
        print("[Market] Войдите в Яндекс-аккаунт в открытом браузере (кнопка")
        print("[Market] 'Войти' в правом верхнем углу) — обычным аккаунтом,")
        print("[Market] которым реально пользуетесь для покупок.")

        input("[Market] Нажмите Enter после успешного входа...")

        cookies = context.cookies()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        print(f"[Market] Cookies сохранены: {path}")
        browser.close()


if __name__ == "__main__":
    main()
