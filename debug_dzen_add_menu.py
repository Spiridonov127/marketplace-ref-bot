"""Диагностика №3: кликаем по найденной кнопке "+" (data-testid=add-publication-button)
в шапке Студии и смотрим, какое меню появляется (выбор типа публикации).

Ничего не публикует. Может создать пустой черновик, если Дзен создаёт его
сразу по клику на "Статья" — если это произойдёт, это просто пустой черновик,
удалить его можно вручную в разделе "Публикации". Публикация (кнопка
"Опубликовать") нигде не нажимается.

Запускать из корня marketplace-ref-bot:
    python3 debug_dzen_add_menu.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def _extract_channel_id(draft_url: str):
    m = re.search(r"/profile/editor/id/([a-f0-9]+)/", draft_url)
    return m.group(1) if m else None


def _dump_elements(page, path_txt):
    candidates = page.query_selector_all("a, button, [role=button], [role=menuitem], li")
    lines = []
    seen = set()
    for el in candidates:
        try:
            box = el.bounding_box()
            if not box:
                continue
            tag = el.evaluate("e => e.tagName")
            attrs = el.evaluate(
                "e => Array.from(e.attributes).map(a => a.name+'='+JSON.stringify(a.value)).join(' ')"
            )
            text = (el.inner_text() or "").strip()[:60]
            key = (tag, attrs, text)
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"<{tag} {attrs}> pos=({box['x']:.0f},{box['y']:.0f}) "
                f"size=({box['width']:.0f}x{box['height']:.0f}) text={text!r}"
            )
        except Exception as e:
            lines.append(f"(error: {e})")
    with open(path_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return len(lines)


def main():
    sp = _try_playwright()
    if not sp:
        print("Playwright не установлен")
        return

    cookies_path = config.DZEN_COOKIES_PATH
    if not os.path.exists(cookies_path):
        print(f"Cookies не найдены: {cookies_path}")
        return

    channel_id = _extract_channel_id(config.DZEN_DRAFT_URL)
    if not channel_id:
        print(f"Не удалось извлечь channel_id из DZEN_DRAFT_URL={config.DZEN_DRAFT_URL!r}")
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

        page.goto(
            f"https://dzen.ru/profile/editor/id/{channel_id}",
            timeout=30000,
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(3000)
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass

        print("До клика URL:", page.url)

        btn = page.locator('[data-testid="add-publication-button"]')
        if btn.count() == 0:
            print("Кнопка add-publication-button не найдена на этой загрузке")
            browser.close()
            return

        btn.first.click()
        page.wait_for_timeout(1500)

        after_click_url = page.url
        print("Сразу после клика URL:", after_click_url)

        n = _dump_elements(page, "data/debug_add_menu_elements.txt")
        print(f"Элементов на экране после клика: {n} -> data/debug_add_menu_elements.txt")

        page.screenshot(path="data/debug_add_menu.png", full_page=True)
        print("Скриншот после клика -> data/debug_add_menu.png")

        # Если сама кнопка сразу создала черновик и перекинула на /edit —
        # тоже зафиксируем это явно.
        if "/edit" in after_click_url:
            print("Похоже, клик сразу создал черновик и открыл редактор (без промежуточного меню).")

        browser.close()


if __name__ == "__main__":
    main()
