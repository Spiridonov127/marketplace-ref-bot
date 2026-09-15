"""Диагностика №2: ищем кнопку создания новой публикации внутри самой
Дзен-Студии (не на общей ленте dzen.ru, а на странице канала/черновиков).

Ничего не публикует, не создаёт черновиков — только сохраняет список
кликабельных элементов всей страницы + скриншот. Запускать из корня
marketplace-ref-bot:
    python3 debug_dzen_studio_create.py
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
    # Ожидаем что-то вроде:
    # https://dzen.ru/profile/editor/id/{channel_id}/{draft_id}/edit
    m = re.search(r"/profile/editor/id/([a-f0-9]+)/", draft_url)
    return m.group(1) if m else None


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
    print(f"channel_id = {channel_id}")

    with open(cookies_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    os.makedirs("data", exist_ok=True)

    # Пробуем несколько вероятных "домашних" URL студии по очереди.
    candidate_urls = [
        f"https://dzen.ru/profile/editor/id/{channel_id}",
        f"https://dzen.ru/profile/editor/id/{channel_id}/publications",
        f"https://dzen.ru/id/{channel_id}",
    ]

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

        for i, url in enumerate(candidate_urls, 1):
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                except Exception:
                    pass

                final_url = page.url
                title = page.title()
                print(f"[{i}] Запрошено: {url}")
                print(f"    Итоговый URL: {final_url} | Title: {title}")

                # Явный 404?
                is_404 = False
                try:
                    err = page.locator(".error__title, [class*=error__title]")
                    if err.count() > 0 and err.first.is_visible():
                        is_404 = True
                except Exception:
                    pass
                print(f"    Похоже на 404: {is_404}")

                # Собираем ВСЕ кликабельные элементы страницы (не только шапку),
                # т.к. кнопка создания может быть где угодно (плавающая, в сайдбаре и т.д.)
                candidates = page.query_selector_all(
                    "a, button, [role=button], [class*=create], [class*=Create], "
                    "[class*=add], [class*=Add], [class*=new], [class*=New], "
                    "[data-testid*=create], [data-testid*=add], [data-testid*=new]"
                )

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

                out_path = f"data/debug_studio_{i}_elements.txt"
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(f"Запрошено: {url}\nИтоговый URL: {final_url}\nTitle: {title}\n\n")
                    f.write("\n".join(lines))
                print(f"    Найдено элементов: {len(lines)} -> {out_path}")

                shot_path = f"data/debug_studio_{i}.png"
                page.screenshot(path=shot_path, full_page=True)
                print(f"    Скриншот -> {shot_path}")

            except Exception as e:
                print(f"[{i}] Ошибка при обработке {url}: {e}")

        browser.close()


if __name__ == "__main__":
    main()
