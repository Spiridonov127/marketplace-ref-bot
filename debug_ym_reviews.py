"""Диагностика: что реально есть на странице товара Яндекс Маркета в разделе
отзывов — структурированные "Достоинства"/"Недостатки" по каждому отзыву,
или просто сплошной текст. Ничего не публикует, только смотрит и печатает.

Запускать из корня marketplace-ref-bot:
    python3 debug_ym_reviews.py "<ссылка на товар>"
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def main():
    if len(sys.argv) < 2:
        print('Использование: python3 debug_ym_reviews.py "<ссылка на товар>"')
        return
    product_url = sys.argv[1]

    sp = _try_playwright()
    if not sp:
        print("Playwright не установлен")
        return

    os.makedirs("data", exist_ok=True)

    with sp() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="ru-RU",
            viewport={"width": 1920, "height": 1080},
            timezone_id="Europe/Moscow",
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en'] });
            window.chrome = { runtime: {} };
        """)
        page = context.new_page()

        print(f"Открываю: {product_url}")
        try:
            page.goto(product_url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
        except Exception as e:
            print(f"Ошибка загрузки страницы товара: {e}")

        title = page.title()
        print(f"Заголовок страницы: {title}")
        if "robot" in title.lower() or "captcha" in title.lower():
            print("Похоже на CAPTCHA — смотри скриншот")
            page.screenshot(path="data/debug_ym_reviews_captcha.png", full_page=True)
            browser.close()
            return

        page.screenshot(path="data/debug_ym_reviews_product_page.png", full_page=True)
        print("Скриншот страницы товара -> data/debug_ym_reviews_product_page.png")

        # Пробуем найти и кликнуть ссылку/вкладку на отзывы — на карточке
        # товара обычно есть якорь вида "N отзывов" или вкладка "Отзывы".
        clicked = False
        for pattern in ["отзыв", "Отзывы", "Все отзывы"]:
            try:
                link = page.get_by_text(re.compile(pattern, re.IGNORECASE)).first
                if link.count() if hasattr(link, "count") else False:
                    pass
            except Exception:
                pass
        try:
            candidates = page.locator("a, button, [role='tab']")
            count = candidates.count()
            for i in range(min(count, 400)):
                try:
                    text = candidates.nth(i).inner_text(timeout=500).strip()
                except Exception:
                    continue
                if re.search(r"отзыв", text, re.IGNORECASE) and len(text) < 40:
                    print(f"Нашёл кандидата на клик: {text!r}")
                    candidates.nth(i).click(force=True, timeout=5000)
                    clicked = True
                    break
        except Exception as e:
            print(f"Не удалось поискать вкладку отзывов: {e}")

        if clicked:
            page.wait_for_timeout(2500)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
        else:
            print("Явную вкладку/ссылку на отзывы не нашёл — просто скроллю страницу вниз")
            for _ in range(6):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(500)

        page.screenshot(path="data/debug_ym_reviews_after_click.png", full_page=True)
        print("Скриншот после клика/скролла -> data/debug_ym_reviews_after_click.png")

        body_text = page.inner_text("body")
        with open("data/debug_ym_reviews_body.txt", "w", encoding="utf-8") as f:
            f.write(body_text)
        print(f"Полный текст страницы ({len(body_text)} символов) -> data/debug_ym_reviews_body.txt")

        # Ищем маркеры структурированных плюсов/минусов в тексте отзывов.
        for marker in ["Достоинства", "Недостатки", "Плюсы", "Минусы", "Комментарий"]:
            hits = [m.start() for m in re.finditer(marker, body_text)]
            print(f"Вхождений '{marker}': {len(hits)}")
            for pos in hits[:3]:
                snippet = body_text[pos:pos + 200].replace("\n", " | ")
                print(f"   ...{snippet}...")

        browser.close()


if __name__ == "__main__":
    main()
