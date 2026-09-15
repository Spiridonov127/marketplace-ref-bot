"""Диагностика: полный цикл получения erid и готовой маркированной ссылки
через генератор Яндекс Дистрибуции — автоматически, без ручных кликов.

Ничего не публикует. Реально создаёт одну тестовую партнёрскую ссылку с
токеном (это штатное действие в личном кабинете, не имеет побочных
эффектов кроме появления записи в истории созданных ссылок).

Запускать из корня marketplace-ref-bot:
    python3 debug_distribution_generate.py "<ссылка на товар>"
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
    if len(sys.argv) < 2:
        print('Использование: python3 debug_distribution_generate.py "<ссылка на товар>"')
        return
    product_url = sys.argv[1]

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
        page.wait_for_timeout(2000)

        if "passport" in page.url:
            print("Не авторизован — обновите data/distribution_cookies.json")
            browser.close()
            return

        link_input = page.locator('textarea[placeholder="https://market.yandex.ru/"]')
        try:
            link_input.wait_for(timeout=15000)
        except Exception as e:
            print(f"Не нашёл поле ссылки: {e}")
            page.screenshot(path="data/debug_distr_gen_fail.png", full_page=True)
            browser.close()
            return

        link_input.click()
        link_input.fill(product_url)
        page.wait_for_timeout(500)

        print("Площадка (не трогаем, должна быть dzen.ru/tot_samiy):",
              page.locator('button[role="listbox"]').first.inner_text())

        get_token_btn = page.get_by_text("Получить токен в ОРД Яндекса", exact=True)
        try:
            get_token_btn.wait_for(state="attached", timeout=10000)
            get_token_btn.click(force=True, timeout=10000)
        except Exception as e:
            print(f"Не нашёл/не нажал кнопку получения токена: {e}")
            page.screenshot(path="data/debug_distr_gen_fail.png", full_page=True)
            browser.close()
            return

        # В модалке ДВА обязательных поля: "Общее описание креатива" (видно
        # сразу, плейсхолдер "Описание объекта рекламирования") и "Текст
        # креатива" (появляется после разворота "Добавить текст креатива").
        # Раньше заполнялось только второе — первое оставалось пустым и
        # подсвечивалось красным как обязательное, из-за чего "Продолжить"
        # не срабатывал и токен не появлялся. Заполняем оба.
        page.wait_for_timeout(1000)
        desc_input = page.locator('textarea[placeholder="Описание объекта рекламирования"]')
        try:
            desc_input.wait_for(state="visible", timeout=5000)
            desc_input.click(force=True)
            desc_input.fill("Тестовое общее описание объекта рекламирования.")
            print("Заполнил общее описание креатива")
        except Exception as e:
            print(f"Не удалось заполнить общее описание креатива: {e}")
        add_text_btn = page.get_by_text("Добавить текст креатива", exact=True)
        try:
            add_text_btn.wait_for(state="attached", timeout=8000)
            add_text_btn.click(force=True, timeout=8000)
            print("Развернул 'Добавить текст креатива'")
            page.wait_for_timeout(800)

            # После разворота должно появиться новое текстовое поле —
            # берём последнюю textarea в модалке (первая — описание креатива).
            modal_textareas = page.locator('textarea')
            count = modal_textareas.count()
            print(f"Textarea в модалке: {count}")
            if count >= 2:
                creative_text_input = modal_textareas.nth(count - 1)
                creative_text_input.click(force=True)
                creative_text_input.fill(
                    "Тестовый текст креатива для проверки автоматизации получения erid."
                )
                print("Заполнил текст креатива")
            else:
                print("Не нашёл отдельное поле для текста креатива после разворота")
        except Exception as e:
            print(f"Не удалось развернуть/заполнить текст креатива: {e}")
            page.screenshot(path="data/debug_distr_gen_modal.png", full_page=True)

        continue_btn = page.get_by_text("Продолжить", exact=True)
        try:
            continue_btn.wait_for(state="attached", timeout=8000)
            continue_btn.click(force=True, timeout=8000)
            print("Нажал 'Продолжить' в модалке ОРД")
        except Exception as e:
            print(f"Модалка 'Продолжить' не появилась/не нажалась (может, её и не было): {e}")

        # После получения токена поле "Токен для маркировки рекламы"
        # перерисовывается не совсем обычным образом — input_value() у него
        # не читается надёжно. Зато значение всегда видно в обычном тексте
        # страницы сразу после подписи поля — читаем именно так.
        import re as _re

        erid = ""
        for _ in range(20):  # до ~10 секунд
            page.wait_for_timeout(500)
            try:
                body_text = page.inner_text("body")
            except Exception:
                continue
            lines = [ln.strip() for ln in body_text.splitlines()]
            for i, ln in enumerate(lines):
                if ln == "Токен для маркировки рекламы":
                    for nxt in lines[i + 1:i + 4]:
                        if nxt and _re.fullmatch(r"[A-Za-z0-9]{10,40}", nxt):
                            erid = nxt
                            break
                    break
            if erid:
                break
        print(f"Получен erid: {erid!r}")

        if not erid:
            print("Токен не появился — смотри скриншот")
            page.screenshot(path="data/debug_distr_gen_no_token.png", full_page=True)
            # Дублируем весь текст видимых элементов — вдруг всплыла ошибка
            # валидации или модалка ещё не закрылась.
            try:
                print("Текст страницы (обрезано):", page.inner_text("body")[:1500])
            except Exception:
                pass
            browser.close()
            return

        create_btn = page.get_by_text("Создать ссылку", exact=True)
        try:
            create_btn.wait_for(state="attached", timeout=10000)
            create_btn.click(force=True, timeout=10000)
        except Exception as e:
            print(f"Не нашёл/не нажал 'Создать ссылку': {e}")
            page.screenshot(path="data/debug_distr_gen_fail2.png", full_page=True)
            browser.close()
            return

        page.wait_for_timeout(2500)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        page.screenshot(path="data/debug_distr_gen_result.png", full_page=True)
        print("Скриншот результата -> data/debug_distr_gen_result.png")

        # Дампим все input/textarea на странице после создания ссылки — среди
        # них должен появиться новый элемент с готовой ссылкой.
        candidates = page.query_selector_all("textarea, input")
        lines = []
        for el in candidates:
            try:
                val = el.input_value()
            except Exception:
                val = ""
            if val and ("market.yandex" in val or "yandex" in val.lower()):
                lines.append(val)
        with open("data/debug_distr_gen_values.txt", "w", encoding="utf-8") as f:
            f.write("\n---\n".join(lines))
        print(f"Найдено значений с ссылками: {len(lines)} -> data/debug_distr_gen_values.txt")

        browser.close()


if __name__ == "__main__":
    main()
