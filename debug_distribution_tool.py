"""Диагностика: проверяем, подходят ли куки от Дзена (та же Яндекс-сессия)
для страницы генератора ссылок Яндекс Дистрибуции, и ищем точные селекторы
полей — ссылка на товар, кнопка "Получить токен в ОРД Яндекса", поле токена,
кнопка "Создать ссылку".

Ничего не создаёт и никуда не публикует — только смотрит страницу и
сохраняет список полей/кнопок + скриншот.

Запускать из корня marketplace-ref-bot:
    python3 debug_distribution_tool.py
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

    cookies_path = config.DISTRIBUTION_COOKIES_PATH
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

        page.goto(TOOL_URL, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
        # Ждём, пока пропадёт спиннер загрузки формы (первая попытка показала
        # пустую страницу с крутилкой — контент подгружается отдельным
        # запросом уже после первой отрисовки).
        try:
            page.locator("textarea").first.wait_for(timeout=15000)
        except Exception:
            print("Textarea так и не появилась за 15с — форма могла не догрузиться")

        print("Итоговый URL:", page.url)
        print("Title:", page.title())

        if "passport" in page.url or "auth" in page.url:
            print("ПОХОЖЕ, НЕ АВТОРИЗОВАН — куки от Дзена сюда не подошли.")
            page.screenshot(path="data/debug_distr_tool_login.png", full_page=True)
            browser.close()
            return

        print("Авторизация похожа на успешную (не улетели на passport/auth).")

        # Собираем все текстовые поля, textarea, кнопки и селекты на странице
        candidates = page.query_selector_all("textarea, input, button, select, [role=button]")
        lines = []
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
                placeholder = el.get_attribute("placeholder") or ""
                lines.append(
                    f"<{tag} {attrs}> pos=({box['x']:.0f},{box['y']:.0f}) "
                    f"size=({box['width']:.0f}x{box['height']:.0f}) "
                    f"placeholder={placeholder!r} text={text!r}"
                )
            except Exception as e:
                lines.append(f"(error: {e})")

        out_path = "data/debug_distr_tool_elements.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"Найдено элементов: {len(lines)} -> {out_path}")

        page.screenshot(path="data/debug_distr_tool.png", full_page=True)
        print("Скриншот -> data/debug_distr_tool.png")

        browser.close()


if __name__ == "__main__":
    main()
