"""Проверка автосоздания черновика на РЕАЛЬНОМ контенте (с AI-текстом и
картинками, как в настоящем посте) — но БЕЗ публикации. Нужно, чтобы
проверить фикс гонки с картинками (первая картинка пропадала) на реальных
данных, а не на тестовом тексте без картинок.

Товары НЕ помечаются как опубликованные — можно гонять сколько угодно раз.

Запускать из корня marketplace-ref-bot:
    python3 test_real_content_draft.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from database import Database
from content_generator import generate_dzen_article
from referral_builder import build_ym_cpa_link
from dzen_poster import (
    _try_playwright,
    _extract_channel_id,
    _create_new_draft,
    _dismiss_help_overlay,
    fill_article,
)
import json


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

    db = Database(config.DB_PATH)
    products = db.get_unposted_products(
        limit=config.MAX_PRODUCTS_PER_POST,
        min_discount=config.MIN_DISCOUNT_PERCENT,
    )
    if not products:
        print("Нет неопубликованных товаров с подтверждённой скидкой — запустите сначала parse_only.py")
        return

    for p in products:
        p.referral_url = build_ym_cpa_link(p.url)

    title, body_html = generate_dzen_article(products)
    expected_images = body_html.count("<img")
    print(f"Сгенерирован контент: заголовок={title!r}, картинок в HTML={expected_images}")

    with open(cookies_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    os.makedirs("data", exist_ok=True)

    with sp() as p_:
        browser = p_.chromium.launch(
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

        if not _create_new_draft(page, channel_id):
            print("Не удалось создать новый черновик — см. лог выше")
            browser.close()
            return

        print(f"Черновик создан: {page.url}")

        editor_root = page.locator('[data-testid="editor-root"]')
        try:
            editor_root.wait_for(timeout=10000)
        except Exception as e:
            print(f"Редактор не загрузился: {e}")
            browser.close()
            return

        _dismiss_help_overlay(page)

        editable = editor_root.locator('[contenteditable="true"]')
        count = editable.count()
        print(f"Найдено contenteditable-полей: {count}")
        if count < 2:
            print("Ожидались поля заголовка и текста — что-то не так с новым черновиком")
            page.screenshot(path="data/debug_real_draft_fail.png", full_page=True)
            browser.close()
            return

        title_input = editable.nth(0)
        body_input = editable.nth(1)

        result = fill_article(page, title_input, body_input, title, body_html)
        print(
            f"Результат: заголовок={result['title_text'][:60]!r}, "
            f"длина текста={len(result['body_text'])}, "
            f"картинок {result['img_count']}/{result['expected_images']}"
        )

        page.wait_for_timeout(2000)
        page.screenshot(path="data/debug_real_draft_filled.png", full_page=True)
        print("Скриншот -> data/debug_real_draft_filled.png")
        print(f"Ссылка на черновик (можно открыть глазами): {page.url}")

        if (
            result["title_text"]
            and result["body_text"]
            and result["img_count"] >= result["expected_images"]
        ):
            print("УСПЕХ: заголовок, текст и все картинки на месте.")
        else:
            print("ПРОБЛЕМА: чего-то не хватает — смотри лог и скриншот выше.")

        print("Публикация НЕ нажималась, товары НЕ помечены как опубликованные.")
        browser.close()


if __name__ == "__main__":
    main()
