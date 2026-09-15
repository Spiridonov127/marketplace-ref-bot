"""Диагностика: ищем кнопку "+" (создать публикацию) в шапке dzen.ru.
Ничего не публикует, не создаёт черновиков — только описывает найденные
кликабельные элементы в шапке. Запускать из корня marketplace-ref-bot:
    python3 debug_dzen_create_btn.py
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="ru-RU",
            viewport={"width": 1440, "height": 1000},
        )
        context.add_cookies(cookies)
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")

        page.goto("https://dzen.ru/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        # Закрываем модалку "браузер устарел", если есть
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass

        print("URL:", page.url, "| Title:", page.title())

        # Ищем все кликабельные элементы в верхней части страницы (шапка)
        candidates = page.query_selector_all(
            "header a, header button, header [role=button], "
            "[class*=header] a, [class*=header] button, [class*=header] [role=button], "
            "[class*=Header] a, [class*=Header] button, [class*=Header] [role=button]"
        )

        lines = []
        seen = set()
        for el in candidates:
            try:
                box = el.bounding_box()
                if not box:
                    continue
                # Интересует только верхняя полоса экрана (шапка)
                if box["y"] > 80:
                    continue
                tag = el.evaluate("e => e.tagName")
                attrs = el.evaluate(
                    "e => Array.from(e.attributes).map(a => a.name+'='+JSON.stringify(a.value)).join(' ')"
                )
                text = (el.inner_text() or "").strip()[:40]
                key = (tag, attrs)
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    f"<{tag} {attrs}> pos=({box['x']:.0f},{box['y']:.0f}) size=({box['width']:.0f}x{box['height']:.0f}) text={text!r}"
                )
            except Exception as e:
                lines.append(f"(error: {e})")

        with open("data/debug_header_buttons.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"Найдено элементов в шапке: {len(lines)} -> data/debug_header_buttons.txt")

        page.screenshot(path="data/debug_header.png")
        print("Скриншот шапки (полная страница видна частично) -> data/debug_header.png")

        browser.close()


if __name__ == "__main__":
    main()
