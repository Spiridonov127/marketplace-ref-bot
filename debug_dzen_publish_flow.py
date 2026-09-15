"""Диагностика: что реально происходит в Дзен-студии после клика по кнопке
"Опубликовать" (article-publish-btn) — публикуется ли статья сразу, или
Дзен открывает ещё один шаг/модалку (например, настройки публикации —
рубрика, обложка и т.п.), которую наш код в dzen_poster.post_to_dzen()
сейчас не проходит, из-за чего статья остаётся в черновиках, хотя код
считает публикацию успешной (клик прошёл без ошибки).

Создаёт ОДИН новый черновик с тестовым содержимым, кликает по той же кнопке,
что и в продакшене, и после этого только смотрит и печатает — саму
модалку/дальнейшие кнопки НЕ трогает, чтобы не опубликовать тестовую статью
по ошибке до того, как мы разберёмся, что там на самом деле происходит.

Запускать из корня marketplace-ref-bot:
    python3 debug_dzen_publish_flow.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from dzen_poster import (
    _try_playwright,
    _create_new_draft,
    _extract_channel_id,
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
        print("Не удалось определить id канала из DZEN_DRAFT_URL в .env")
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="ru-RU",
            viewport={"width": 1440, "height": 1000},
        )
        context.add_cookies(cookies)
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
        )

        print("Создаю новый черновик...")
        if not _create_new_draft(page, channel_id):
            print("Не удалось создать черновик — смотри лог выше")
            browser.close()
            return

        print(f"Черновик создан: {page.url}")

        if "passport" in page.url or "login" in page.url:
            print("Не авторизован — обнови cookies")
            browser.close()
            return

        editor_root = page.locator('[data-testid="editor-root"]')
        editor_root.wait_for(timeout=10000)
        _dismiss_help_overlay(page)

        editable = editor_root.locator('[contenteditable="true"]')
        title_input = editable.nth(0)
        body_input = editable.nth(1)

        result = fill_article(
            page,
            title_input,
            body_input,
            "ТЕСТ ПУБЛИКАЦИИ — можно удалить",
            "<p>Тестовая статья для диагностики шага публикации. Можно удалить.</p>",
        )
        print(f"Заполнено: title={result['title_text']!r}, body_len={len(result['body_text'])}")

        page.screenshot(path="data/debug_dzen_before_publish.png", full_page=True)
        print("Скриншот ДО клика по 'Опубликовать' -> data/debug_dzen_before_publish.png")

        publish_btn = page.locator('[data-testid="article-publish-btn"]')
        publish_btn.wait_for(timeout=8000)
        btn_text = publish_btn.inner_text().strip()
        print(f"Текст на кнопке публикации: {btn_text!r}")
        publish_btn.click()
        page.wait_for_timeout(2500)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        print(f"URL после клика: {page.url}")
        page.screenshot(path="data/debug_dzen_after_publish_click.png", full_page=True)
        print("Скриншот ПОСЛЕ клика -> data/debug_dzen_after_publish_click.png")

        # Ищем любую модалку/панель, которая могла открыться поверх редактора.
        modal_selectors = [
            "[role='dialog']",
            "[aria-modal='true']",
            "[class*='Modal']",
            "[class*='modal']",
            "[class*='Drawer']",
            "[class*='drawer']",
            "[class*='Panel']",
        ]
        found_any_modal = False
        for sel in modal_selectors:
            loc = page.locator(sel)
            n = loc.count()
            for i in range(min(n, 3)):
                el = loc.nth(i)
                try:
                    if el.is_visible():
                        found_any_modal = True
                        text = el.inner_text()[:500].replace("\n", " | ")
                        print(f"[Видимый элемент {sel} #{i}]: {text}")
                except Exception:
                    continue
        if not found_any_modal:
            print("Видимых модалок/панелей по стандартным селекторам не найдено.")

        # Печатаем ВСЕ видимые кнопки на странице — среди них должна быть
        # настоящая кнопка финального подтверждения, если такая есть.
        print("\nВсе видимые кнопки на странице после клика:")
        buttons = page.locator("button")
        n = buttons.count()
        for i in range(min(n, 60)):
            btn = buttons.nth(i)
            try:
                if btn.is_visible():
                    text = btn.inner_text().strip().replace("\n", " ")
                    testid = btn.get_attribute("data-testid") or ""
                    if text or testid:
                        print(f"  - text={text!r} data-testid={testid!r}")
            except Exception:
                continue

        # Финальная проверка: не трогаем ничего дальше, чтобы тестовая статья
        # осталась черновиком, а не была случайно опубликована.
        print(
            "\nГотово. Тестовая статья НЕ опубликована окончательно (мы не "
            "нажимали никаких дальнейших кнопок) — её можно удалить в Дзен "
            "Студии из черновиков."
        )
        browser.close()


if __name__ == "__main__":
    main()
