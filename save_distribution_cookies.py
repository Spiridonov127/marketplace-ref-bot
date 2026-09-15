"""Одноразовый интерактивный вход в Яндекс Дистрибуцию и сохранение cookies.

Куки от Дзена (data/dzen_cookies.json) для этого НЕ подходят — проверено,
это отдельная область авторизации Яндекс Паспорта. Нужен отдельный вход,
как когда-то делали для Дзена: открывается видимый браузер, ты логинишься
руками, cookies сохраняются в файл и дальше переиспользуются скриптами
автоматически (без повторного ввода пароля).

Запускать из корня marketplace-ref-bot:
    python3 save_distribution_cookies.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config

TOOL_URL = "https://distribution.yandex.ru/v2/tools/market/links/"


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

    path = config.DISTRIBUTION_COOKIES_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with sp() as p:
        browser = p.chromium.launch(headless=False)  # Видимый браузер для входа
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="ru-RU",
        )
        page = context.new_page()

        page.goto(TOOL_URL, timeout=30000)
        print("[Distribution] Войдите в Яндекс-аккаунт в открытом браузере...")
        print("[Distribution] Дождитесь, пока откроется сама страница инструментов")
        print("[Distribution] (заголовок 'Инструменты Яндекс Маркет'), а не экран входа.")

        input("[Distribution] Нажмите Enter после успешного входа...")

        cookies = context.cookies()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        print(f"[Distribution] Cookies сохранены: {path}")
        browser.close()


if __name__ == "__main__":
    main()
