"""Диагностика: проходим реальный путь "открыть Дзен -> Студия -> Создать публикацию -> Статья"
кликами, как это делает человек, и на каждом шаге сохраняем скриншот + URL.
Так и старый URL dzen.ru/id/editor/new_post оказался несуществующим (404) -
Дзен, видимо, перенёс редактор в другое место.

Ничего не публикует. Запускать из корня marketplace-ref-bot:
    python3 debug_dzen_flow.py
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


def dump_step(page, name, log):
    path = f"data/debug_flow_{name}.png"
    try:
        page.screenshot(path=path, full_page=True)
    except Exception as e:
        log.append(f"[{name}] screenshot failed: {e}")
    log.append(f"[{name}] url={page.url} title={page.title()!r}")


def try_click_text(page, context, text, log, step_name):
    """Пробует кликнуть по элементу с данным текстом. Возвращает страницу
    (новую, если открылась в новой вкладке, иначе ту же) или None, если не нашли."""
    try:
        locator = page.get_by_text(text, exact=False).first
        locator.wait_for(timeout=8000)
    except Exception as e:
        log.append(f"[{step_name}] элемент с текстом '{text}' не найден: {e}")
        return None

    pages_before = len(context.pages)
    try:
        locator.click(timeout=8000)
    except Exception as e:
        log.append(f"[{step_name}] клик по '{text}' не удался: {e}")
        return None

    page.wait_for_timeout(2500)

    if len(context.pages) > pages_before:
        new_page = context.pages[-1]
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        new_page.wait_for_timeout(1500)
        log.append(f"[{step_name}] клик открыл новую вкладку")
        return new_page

    return page


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
    log = []

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
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")

        page.goto("https://dzen.ru/", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        dump_step(page, "1_home", log)

        cur = try_click_text(page, context, "Студия", log, "2_click_studio")
        if cur is None:
            cur = try_click_text(page, context, "студия", log, "2b_click_studio_lower")
        if cur is not None:
            page = cur
            dump_step(page, "2_studio", log)

            cur2 = try_click_text(page, context, "Создать публикацию", log, "3_click_create")
            if cur2 is None:
                cur2 = try_click_text(page, context, "Создать", log, "3b_click_create_short")
            if cur2 is not None:
                page = cur2
                dump_step(page, "3_create_menu", log)

                cur3 = try_click_text(page, context, "Статья", log, "4_click_article")
                if cur3 is not None:
                    page = cur3
                    dump_step(page, "4_article_editor", log)

        # Финальное состояние + список полей ввода на текущей странице
        log.append(f"ФИНАЛЬНЫЙ URL: {page.url}")

        candidates = page.query_selector_all(
            '[contenteditable="true"], [contenteditable=""], textarea, input, '
            '[role="textbox"], [data-testid]'
        )
        field_lines = []
        for el in candidates:
            try:
                tag = el.evaluate("e => e.tagName")
                attrs = el.evaluate(
                    "e => Array.from(e.attributes).map(a => a.name+'='+JSON.stringify(a.value)).join(' ')"
                )
                text = (el.inner_text() or "")[:60].replace("\n", " ")
                field_lines.append(f"<{tag} {attrs}> text={text!r}")
            except Exception as e:
                field_lines.append(f"(error: {e})")

        with open("data/debug_flow_fields.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(field_lines))
        log.append(f"Полей-кандидатов на финальной странице: {len(field_lines)}")

        with open("data/debug_flow_log.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(log))

        browser.close()

    print("\n".join(log))
    print("\nСмотрите файлы data/debug_flow_*.png и data/debug_flow_*.txt")


if __name__ == "__main__":
    main()
