"""Автоматическое получение erid и промаркированной ссылки через генератор
Яндекс Дистрибуции (https://distribution.yandex.ru/v2/tools/market/links/).

ВАЖНО: каждый вызов get_marked_link() реально регистрирует новый рекламный
креатив в ОРД Яндекса — это не тестовое действие с побочным эффектом, а
весь смысл функции (по закону так и должно быть: у каждого рекламного
креатива свой erid). Поэтому вызывать это стоит только для постов, которые
реально уходят в публикацию, а не для превью/черновиков "просто посмотреть".

Требует ОТДЕЛЬНОГО входа — куки Дзена (DZEN_COOKIES_PATH) сюда не подходят,
это разные области авторизации Яндекс Паспорта. Сначала один раз запустите
save_distribution_cookies.py.

Если что-то пошло не так (нет cookies, не авторизован, разметка страницы
поменялась) — возвращает None, и вызывающий код должен сам решить: не
публиковать пост вообще, либо явно опубликовать без маркировки (второе —
плохая идея с точки зрения закона, лучше просто не публиковать).
"""
import json
import logging
import os
import re
from typing import Optional

from config import config

logger = logging.getLogger(__name__)

TOOL_URL = "https://distribution.yandex.ru/v2/tools/market/links/"


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def _value_after(lines: list[str], label: str) -> Optional[str]:
    for i, ln in enumerate(lines):
        if ln == label:
            for nxt in lines[i + 1:i + 3]:
                if nxt:
                    return nxt
    return None


def get_marked_link(product_url: str, creative_text: str) -> Optional[dict]:
    """Регистрирует товар как рекламный креатив и возвращает готовые данные:

    {
        "erid": "5jtCeReNx...",
        "short_link": "https://market.yandex.ru/cc/....?erid=...",
        "full_link": "https://market.yandex.ru/card/...?...&erid=...&clid=...",
        "label": "Реклама. ООО «Яндекс Маркет», ИНН 9704254424, erid: ...",
        "disclaimer": "Внешний вид товаров и/или упаковки...",
    }

    full_link — это и есть ссылка, которую нужно использовать в посте вместо
    обычной CPA-ссылки (она уже содержит и clid, и erid, и трекинговые
    параметры). Возвращает None при любой ошибке.
    """
    sp = _try_playwright()
    if not sp:
        logger.error("[ОРД] Playwright не установлен")
        return None

    cookies_path = config.DISTRIBUTION_COOKIES_PATH
    if not os.path.exists(cookies_path):
        logger.error(
            f"[ОРД] Cookies не найдены: {cookies_path} — запустите save_distribution_cookies.py"
        )
        return None

    with open(cookies_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    try:
        with sp() as p:
            browser = p.chromium.launch(
                headless=True,
                proxy={"server": config.YM_PROXY_URL} if config.YM_PROXY_URL else None,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                locale="ru-RU",
                viewport={"width": 1440, "height": 1000},
            )
            context.add_cookies(cookies)
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
            )

            page.goto(TOOL_URL, timeout=30000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1500)

            if "passport" in page.url:
                logger.error(
                    "[ОРД] Не авторизован — обновите куки через save_distribution_cookies.py"
                )
                browser.close()
                return None

            link_input = page.locator('textarea[placeholder="https://market.yandex.ru/"]')
            link_input.wait_for(timeout=15000)
            link_input.click()
            link_input.fill(product_url)
            page.wait_for_timeout(500)

            get_token_btn = page.get_by_text("Получить токен в ОРД Яндекса", exact=True)
            get_token_btn.wait_for(state="attached", timeout=10000)
            get_token_btn.click(force=True, timeout=10000)
            page.wait_for_timeout(1000)

            # Модалка регистрации креатива содержит ДВА обязательных текстовых
            # поля, не одно: "Общее описание креатива" (видно сразу, с
            # плейсхолдером "Описание объекта рекламирования") и "Текст
            # креатива" (появляется только после разворота "Добавить текст
            # креатива"). Раньше заполнялось только второе — из-за этого
            # первое оставалось пустым, форма не проходила валидацию
            # ("Обязательное поле" подсвечивалось красным), "Продолжить" не
            # срабатывал и токен не появлялся. Заполняем оба.
            desc_input = page.locator(
                'textarea[placeholder="Описание объекта рекламирования"]'
            )
            try:
                desc_input.wait_for(state="visible", timeout=5000)
                desc_input.click(force=True)
                desc_input.fill((creative_text or "Реклама товара")[:500])
            except Exception as e:
                logger.warning(f"[ОРД] Не удалось заполнить общее описание креатива: {e}")

            add_text_btn = page.get_by_text("Добавить текст креатива", exact=True)
            try:
                add_text_btn.wait_for(state="attached", timeout=8000)
                add_text_btn.click(force=True, timeout=8000)
                page.wait_for_timeout(800)
                modal_textareas = page.locator("textarea")
                count = modal_textareas.count()
                if count >= 2:
                    modal_textareas.nth(count - 1).click(force=True)
                    modal_textareas.nth(count - 1).fill(creative_text[:1000])
            except Exception as e:
                logger.warning(f"[ОРД] Не удалось заполнить текст креатива: {e}")

            continue_btn = page.get_by_text("Продолжить", exact=True)
            continue_btn.wait_for(state="attached", timeout=8000)
            continue_btn.click(force=True, timeout=8000)

            # Поле с новым токеном отрисовывается нестандартно (input_value()
            # не читает его надёжно) — читаем прямо из текста страницы.
            erid = ""
            for _ in range(20):
                page.wait_for_timeout(500)
                try:
                    body_text = page.inner_text("body")
                except Exception:
                    continue
                lines = [ln.strip() for ln in body_text.splitlines()]
                for i, ln in enumerate(lines):
                    if ln == "Токен для маркировки рекламы":
                        for nxt in lines[i + 1:i + 4]:
                            if nxt and re.fullmatch(r"[A-Za-z0-9]{10,40}", nxt):
                                erid = nxt
                                break
                        break
                if erid:
                    break

            if not erid:
                logger.error(f"[ОРД] Токен не появился для {product_url}")
                browser.close()
                return None

            create_btn = page.get_by_text("Создать ссылку", exact=True)
            create_btn.wait_for(state="attached", timeout=10000)
            create_btn.click(force=True, timeout=10000)
            page.wait_for_timeout(2000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            body_text = page.inner_text("body")
            lines = [ln.strip() for ln in body_text.splitlines()]

            short_link = _value_after(lines, "Короткая ссылка с токеном")
            full_link = _value_after(lines, "Полная ссылка с токеном")
            label = _value_after(lines, "Метка для маркировки рекламы")
            disclaimer = _value_after(lines, "Обязательный дисклеймер")

            browser.close()

            if not full_link:
                logger.error(f"[ОРД] Не нашёл готовую ссылку после создания для {product_url}")
                return None

            return {
                "erid": erid,
                "short_link": short_link,
                "full_link": full_link,
                "label": label,
                "disclaimer": disclaimer,
            }

    except Exception as e:
        logger.error(f"[ОРД] Ошибка получения маркированной ссылки для {product_url}: {e}")
        return None
