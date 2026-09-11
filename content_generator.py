"""Генератор контента для постов в Telegram-канале."""
import random
from datetime import datetime
from typing import Optional

from models import Product, Marketplace


# Эмодзи для заголовков
HEADERS = [
    "\U0001F525 ГОРЯЩИЕ СКИДКИ",
    "\U0001F381 ВЫГОДНЫЕ ПОКУПКИ",
    "\U0001F4B0 ЛУЧШИЕ ЦЕНЫ",
    "\U0001F6D2 ШОПИНГ ДНЯ",
    "\U0001F4A1 ВЫГОДНАЯ НАХОДКА",
    "\U0001F3C6 ТОП ПРЕДЛОЖЕНИЯ",
    "\U0001F48E СКИДКИ ДНЯ",
    "\U0001F9E7 ЗОЛОТЫЕ СДЕЛКИ",
]

# Эмодзи для рейтинга
RATING_EMOJI = {5: "\u2b50\u2b50\u2b50\u2b50\u2b50", 4: "\u2b50\u2b50\u2b50\u2b50", 3: "\u2b50\u2b50\u2b50"}

# Тексты для CTA
CTAS = [
    "\U0001F449 Купить по ссылке",
    "\U0001F6D2 Перейти к покупке",
    "\u27a1\ufe0f Смотреть предложение",
    "\U0001F445 Забрать скидку",
    "\U0001f525 Успеть купить",
]


def format_price(price: float) -> str:
    return f"{price:,.0f}".replace(",", " ")


def rating_stars(rating: float) -> str:
    if rating >= 4.5:
        return "\u2b50\u2b50\u2b50\u2b50\u2b50"
    elif rating >= 4.0:
        return "\u2b50\u2b50\u2b50\u2b50"
    elif rating >= 3.0:
        return "\u2b50\u2b50\u2b50"
    return ""


def discount_badge(discount: int) -> str:
    if discount >= 60:
        return "\U0001F525\U0001F525\U0001F525"
    elif discount >= 40:
        return "\U0001F525\U0001F525"
    elif discount >= 25:
        return "\U0001F525"
    return "\u27a1\ufe0f"


def product_block(p: Product, index: int = 1) -> str:
    lines = []

    # Заголовок товара
    lines.append(f"\n<b>{index}. {p.marketplace.emoji} {p.name}</b>")

    # Бренд
    if p.brand:
        lines.append(f"\U0001F3F7\ufe0f {p.brand}")

    # Рейтинг и отзывы
    if p.rating > 0:
        stars = rating_stars(p.rating)
        reviews_text = f"{p.reviews_count} отзывов" if p.reviews_count > 0 else ""
        lines.append(f"{stars} {p.rating:.1f} {reviews_text}")

    # Цены
    badge = discount_badge(p.discount_percent)
    lines.append(
        f"\u274c <s>{format_price(p.price_original)} \u20bd</s>"
    )
    lines.append(
        f"\u2705 <b>{format_price(p.price_sale)} \u20bd</b> "
        f"\u2014 <b>\u2193 {p.discount_percent}%</b> {badge}"
    )
    lines.append(
        f"\U0001F4B0 Экономия: {format_price(p.savings)} \u20bd"
    )

    # Маркетплейс
    lines.append(f"\U0001F4E6 {p.marketplace.display_name}")

    # CTA
    cta = random.choice(CTAS)
    lines.append(f'<a href="{p.referral_url or p.url}">{cta}</a>')

    return "\n".join(lines)


def generate_post(products: list[Product], style: str = "auto") -> str:
    if not products:
        return ""

    # Заголовок
    header = random.choice(HEADERS)
    date_str = datetime.now().strftime("%d.%m.%Y")
    parts = [f"<b>{header}</b> {date_str}"]

    # Товары
    for i, p in enumerate(products, 1):
        parts.append(product_block(p, i))

    # Разделитель и хвост
    parts.append("\n" + "\u2500" * 30)

    # Хештеги
    marketplaces = list({p.marketplace.display_name for p in products})
    hashtags = " ".join(f"#{m.replace(' ', '')}" for m in marketplaces)
    parts.append(f"\U0001F4CC {hashtags}")
    parts.append("#скидки #выгодно #покупки")

    # Подвал
    parts.append(
        "\n\U0001F4E2 Подпишись на канал, чтобы не пропустить лучшие скидки!"
    )

    return "\n".join(parts)


def generate_single_product_post(p: Product) -> str:
    """Генерация поста для одного товара — подробный формат."""
    header = random.choice(HEADERS)
    badge = discount_badge(p.discount_percent)
    parts = [
        f"<b>{header}</b>",
        "",
        f"<b>{p.marketplace.emoji} {p.name}</b>",
    ]

    if p.brand:
        parts.append(f"\U0001F3F7\ufe0f {p.brand}")

    parts.append("")

    # Блок цен
    parts.append(f"\u274c Было: <s>{format_price(p.price_original)} \u20bd</s>")
    parts.append(
        f"\u2705 Стало: <b>{format_price(p.price_sale)} \u20bd</b> {badge}"
    )
    parts.append(f"\U0001F4B0 Экономия: <b>{format_price(p.savings)} \u20bd (-{p.discount_percent}%)</b>")

    if p.rating > 0:
        parts.append(f"\n{rating_stars(p.rating)} {p.rating:.1f}/5 ({p.reviews_count} \u043e\u0442\u0437\u044b\u0432\u043e\u0432)")

    parts.append(f"\U0001F4E6 {p.marketplace.display_name}")

    cta = random.choice(CTAS)
    parts.append(f'\n<a href="{p.referral_url or p.url}">{cta} \u2192</a>')
    parts.append("\n\U0001F4CC #скидки #выгодно #покупки")

    return "\n".join(parts)


def generate_digest_post(top_products: dict[Marketplace, list[Product]]) -> str:
    """Дайджест: лучшая скидка с каждого маркетплейса."""
    parts = ["<b>\U0001F4F0 ДАЙДЖЕСТ ЛУЧШИХ СКИДОК ДНЯ</b>\n"]
    for mp, products in top_products.items():
        if not products:
            continue
        p = products[0]
        parts.append(
            f"{mp.emoji} <b>{mp.display_name}</b>\n"
            f"  {p.name}\n"
            f"  \u274c <s>{format_price(p.price_original)} \u20bd</s> "
            f"\u2192 \u2705 <b>{format_price(p.price_sale)} \u20bd</b> (-{p.discount_percent}%)\n"
            f'  <a href="{p.referral_url or p.url}">\U0001F6D2 Купить</a>\n'
        )
    parts.append("\n\U0001F4E2 Подписывайтесь, чтобы не пропустить скидки!")
    return "\n".join(parts)
