"""Генератор контента для Дзена: статьи с CPA-ссылками и маркировкой ОРИ."""
import html
import random
import re
from datetime import datetime
from models import Product, Marketplace
from referral_builder import build_ym_cpa_link, get_post_footer
from article_writer import generate_ai_copy, generate_single_product_copy
from reviews_extractor import real_cons_from_reviews, real_pros_from_reviews


def format_price(price: float) -> str:
    return f"{price:,.0f}".replace(",", " ")


def _fallback_titles(products: list[Product]) -> list[str]:
    return [
        f"Топ-{len(products)} скидок на Яндекс Маркете до -{max(p.discount_percent for p in products)}%",
        f"Горящие предложения Яндекс Маркета: экономия до {format_price(max(p.savings for p in products))} ₽",
        f"Лучшие deals дня на Яндекс Маркете — скидки до {max(p.discount_percent for p in products)}%",
        f"Выбрали для вас: {len(products)} товаров с большими скидками на Яндекс Маркете",
    ]


def _shorten_product_name(name: str, max_len: int = 60) -> str:
    """Обрезает название до бренда/модели, убирая технические характеристики
    (объём памяти, цвет, комплектацию и т.п.), которые Яндекс Маркет обычно
    дописывает через запятую или в скобках — например, "Смартфон Xiaomi
    Redmi Note 12, 8/256 ГБ, чёрный" превращается в "Смартфон Xiaomi Redmi
    Note 12". Используется как запасной вариант, если AI не вернул short_name.
    """
    if not name:
        return name
    cut = re.split(r"[,(]|\s[-–—]\s", name, maxsplit=1)[0].strip()
    if not cut:
        cut = name.strip()
    if len(cut) > max_len:
        cut = cut[:max_len].rsplit(" ", 1)[0].rstrip() + "…"
    return cut


def _fallback_item(p: Product, reviews: list[dict] = None) -> dict:
    """Запасной (без AI) набор текста для товара — длиннее старого шаблона,
    но по-прежнему построен только из реальных данных о товаре, ничего не
    выдумываем сверх того, что реально известно.
    """
    sentences = []
    if p.brand:
        sentences.append(f"Это товар от бренда {p.brand}.")
    if p.rating > 0 and p.reviews_count > 0:
        sentences.append(
            f"Его уже оценили {p.reviews_count} покупателей — средняя оценка "
            f"{p.rating:.1f} из 5."
        )
    elif p.rating > 0:
        sentences.append(f"Средняя оценка покупателей — {p.rating:.1f} из 5.")
    sentences.append(
        "Сейчас на него действует заметная скидка на Яндекс Маркете, так что "
        "если товар в целом подходит под ваш запрос — самое время "
        "присмотреться к нему внимательнее и сравнить с аналогами."
    )
    sentences.append(
        "Полное описание, комплектацию и все характеристики удобнее всего "
        "смотреть прямо на странице товара по ссылке ниже."
    )

    pros = []
    if p.discount_percent > 0:
        pros.append(f"Скидка {p.discount_percent}% от обычной цены")
    if p.rating >= 4:
        pros.append(f"Высокий рейтинг {p.rating:.1f}/5")
    if p.reviews_count >= 50:
        pros.append(f"Уже {p.reviews_count} отзывов покупателей")
    if p.brand:
        pros.append(f"Товар от бренда {p.brand}")
    if not pros:
        pros.append("Актуальное предложение на Яндекс Маркете")

    # Реальные недостатки — только из настоящих отзывов покупателей, никогда
    # не выдумываем и не подставляем общую фразу-заглушку вместо них: если
    # среди отзывов нет ни одного заполненного "Недостатки", это честно
    # означает пустой список, и блок "Минусы" в статье просто не покажется.
    cons = real_cons_from_reviews(reviews)
    extra_pros = real_pros_from_reviews(reviews)
    for rp in extra_pros:
        if rp not in pros:
            pros.append(rp)

    return {
        "short_name": _shorten_product_name(p.name),
        "description": " ".join(sentences),
        "pros": pros[:4],
        "cons": cons,
    }


def generate_dzen_article(
    products: list[Product], reviews_by_product: list[list[dict]] = None
) -> tuple[str, str]:
    """Генерирует (заголовок, HTML-тело) для статьи в Дзене.

    Описательный текст (вступление, абзац на товар, заключение) пробуем
    получить от Groq — раньше вместо него был сухой шаблон, и статья
    превращалась в таблицу характеристик. Цена, скидка, рейтинг, картинка и
    CPA-ссылка всегда собираются здесь из реальных данных о товаре, а не из
    ответа модели, так что даже если AI недоступен или ответил странно,
    цифры и ссылки в статье всегда верные — меняется только наличие
    живого текста.

    reviews_by_product (если передан) — список реальных отзывов покупателей
    по каждому товару (в том же порядке, что products), от
    reviews_extractor.get_reviews_for_products(). "Минусы" в статье ВСЕГДА
    строятся только из них (никогда от AI и никогда фразой-заглушкой) — если
    отзывов с недостатками нет, блок "Минусы" просто не появится.
    """
    if not products:
        return "", ""

    if reviews_by_product is None:
        reviews_by_product = [[] for _ in products]

    ai = generate_ai_copy(products)

    if ai:
        title = ai.get("title") or random.choice(_fallback_titles(products))
        intro_text = ai.get("intro", "")
        outro_text = ai.get("outro", "")
        items_data = ai.get("items") or [None] * len(products)
    else:
        title = random.choice(_fallback_titles(products))
        intro_text = (
            "Собрали для вас лучшие предложения на Яндекс Маркете. "
            "Все товары со значительными скидками — смотрите, вдруг пригодится."
        )
        outro_text = ""
        items_data = [None] * len(products)

    parts = []

    if intro_text:
        parts.append(f"<p>{html.escape(intro_text)}</p>")

    for i, p in enumerate(products, 1):
        cpa_link = build_ym_cpa_link(p.url)
        reviews = reviews_by_product[i - 1] if i - 1 < len(reviews_by_product) else []
        data = items_data[i - 1] if i - 1 < len(items_data) else None
        if not data or not data.get("description"):
            data = _fallback_item(p, reviews)

        short_name = data.get("short_name") or _shorten_product_name(p.name)
        blurb = data.get("description") or ""
        pros = list(data.get("pros") or [])
        # "Минусы" — всегда только из настоящих отзывов покупателей, даже если
        # текст описания и "Плюсы" пришли от AI: AI больше не генерирует cons
        # (см. article_writer._build_prompt), а старую фразу-заглушку
        # ("уточните на странице товара") пользователь явно попросил убрать.
        cons = real_cons_from_reviews(reviews)
        for rp in real_pros_from_reviews(reviews):
            if rp not in pros:
                pros.append(rp)

        parts.append(f'<h2>{i}. {html.escape(short_name)}</h2>')

        if p.image_url:
            parts.append(
                f'<p><img src="{html.escape(p.image_url)}" alt="{html.escape(short_name)}"></p>'
            )

        if blurb:
            parts.append(f'<p>{html.escape(blurb)}</p>')

        if p.brand:
            parts.append(f'<p><strong>Бренд:</strong> {html.escape(p.brand)}</p>')

        if p.rating > 0:
            stars = "⭐" * int(p.rating)
            if p.reviews_count > 0:
                parts.append(
                    f'<p>{stars} {p.rating:.1f}/5 ({p.reviews_count} отзывов)</p>'
                )
            else:
                # Скрываем "(0 отзывов)" — иногда Маркет не отдаёт число
                # отзывов в разметке страницы, хотя реальный рейтинг есть;
                # показывать заведомо неверный ноль хуже, чем не показывать
                # число вовсе.
                parts.append(f'<p>{stars} {p.rating:.1f}/5</p>')

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

        if pros:
            pros_html = "".join(f"<li>{html.escape(x)}</li>" for x in pros)
            parts.append(f"<p><strong>Плюсы:</strong></p><ul>{pros_html}</ul>")
        if cons:
            cons_html = "".join(f"<li>{html.escape(x)}</li>" for x in cons)
            parts.append(f"<p><strong>Минусы:</strong></p><ul>{cons_html}</ul>")

        # CPA-ссылка
        parts.append(
            f'<p><a href="{cpa_link}" target="_blank">'
            f'Перейти к покупке на Яндекс Маркете</a></p>'
        )

        parts.append('<hr>')

    if outro_text:
        parts.append(f"<p>{html.escape(outro_text)}</p>")

    # Футер с маркировкой
    footer = get_post_footer()
    if footer:
        parts.append(f'<p><small>{footer}</small></p>')

    body = "\n".join(parts)
    return title, body


def generate_single_product_article(p: Product, topic: str = "") -> tuple[str, str]:
    """Статья-обзор об ОДНОМ товаре: заголовок, фото, живой текст, ссылка.

    Это второй режим работы бота (см. scheduler.run_post_cycle_for_query).
    Обычный запрос вроде "шапка" даёт именно такую статью: просто текст про
    вещь, без отзывов покупателей, без оценок и без списков плюсов/минусов —
    их пользователь просил показывать только когда он прямо просит подборку.
    Цену и скидку здесь тоже не показываем: цифры быстро устаревают, а
    отдельного блока с ними в этом формате нет, поэтому и в тексте модели
    запрещено на них ссылаться (см. article_writer._build_single_prompt).

    Маркировка рекламы (erid) добавляется НЕ здесь, а выше по стеку, в
    scheduler._apply_ad_marking — ровно так же, как для подборки: правила
    маркировки в обоих режимах одинаковые.
    """
    if not p:
        return "", ""

    ai = generate_single_product_copy(p, topic)

    short_name = _shorten_product_name(p.name)

    if ai and ai.get("paragraphs"):
        title = ai.get("title") or short_name
        paragraphs = ai["paragraphs"]
    else:
        title = short_name
        # Запасной текст без AI — сознательно общий: про сам товар достоверно
        # известны только название и бренд, поэтому ничего "характерного" мы
        # тут придумать не можем и не пытаемся.
        paragraphs = []
        if p.brand:
            paragraphs.append(
                f"{short_name} — товар от бренда {p.brand}, который сейчас "
                f"можно посмотреть на Яндекс Маркете."
            )
        else:
            paragraphs.append(
                f"{short_name} — один из вариантов, которые сейчас можно "
                f"посмотреть на Яндекс Маркете."
            )
        paragraphs.append(
            "Выбирая такую вещь, стоит заранее прикинуть, как часто и в каких "
            "условиях вы будете ей пользоваться — от этого обычно и зависит, "
            "какой вариант окажется удачным именно для вас."
        )
        paragraphs.append(
            "Прежде чем оформлять заказ, полезно сравнить несколько похожих "
            "моделей между собой: обратите внимание на отзывы других "
            "покупателей, на то, для каких задач вещь позиционируется "
            "производителем, и насколько она впишется именно в ваш сценарий "
            "использования — иногда самая популярная модель оказывается вовсе "
            "не той, что нужна лично вам."
        )
        paragraphs.append(
            "Такие покупки редко бывают спонтанными: обычно к ним присматриваются "
            "заранее, читают отзывы, сравнивают цены в разных магазинах — и "
            "Яндекс Маркет как раз удобен тем, что собирает предложения от "
            "разных продавцов в одном месте, а значит можно быстро прикинуть, "
            "какой вариант выгоднее именно сейчас."
        )
        paragraphs.append(
            "Отдельное внимание стоит уделить отзывам покупателей — не только "
            "общей оценке в звёздах, но и тому, что именно люди пишут в тексте. "
            "Общая цифра рейтинга усредняет очень разный опыт, а вот "
            "конкретные комментарии обычно точнее показывают, подойдёт ли "
            "вещь именно под ваш случай использования."
        )
        paragraphs.append(
            "Полезно обращать внимание и на то, кто именно продаёт товар: у "
            "одной и той же модели на Маркете нередко бывает сразу несколько "
            "продавцов с разной ценой, сроками доставки и условиями возврата "
            "— иногда выгоднее взять не самое дешёвое предложение, а то, у "
            "которого удобнее логистика или надёжнее продавец."
        )
        paragraphs.append(
            "Если покупка не срочная, имеет смысл последить за ценой несколько "
            "дней: на маркетплейсах цены довольно живые и часто снижаются во "
            "время акций или распродаж — иногда достаточно немного подождать, "
            "чтобы купить то же самое заметно дешевле."
        )
        paragraphs.append(
            "Перед оформлением заказа стоит ещё раз свериться с точными "
            "параметрами на странице товара — производители периодически "
            "обновляют линейки и характеристики, поэтому надёжнее опираться "
            "на актуальное описание у продавца, а не на общие представления "
            "о модели."
        )
        paragraphs.append(
            "Если вещь берётся в подарок, дополнительно стоит прикинуть, "
            "насколько она универсальна: подходит ли под разные вкусы и "
            "ситуации, легко ли будет вернуть или обменять при необходимости "
            "— у большинства продавцов на Маркете такая возможность "
            "предусмотрена в течение определённого срока после покупки."
        )
        paragraphs.append(
            "Способ доставки тоже стоит выбирать осознанно: где-то важнее "
            "скорость (курьером в течение дня), а где-то — цена, и тогда "
            "выгоднее пункт выдачи. На карточке товара обычно сразу видно "
            "несколько вариантов доставки с разными сроками — удобно "
            "сопоставить их со своим графиком заранее, а не в момент оформления."
        )
        paragraphs.append(
            "Наконец, не стоит недооценивать фотографии в карточке товара — "
            "обычно продавцы выкладывают не только студийные снимки, но и "
            "реальные фото от покупателей в отзывах. Они часто честнее "
            "показывают цвет, размер и качество материалов, чем "
            "профессиональная съёмка, и помогают избежать разочарования "
            "после получения заказа."
        )
        paragraphs.append(
            "Полное описание, характеристики и комплектацию удобнее всего "
            "смотреть прямо на странице товара по ссылке ниже — там же видно "
            "актуальную цену, наличие у конкретных продавцов и условия доставки."
        )

    parts = []

    if p.image_url:
        parts.append(
            f'<p><img src="{html.escape(p.image_url)}" alt="{html.escape(short_name)}"></p>'
        )

    for para in paragraphs:
        parts.append(f"<p>{html.escape(para)}</p>")

    cpa_link = build_ym_cpa_link(p.url)
    parts.append(
        f'<p><a href="{cpa_link}" target="_blank">'
        f'Посмотреть на Яндекс Маркете</a></p>'
    )

    footer = get_post_footer()
    if footer:
        parts.append(f'<p><small>{footer}</small></p>')

    return title, "\n".join(parts)


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
        parts.append(f"   ❌ {format_price(p.price_original)} ₽ → ✅ {format_price(p.price_sale)} ₽ (-{p.discount_percent}%)")
        parts.append(f"   \U0001F4B0 Экономия: {format_price(p.savings)} ₽")
        parts.append(f"   \U0001F517 {cpa_link}")
        parts.append("")

    footer = get_post_footer()
    if footer:
        parts.append(footer)

    return "\n".join(parts)
