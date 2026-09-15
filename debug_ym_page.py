"""Диагностика: сохраняет сырые данные страницы Яндекс Маркета для анализа разметки цен/скидок.
Ничего никуда не публикует, только пишет файлы в data/debug_*.
Запускать из корня marketplace-ref-bot: python3 debug_ym_page.py
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parsers.playwright_parsers import _try_playwright, _create_browser_context

URL = "https://market.yandex.ru/catalog--elektronika/54439/list?hid=90555&glfilter=offer-shippable:1&how=discount"


def main():
    sp = _try_playwright()
    if not sp:
        print("Playwright не установлен")
        return

    os.makedirs("data", exist_ok=True)

    with sp() as p:
        browser, context = _create_browser_context(p)
        page = context.new_page()
        page.goto(URL, timeout=25000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        title = page.title()
        print(f"Title: {title}")
        if "robot" in title.lower() or "captcha" in title.lower():
            print("!!! CAPTCHA / robot check — сохраняю всё равно, но будет пусто")

        # 1) Все JSON-LD скрипты целиком
        scripts = page.query_selector_all('script[type="application/ld+json"]')
        jsonld_dump = []
        for i, script in enumerate(scripts):
            try:
                data = json.loads(script.inner_text())
                jsonld_dump.append(data)
            except Exception as e:
                jsonld_dump.append({"_parse_error": str(e), "_raw": script.inner_text()[:2000]})
        with open("data/debug_jsonld.json", "w", encoding="utf-8") as f:
            json.dump(jsonld_dump, f, ensure_ascii=False, indent=2)
        print(f"JSON-LD блоков сохранено: {len(jsonld_dump)} -> data/debug_jsonld.json")

        # 2) HTML первых нескольких карточек товаров (с ценой/скидкой на глаз)
        cards = page.query_selector_all(
            '[data-autotest-id="offer-snippet"], [class*="n-snippet-card"], '
            'article, [class*="snippet"], a[href*="/product/"]'
        )
        print(f"Найдено карточек по текущим селекторам: {len(cards)}")

        html_dump = []
        seen = set()
        for card in cards:
            try:
                outer = card.evaluate("el => el.outerHTML")
            except Exception:
                continue
            key = outer[:200]
            if key in seen:
                continue
            seen.add(key)
            html_dump.append(outer)
            if len(html_dump) >= 5:
                break

        with open("data/debug_cards.html", "w", encoding="utf-8") as f:
            f.write("\n\n<!-- ===== NEXT CARD ===== -->\n\n".join(html_dump))
        print(f"Карточек сохранено: {len(html_dump)} -> data/debug_cards.html")

        # 3) Полный HTML страницы на всякий случай (для поиска блоков цены руками)
        with open("data/debug_full_page.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("Полный HTML страницы -> data/debug_full_page.html")

        browser.close()


if __name__ == "__main__":
    main()
