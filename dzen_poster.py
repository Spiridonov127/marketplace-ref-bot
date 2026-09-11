"""Постинг в Яндекс Дзен через Playwright."""
import json
import logging
import os
import time
from typing import Optional

from config import config

logger = logging.getLogger(__name__)


def _try_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def save_dzen_cookies(cookies_path: str = None):
    """Интерактивный вход в Дзен и сохранение cookies.
    
    Запускается один раз вручную для авторизации.
    После этого cookies используются для автоматических постов.
    """
    sp = _try_playwright()
    if not sp:
        logger.error("Playwright not installed")
        return False

    path = cookies_path or config.DZEN_COOKIES_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        with sp() as p:
            browser = p.chromium.launch(headless=False)  # Видимый браузер для входа
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="ru-RU",
            )
            page = context.new_page()

            # Открываем Дзен
            page.goto("https://dzen.ru/id", timeout=30000)
            logger.info("[Dzen] Войдите в Яндекс-аккаунт в открытом браузере...")
            logger.info("[Dzen] После входа нажмите Enter в консоли...")

            # Ждём ручного входа
            input("[Dzen] Нажмите Enter после входа в аккаунт...")

            # Сохраняем cookies
            cookies = context.cookies()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)

            logger.info(f"[Dzen] Cookies сохранены: {path}")
            browser.close()
            return True

    except Exception as e:
        logger.error(f"[Dzen] Ошибка сохранения cookies: {e}")
        return False


def post_to_dzen(title: str, content: str, image_url: str = "") -> bool:
    """Публикация статьи в Дзен через Playwright."""
    sp = _try_playwright()
    if not sp:
        logger.error("Playwright not installed")
        return False

    cookies_path = config.DZEN_COOKIES_PATH
    if not os.path.exists(cookies_path):
        logger.error(f"[Dzen] Cookies не найдены: {cookies_path}")
        logger.error("[Dzen] Запустите save_dzen_cookies() для авторизации")
        return False

    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception as e:
        logger.error(f"[Dzen] Ошибка чтения cookies: {e}")
        return False

    try:
        with sp() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="ru-RU",
            )

            # Загружаем cookies
            context.add_cookies(cookies)
            page = context.new_page()

            # Убираем WebDriver флаг
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
            """)

            # Переходим в редактор Дзена
            page.goto("https://dzen.ru/id/editor/new_post", timeout=30000)
            time.sleep(3)

            # Проверяем, авторизованы ли мы
            if "passport" in page.url or "login" in page.url:
                logger.error("[Dzen] Не авторизован. Обновите cookies.")
                browser.close()
                return False

            # Вводим заголовок
            title_input = page.query_selector(
                '[data-testid="post-title"], [class*="title"], textarea[placeholder*="заголовок"], h1[contenteditable]'
            )
            if title_input:
                title_input.click()
                title_input.fill(title)
                time.sleep(1)

            # Вводим контент
            content_area = page.query_selector(
                '[data-testid="post-content"], [class*="editor"], [contenteditable="true"]:not(h1), .ProseMirror'
            )
            if content_area:
                content_area.click()
                # Вставляем текст через clipboard
                page.evaluate(f"""
                    const el = document.activeElement;
                    el.innerHTML = `{content.replace('`', '\\`')}`;
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                """)
                time.sleep(1)

            # Публикуем
            publish_btn = page.query_selector(
                'button[data-testid="publish"], button:has-text("Опубликовать"), button:has-text("Publish")'
            )
            if publish_btn:
                publish_btn.click()
                time.sleep(3)
                logger.info("[Dzen] Пост опубликован")
                browser.close()
                return True
            else:
                logger.warning("[Dzen] Кнопка публикации не найдена")
                # Пробуем найти любую кнопку отправки
                buttons = page.query_selector_all("button")
                for btn in buttons:
                    text = btn.inner_text().lower()
                    if any(w in text for w in ["опубликовать", "отправить", "publish", "send"]):
                        btn.click()
                        time.sleep(3)
                        logger.info("[Dzen] Пост опубликован (alt)")
                        browser.close()
                        return True

            browser.close()
            return False

    except Exception as e:
        logger.error(f"[Dzen] Ошибка публикации: {e}")
        return False


def post_article_to_dzen(title: str, body_html: str, tags: list[str] = None) -> bool:
    """Публикация статьи с HTML-контентом и тегами."""
    # Формируем контент с тегами
    content = body_html
    if tags:
        tag_str = " ".join(f"#{t}" for t in tags)
        content += f"\n\n{tag_str}"

    return post_to_dzen(title, content)
