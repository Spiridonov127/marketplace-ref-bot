"""Генератор контента для Дзена: статьи с CPA-ссылками и маркировкой ОРИ."""
import random
from datetime import datetime
from models import Product, Marketplace
from referral_builder import build_ym_cpa_link, get_post_footer


def format_price(price: float) -> str:
    return f"{price:,.0f}".replace(",", " ")


def generate_dzen_article(products: list[Product]) -> tuple[str, str]:
    """Генерирует (заголовок, HTML-тело) для статьи в Дзене."""
    if not products:
        return "", ""

    # Заголовок
    titles = [
        f"Топ-{len(products)} скидок на Яндекс Маркете до -{max(p.discount_percent for p in products)}%",
        f"Горящие предложения Яндекс Маркета: экономия до {format_price(max(p.savings for p in products))} ₽",
        f"Лучшие deals дня на Яндекс Маркете — скидки до {max(p.discount_percent for p in products)}%",
        f"Выбрали для вас: {len(products)} товаров с большими скидками на Яндекс Маркете",
    ]
    title = random.choice(titles)

    # HTML тело статьи
    parts = []

    # Вступление
    parts.append(
        '<p>Собрали для вас лучшие предложения на Яндекс Маркете. '
        'Все товары со значительными скидками — успейте купить по выгодной цене!</p>'
    )

    # Товары
    for i, p in enumerate(products, 1):
        cpa_link = build_ym_cpa_link(p.url)

        parts.append(f'<h2>{i}. {p.name}</h2>')

        if p.brand:
            parts.append(f'<p><strong>Бренд:</strong> {p.brand}</p>')

        if p.rating > 0:
            stars = "\u2b50" * int(p.rating)
            parts.append(f'<p>{stars} {p.rating:.1f}/5 ({p.reviews_count} отзывов)</p>')

        parts.append(
            f'<p>'
            f'<s>{format_price(p.price_original)} ₽</s> '
            f'→ <strong>{format_price(p.price_sale)} ₽</strong> '
            f'(-{p.discount_percent}%)'
            f'</p>'
        )
        parts.append(
            f'<p>Экономия: <strong>{format_price(p.savings)} ₽</strong></p>'
        )

        # CPA-ссылка
        parts.append(
            f'<p><a href="{cpa_link}" target="_blank">'
            f'Перейти к покупке на Яндекс Маркете</a></p>'
        )

        parts.append('<hr>')

    # Футер с маркировкой
    footer = get_post_footer()
    if footer:
        parts.append(f'<p><small>{footer}</small></p>')

    # Хештеги
    parts.append(
        '<p>#скидки #выгодно #покупки #яндексмаркет #товары</p>'
    )

    body = "\n".join(parts)
    return title, body


def generate_dzen_post_text(products: list[Product]) -> str:
    """Генерирует текстовый пост (для Telegram или уведомлений)."""
    if not products:
        return ""

    parts = [
        f"\U0001F525 Скидки дня на Яндекс Маркете\n",
    ]

    for i, p in enumerate(products, 1):
        cpa_link = build_ym_cpa_link(p.url)
        parts.append(f"{i}. {p.name}")
        parts.append(f"   \u274c {format_price(p.price_original)} \u20bd → \u2705 {format_price(p.price_sale)} \u20bd (-{p.discount_percent}%)")
        parts.append(f"   \U0001F4B0 Экономия: {format_price(p.savings)} \u20bd")
        parts.append(f"   \U0001F517 {cpa_link}")
        parts.append("")

    footer = get_post_footer()
    if footer:
        parts.append(footer)

    return "\n".join(parts)
