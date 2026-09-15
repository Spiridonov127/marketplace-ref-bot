"""Диагностика реального редактора Дзена по прямой ссылке на существующий черновик.
Ничего не публикует и не редактирует черновик. Запускать из корня marketplace-ref-bot:
    python3 debug_dzen_editor2.py "<URL черновика>"
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config

DEFAULT_URL = "https://dzen.ru/profile/editor/id/6a5fef5807b3fa3d93117168/6aa7eec6e31cf70ed29b89c1/edit"


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL

    sp = _try_playwright()
    if not sp:
        print("Playwright не установлен")
        return

    cookies_path = config.DZEN_COOKIES_PATH
    if not os.path.exists(cookies_path):
        print(f"Cookies не найдены: {cookies_path}")
        return

    with open(cookies_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    os.makedirs("data", exist_ok=True)

    with sp() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="ru-RU",
            viewport={"width": 1440, "height": 1000},
        )
        context.add_cookies(cookies)
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")

        print("Открываю:", url)
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        print("URL после загрузки:", page.url)
        print("Title:", page.title())

        page.screenshot(path="data/debug_editor2.png", full_page=True)
        print("Скриншот -> data/debug_editor2.png")

        with open("data/debug_editor2.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("HTML -> data/debug_editor2.html")

        candidates = page.query_selector_all(
            '[contenteditable="true"], [contenteditable=""], textarea, input, '
            '[role="textbox"], [data-testid], [class*="title" i], button'
        )
        lines = []
        for el in candidates:
            try:
                tag = el.evaluate("e => e.tagName")
                attrs = el.evaluate(
                    "e => Array.from(e.attributes).map(a => a.name+'='+JSON.stringify(a.value)).join(' ')"
                )
                text = (el.inner_text() or "")[:60].replace("\n", " ")
                box = el.bounding_box()
                visible = bool(box and box.get("width", 0) > 0 and box.get("height", 0) > 0)
                lines.append(f"<{tag} {attrs}> visible={visible} text={text!r}")
            except Exception as e:
                lines.append(f"(error: {e})")

        with open("data/debug_editor2_fields.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"Полей-кандидатов: {len(lines)} -> data/debug_editor2_fields.txt")

        browser.close()


if __name__ == "__main__":
    main()
