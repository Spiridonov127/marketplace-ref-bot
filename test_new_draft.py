"""Безопасная проверка автосоздания черновика: создаёт новый черновик через
"+" в Студии и заполняет заголовок/текст тестовыми данными — теми же
функциями, что использует реальный post_to_dzen(). НЕ нажимает
"Опубликовать" — черновик останется черновиком, ничего не публикуется.

Запускать из корня marketplace-ref-bot:
    python3 test_new_draft.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from dzen_poster import (
    _try_playwright,
    _extract_channel_id,
    _create_new_draft,
    _dismiss_help_overlay,
    _paste_html,
)

TEST_TITLE = "ТЕСТ автосоздания черновика — можно удалить"
TEST_BODY_HTML = (
    "<p>Это тестовый текст, чтобы проверить, что заголовок и тело "
    "заполняются в новом автосозданном черновике. Публикация НЕ "
    "нажималась.</p>"
)


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
            page.screenshot(path="data/debug_new_draft_fail.png", full_page=True)
            browser.close()
            return

        title_input = editable.nth(0)
        body_input = editable.nth(1)

        def _fill_once():
            title_input.click()
            title_input.fill(TEST_TITLE)
            page.wait_for_timeout(500)
            _paste_html(page, body_input.element_handle(), TEST_BODY_HTML)
            page.wait_for_timeout(2000)
            try:
                page.get_by_text(re.compile("Сохранено")).first.wait_for(timeout=15000)
                print("Индикатор 'Сохранено' появился")
            except Exception:
                print("Индикатор 'Сохранено' не дождался (не обязательно ошибка)")

        _fill_once()
        title_text = (title_input.inner_text() or "").strip()
        body_text = (body_input.inner_text() or "").strip()
        print(f"После 1-й попытки: заголовок={title_text!r}, длина текста={len(body_text)}")

        if not title_text or not body_text:
            print("Пусто после первой попытки — пробую ещё раз")
            _fill_once()
            title_text = (title_input.inner_text() or "").strip()
            body_text = (body_input.inner_text() or "").strip()
            print(f"После 2-й попытки: заголовок={title_text!r}, длина текста={len(body_text)}")

        # Дополнительная пауза + повторное чтение — проверяем, что текст не
        # исчезает сам по себе чуть позже (та самая гонка с автосохранением).
        page.wait_for_timeout(3000)
        title_text_later = (title_input.inner_text() or "").strip()
        body_text_later = (body_input.inner_text() or "").strip()
        print(
            f"Через 3с после этого: заголовок={title_text_later!r}, "
            f"длина текста={len(body_text_later)}"
        )

        page.screenshot(path="data/debug_new_draft_filled.png", full_page=True)
        print("Скриншот -> data/debug_new_draft_filled.png")
        print(f"Ссылка на черновик (можно открыть глазами): {page.url}")

        if title_text_later and body_text_later:
            print("УСПЕХ: заголовок и текст на месте и через 3 секунды.")
        else:
            print("ПРОБЛЕМА: контент всё ещё пропадает — нужно копать глубже.")

        print("Публикация НЕ нажималась — это просто черновик, можно удалить в разделе 'Публикации'.")

        browser.close()


if __name__ == "__main__":
    main()
