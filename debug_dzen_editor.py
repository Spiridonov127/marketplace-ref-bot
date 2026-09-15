"""Диагностика редактора Дзена: скриншот + HTML + список полей ввода.
Ничего не публикует и не меняет. Запускать из корня marketplace-ref-bot:
    python3 debug_dzen_editor.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config


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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="ru-RU",
            viewport={"width": 1440, "height": 1000},
        )
        context.add_cookies(cookies)
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
        """)

        page.goto("https://dzen.ru/id/editor/new_post", timeout=30000)
        page.wait_for_timeout(6000)

        print("URL после загрузки:", page.url)
        print("Title:", page.title())

        if "passport" in page.url or "login" in page.url:
            print("!!! Не авторизован — cookies не сработали")

        # Скриншот всей видимой области
        page.screenshot(path="data/debug_dzen_editor.png", full_page=True)
        print("Скриншот -> data/debug_dzen_editor.png")

        # Полный HTML
        with open("data/debug_dzen_editor.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("HTML -> data/debug_dzen_editor.html")

        # Список потенциальных полей ввода: contenteditable, textarea, role=textbox, input
        candidates = page.query_selector_all(
            '[contenteditable="true"], [contenteditable=""], textarea, input, '
            '[role="textbox"], [data-testid], h1, [class*="title" i]'
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
                lines.append(f"(error reading element: {e})")

        with open("data/debug_dzen_elements.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"Полей-кандидатов найдено: {len(lines)} -> data/debug_dzen_elements.txt")

        browser.close()


if __name__ == "__main__":
    main()
