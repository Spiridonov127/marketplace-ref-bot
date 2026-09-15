"""Генерирует статью (с AI-текстом от Groq, если задан GROQ_API_KEY) и
сохраняет её как черновик в data/drafts/ — ничего не публикует в Дзен и не
помечает товары как опубликованные. Для проверки текста перед реальным
постом. Запускать из корня marketplace-ref-bot:
    python3 scripts/preview_article.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from database import Database
from content_generator import generate_dzen_article, generate_dzen_post_text
from referral_builder import build_ym_cpa_link


def main():
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

    if config.GROQ_API_KEY:
        print("GROQ_API_KEY найден — пробуем сгенерировать AI-текст...")
    else:
        print("GROQ_API_KEY не задан — будет использован запасной шаблонный текст")

    title, body_html = generate_dzen_article(products)
    text = generate_dzen_post_text(products)

    os.makedirs("data/drafts", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"data/drafts/preview_{ts}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"## HTML (для Дзена)\n\n{body_html}\n\n")
        f.write(f"## Текст (для копирования)\n\n{text}\n")

    print(f"Превью сохранено: {path}")
    print("Товары НЕ помечены как опубликованные — можно смотреть и генерировать заново сколько угодно раз.")


if __name__ == "__main__":
    main()
