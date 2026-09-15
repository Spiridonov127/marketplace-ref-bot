"""Постинг в Яндекс Дзен через Playwright."""
import json
import logging
import os
import re
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


def _paste_html(page, element, html: str):
    """Вставляет HTML в contenteditable-редактор Дзена (это Draft.js — та же
    библиотека, что и в Facebook, видно по классу public-DraftEditor-content).

    Draft.js хранит контент в собственном внутреннем состоянии, а не читает его
    из DOM, поэтому обычная подстановка el.innerHTML эффект не даёт: редактор
    либо проигнорирует изменение, либо потом затрёт его при следующем вводе.
    Правильный путь — сымитировать реальную вставку из буфера обмена (событие
    paste с text/html), Draft.js сам умеет разбирать HTML в заголовки/ссылки/
    абзацы, как при обычном Ctrl+V.
    """
    element.click()
    page.evaluate(
        """([el, html]) => {
            el.focus();
            const dt = new DataTransfer();
            dt.setData('text/html', html);
            dt.setData('text/plain', el.innerText || '');
            const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
            el.dispatchEvent(ev);
        }""",
        [element, html],
    )


def _dismiss_help_overlay(page):
    """Закрывает обучающую подсказку ("Статья / Текст / Медиа / Черновики...")
    в новом черновике.

    Визуально карточка подсказки сидит внизу экрана, но её оверлей — это
    react-modal (класс ReactModal__Overlay), который растягивается на всю
    страницу и перехватывает клики даже по полю заголовка сверху, хотя на
    вид там пусто. react-modal по умолчанию закрывается по Esc и по клику
    на сам оверлей — пробуем оба варианта.
    """
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    try:
        overlay = page.locator(".ReactModal__Overlay")
        if overlay.count() > 0 and overlay.first.is_visible():
            # Кликаем в верхний левый угол оверлея — там точно нет самой
            # карточки подсказки (она внизу), только фон.
            overlay.first.click(position={"x": 10, "y": 10}, timeout=3000)
            page.wait_for_timeout(500)
    except Exception as e:
        logger.warning(f"[Dzen] Не удалось закрыть обучающую подсказку: {e}")


def _extract_channel_id(draft_url: str) -> Optional[str]:
    """Достаёт id канала из ссылки вида
    https://dzen.ru/profile/editor/id/<channel_id>/<draft_id>/edit.

    Id черновика каждый раз новый (создаётся заново, см. _create_new_draft),
    а id канала стабилен — поэтому его один раз можно достать из старой
    ссылки на черновик (DZEN_DRAFT_URL в .env) и использовать для захода в
    саму Студию, откуда уже создаётся новый черновик через "+".
    """
    if not draft_url:
        return None
    m = re.search(r"/profile/editor/id/([a-f0-9]+)/", draft_url)
    return m.group(1) if m else None


def _create_new_draft(page, channel_id: str) -> bool:
    """Создаёт новый пустой черновик статьи через "+" в шапке Дзен-студии.

    Открывает главную страницу Студии канала, кликает по кнопке
    add-publication-button (иконка "+" в правом верхнем углу), в открывшемся
    меню выбирает "Написать статью" (там же ещё "Написать пост" и "Загрузить
    видео" — не подходят). Дзен-студия — SPA, переход в редактор происходит
    через History API без полной перезагрузки страницы, поэтому ждём именно
    смену URL на паттерн нового черновика, а не networkidle/load.
    """
    page.goto(
        f"https://dzen.ru/profile/editor/id/{channel_id}",
        timeout=30000,
        wait_until="domcontentloaded",
    )
    page.wait_for_timeout(2500)
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass

    add_btn = page.locator('[data-testid="add-publication-button"]')
    try:
        add_btn.wait_for(timeout=10000)
        add_btn.click()
    except Exception as e:
        logger.error(f"[Dzen] Не нашёл кнопку создания публикации (url={page.url}): {e}")
        return False

    write_article = page.locator('[aria-label="Написать статью"]')
    try:
        write_article.wait_for(timeout=5000)
        write_article.click()
    except Exception as e:
        logger.error(f"[Dzen] Не нашёл пункт меню 'Написать статью': {e}")
        return False

    try:
        page.wait_for_url(
            re.compile(r"/profile/editor/id/[a-f0-9]+/[a-f0-9]+/edit"),
            timeout=15000,
        )
    except Exception as e:
        logger.error(f"[Dzen] Не дождался перехода в новый черновик (url={page.url}): {e}")
        return False

    # На свежесозданном черновике редактор сначала отрисовывается пустым, а
    # затем — уже после смены URL — асинхронно подтягивает и накатывает
    # реальное (тоже пустое) состояние документа с сервера. Если начать
    # печатать до того, как это подтягивание завершилось, оно перетирает уже
    # введённый текст обратно на пустой — именно это и происходило раньше
    # (в скриншоте текст был виден сразу после ввода, а через пару минут
    # черновик оказывался пустым). На уже существующем черновике такой гонки
    # не было, потому что там нечего было подтягивать заново поверх ввода.
    # Ждём сначала завершения сетевой активности, потом небольшой буфер.
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    logger.info(f"[Dzen] Новый черновик создан: {page.url}")
    return True


def fill_article(page, title_input, body_input, title: str, content: str) -> dict:
    """Заполняет заголовок и тело статьи в уже открытом черновике, с одной
    автоматической повторной попыткой, если после первого раза что-то не
    закрепилось.

    Вынесено из post_to_dzen в отдельную функцию, чтобы её же можно было
    использовать в тестовом скрипте на реальном контенте (с картинками) без
    публикации — оба места гоняют один и тот же код заполнения, а не два
    похожих, которые могут разъехаться.

    Здесь чинятся две реальные, воспроизводимые гонки инициализации
    редактора на свежесозданном черновике:
    1) текст визуально вставляется, но внутреннее состояние Draft.js его не
       регистрирует и следующим ре-рендером стирает обратно на пустое;
    2) картинки Дзен закачивает на свой сервер асинхронно по одной на
       каждую <img> из вставленного HTML, и если не подождать эту сетевую
       активность, часть картинок (на практике — обычно первая) не успевает
       долиться и пропадает из итогового черновика.

    Возвращает {"title_text", "body_text", "img_count", "expected_images"} —
    вызывающий код сам решает, публиковать или нет и что писать в лог.
    """
    expected_images = content.count("<img")

    def _fill_once():
        title_input.click()
        title_input.fill(title)
        page.wait_for_timeout(500)
        _paste_html(page, body_input.element_handle(), content)
        page.wait_for_timeout(2000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        try:
            page.get_by_text(re.compile("Сохранено")).first.wait_for(timeout=15000)
        except Exception:
            pass

    def _check():
        t = (title_input.inner_text() or "").strip()
        b = (body_input.inner_text() or "").strip()
        imgs = body_input.locator("img").count()
        return t, b, imgs

    _fill_once()
    title_text, body_text, img_count = _check()

    if not title_text or not body_text or img_count < expected_images:
        logger.warning(
            f"[Dzen] После заполнения не всё на месте (заголовок={title_text!r}, "
            f"длина текста={len(body_text)}, картинок {img_count}/{expected_images}) "
            f"— пробую заполнить ещё раз"
        )
        _fill_once()
        title_text, body_text, img_count = _check()

    return {
        "title_text": title_text,
        "body_text": body_text,
        "img_count": img_count,
        "expected_images": expected_images,
    }


def post_to_dzen(title: str, content: str, image_url: str = "") -> bool:
    """Публикация статьи в Дзен через Playwright.

    На каждый запуск создаётся НОВЫЙ черновик статьи (клик по "+" в шапке
    Студии, см. _create_new_draft) — конкретный id канала при этом берётся
    из config.DZEN_DRAFT_URL (см. _extract_channel_id), а сам старый
    черновик по этой ссылке больше не используется и не перезаписывается.
    """
    sp = _try_playwright()
    if not sp:
        logger.error("Playwright not installed")
        return False

    cookies_path = config.DZEN_COOKIES_PATH
    if not os.path.exists(cookies_path):
        logger.error(f"[Dzen] Cookies не найдены: {cookies_path}")
        logger.error("[Dzen] Запустите save_dzen_cookies() для авторизации")
        return False

    channel_id = _extract_channel_id(config.DZEN_DRAFT_URL)
    if not channel_id:
        logger.error(
            "[Dzen] Не удалось определить id канала: DZEN_DRAFT_URL в .env "
            "пуст или не похож на ссылку вида .../profile/editor/id/<id>/..."
        )
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
                # Свежая версия Chrome — иначе Дзен показывает блокирующую
                # модалку "Ваша версия браузера устарела".
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                locale="ru-RU",
                viewport={"width": 1440, "height": 1000},
            )

            # Загружаем cookies
            context.add_cookies(cookies)
            page = context.new_page()

            # Убираем WebDriver флаг
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
            """)

            # Создаём новый пустой черновик статьи вместо захода в один и тот
            # же фиксированный DZEN_DRAFT_URL — так каждый пост уходит в
            # отдельную публикацию, а не затирает предыдущую.
            if not _create_new_draft(page, channel_id):
                browser.close()
                return False

            # Проверяем, авторизованы ли мы
            if "passport" in page.url or "login" in page.url:
                logger.error("[Dzen] Не авторизован. Обновите cookies.")
                browser.close()
                return False

            editor_root = page.locator('[data-testid="editor-root"]')
            try:
                editor_root.wait_for(timeout=10000)
            except Exception as e:
                logger.error(f"[Dzen] Редактор не загрузился (url={page.url}): {e}")
                browser.close()
                return False

            _dismiss_help_overlay(page)

            editable = editor_root.locator('[contenteditable="true"]')
            count = editable.count()
            if count < 2:
                logger.error(f"[Dzen] Ожидались поля заголовка и текста, найдено: {count}")
                browser.close()
                return False

            # Первое contenteditable-поле в редакторе — заголовок, второе — тело статьи
            title_input = editable.nth(0)
            body_input = editable.nth(1)

            result = fill_article(page, title_input, body_input, title, content)

            if not result["title_text"] or not result["body_text"]:
                logger.error(
                    f"[Dzen] Черновик остался пустым после двух попыток заполнения "
                    f"(url={page.url}) — публикацию отменяю, чтобы не запостить пустоту"
                )
                browser.close()
                return False

            if result["img_count"] < result["expected_images"]:
                logger.warning(
                    f"[Dzen] После двух попыток картинок всё равно меньше, чем в контенте "
                    f"({result['img_count']}/{result['expected_images']}, url={page.url}) — "
                    f"публикую как есть, но стоит проверить пост глазами после публикации"
                )

            # Публикуем. Клик по этой кнопке НЕ публикует статью сразу — он
            # только открывает модалку "Публикация" с настройками (кто может
            # комментировать, дата публикации и т.п.). Раньше код на этом
            # останавливался и считал дело сделанным, из-за чего все статьи
            # реально оставались черновиками в Дзене, хотя лог показывал
            # "Пост опубликован" — подтверждено диагностикой
            # debug_dzen_publish_flow.py на живом черновике.
            publish_btn = page.locator('[data-testid="article-publish-btn"]')
            try:
                publish_btn.wait_for(timeout=8000)
                publish_btn.click()
            except Exception as e:
                logger.error(f"[Dzen] Не удалось нажать 'Опубликовать': {e}")
                browser.close()
                return False

            # Реальную публикацию завершает ОТДЕЛЬНАЯ кнопка "Опубликовать"
            # ВНУТРИ открывшейся модалки — у неё другой data-testid
            # ("publish-btn"), не путать с кнопкой выше ("article-publish-btn").
            # В той же модалке есть похожая по смыслу "Опубликовать позже"
            # (отложенная публикация) — её не трогаем.
            confirm_btn = page.locator('[data-testid="publish-btn"]')
            try:
                confirm_btn.wait_for(state="visible", timeout=8000)
                confirm_btn.click()
                page.wait_for_timeout(3000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                # После успешной публикации модалка должна закрыться сама.
                # Если она всё ещё видна спустя все ожидания выше — скорее
                # всего Дзен показал валидационную ошибку и статья НЕ
                # опубликована, а осталась черновиком. Именно молчаливое
                # "успех, раз клик не упал с ошибкой" и было причиной
                # исходного бага — здесь эту же ошибку не повторяем и
                # считаем это провалом публикации, а не предупреждением.
                try:
                    confirm_btn.wait_for(state="hidden", timeout=5000)
                except Exception:
                    logger.error(
                        "[Dzen] Модалка публикации не закрылась после клика "
                        "по финальной кнопке — статья, вероятно, осталась "
                        "черновиком, публикацию считаю неуспешной"
                    )
                    browser.close()
                    return False
                logger.info("[Dzen] Пост опубликован")
                browser.close()
                return True
            except Exception as e:
                logger.error(f"[Dzen] Не удалось подтвердить публикацию в модалке: {e}")
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
