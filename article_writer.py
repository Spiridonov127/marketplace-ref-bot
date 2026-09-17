"""Генерация живого текста статьи через Groq (бесплатный API, OpenAI-совместимый).

Модель пишет только описательный текст (вступление, пара предложений на товар,
заключение) — сама цена, скидка, рейтинг, картинка и CPA-ссылка всегда
собираются кодом в content_generator.py из реальных данных из БД, а не из
ответа модели. Так модель не может ошибиться в цифрах или испортить ссылку,
но текст всё равно получается живым и не повторяется от поста к посту.

Если GROQ_API_KEY не задан в .env, или запрос к Groq не удался (сеть, лимит,
невалидный JSON в ответе и т.п.) — возвращается None, и вызывающий код
(content_generator.generate_dzen_article) сам подставляет запасной шаблонный
текст. Публикация поста никогда не должна падать только из-за того, что AI
недоступен.
"""
import json
import logging
from typing import Optional

import requests

from config import config
from models import Product

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# На момент написания llama-3.3-70b-versatile и llama-3.1-8b-instant у Groq
# больше не существуют (сняты с линейки) — проверяли реальный список моделей
# через GET /openai/v1/models на конкретном ключе. gpt-oss-120b поддерживает
# json_mode и большой контекст, этого достаточно для наших задач.
GROQ_MODEL = "openai/gpt-oss-120b"


def _build_prompt(products: list[Product]) -> str:
    product_lines = []
    for i, p in enumerate(products, 1):
        product_lines.append(
            f"{i}. {p.name} | бренд: {p.brand or 'не указан'} | "
            f"цена {p.price_sale:.0f} ₽ (было {p.price_original:.0f} ₽, скидка {p.discount_percent}%) | "
            f"рейтинг {p.rating:.1f}/5 ({p.reviews_count} отзывов)"
        )

    return (
        "Ты пишешь статью для Яндекс Дзена о выгодных скидках на Яндекс Маркете. "
        "Пиши живо, по-человечески, без канцелярита и без рекламных штампов вроде "
        "\"успей купить\". Используй ТОЛЬКО факты из списка ниже — не выдумывай "
        "характеристики, комплектацию или преимущества товара, которых там нет. "
        "Если каких-то данных о товаре не хватает, просто не упоминай их.\n\n"
        "ВАЖНО: цену, старую цену, процент скидки и сумму экономии НЕ нужно "
        "упоминать в описании товара — они и так будут показаны отдельным "
        "блоком сразу под текстом.\n\n"
        "Для каждого товара верни:\n"
        "- short_name: короткое чистое название товара БЕЗ технических "
        "характеристик (объём памяти/накопителя, цвет, размер, комплектация, "
        "артикул и т.п.) — только бренд и модель, не длиннее 60 символов;\n"
        "- description: 5-7 живых развёрнутых предложений о самом товаре — "
        "для кого он, для какой ситуации подходит, чем может быть удобен, "
        "какие у него сильные стороны — без цифр цены/скидки, но так, чтобы "
        "читателю было интересно дочитать, а не сухой пересказ характеристик;\n"
        "- pros: список из 3-4 коротких реалистичных преимуществ, основанных "
        "ТОЛЬКО на данных из списка (бренд, скидка, рейтинг, число отзывов) и "
        "общих для этой категории плюсах — не выдумывай конкретные "
        "технические характеристики, которых нет в списке.\n\n"
        "НЕ придумывай и НЕ пиши поле cons/'Минусы' сам — реальные недостатки "
        "товара берутся отдельно из настоящих отзывов покупателей, а не от тебя. "
        "Если ты всё же вернёшь cons, они будут проигнорированы.\n\n"
        "Товары:\n" + "\n".join(product_lines) + "\n\n"
        "Верни ТОЛЬКО валидный JSON, без markdown-разметки вокруг него и без "
        "пояснений, в формате:\n"
        '{"title": "цепляющий заголовок статьи (не более 90 символов)", '
        '"intro": "1-2 живых вступительных предложения о подборке в целом", '
        '"items": [{"short_name": "...", '
        '"description": "5-7 предложений о товаре 1, без цены и скидки", '
        '"pros": ["...", "...", "..."]}, '
        '{"short_name": "...", "description": "...", "pros": [...]}, '
        '"..."], '
        '"outro": "1-2 заключительных предложения"}\n\n'
        f"В массиве items должно быть ровно {len(products)} элементов, "
        "в том же порядке, что и товары выше."
    )


def generate_ai_copy(products: list[Product]) -> Optional[dict]:
    """Пробует сгенерировать текст статьи через Groq.

    Возвращает {"title": str, "intro": str, "outro": str, "items": [item, ...]},
    где каждый item — {"short_name": str, "description": str, "pros": [str],
    "cons": [str]}, либо None, если AI недоступен/не настроен/ответ не
    распарсился.
    """
    if not products:
        return None

    if not config.GROQ_API_KEY:
        logger.info("[AI] GROQ_API_KEY не задан — используем шаблонный текст")
        return None

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": _build_prompt(products)}],
                "temperature": 0.8,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
    except Exception as e:
        logger.warning(f"[AI] Не удалось получить текст от Groq: {e}")
        return None

    items = parsed.get("items")
    if not isinstance(items, list) or len(items) != len(products):
        logger.warning(
            f"[AI] Groq вернул {len(items) if isinstance(items, list) else 'не список'} "
            f"описаний вместо {len(products)} — используем шаблонный текст"
        )
        return None

    # Раньше items были просто строками-описаниями; теперь это объекты с
    # short_name/description/pros/cons. Подстраховываемся на случай, если
    # модель всё же вернула что-то неполное или в старом формате.
    normalized = []
    for it in items:
        if isinstance(it, dict):
            normalized.append({
                "short_name": str(it.get("short_name") or "").strip(),
                "description": str(it.get("description") or it.get("text") or "").strip(),
                "pros": [
                    str(x).strip() for x in (it.get("pros") or []) if str(x).strip()
                ][:5],
                "cons": [
                    str(x).strip() for x in (it.get("cons") or []) if str(x).strip()
                ][:3],
            })
        elif isinstance(it, str):
            normalized.append({"short_name": "", "description": it, "pros": [], "cons": []})
        else:
            normalized.append({"short_name": "", "description": "", "pros": [], "cons": []})
    parsed["items"] = normalized

    return parsed


def _build_single_prompt(p: Product, topic: str = "") -> str:
    """Промпт для статьи об ОДНОМ товаре — без отзывов, оценок и списков
    плюсов/минусов.

    Это принципиально другой жанр, чем подборка: там читателю нужно сравнить
    несколько вариантов по цифрам, здесь — просто прочитать живой текст про
    вещь. Поэтому модели прямо запрещено упоминать цену, скидку, рейтинг и
    мнения покупателей: этих блоков в такой статье нет, и если текст начнёт
    на них ссылаться ("судя по отзывам..."), получится ложь.
    """
    lines = [f"Товар: {p.name}", f"Бренд: {p.brand or 'не указан'}"]
    if topic:
        lines.append(f"Читатель искал: {topic}")

    return (
        "Ты пишешь статью для Яндекс Дзена об одном конкретном товаре с "
        "Яндекс Маркета.\n\n"
        + "\n".join(lines)
        + "\n\n"
        "Правила:\n"
        "- Пиши живо, по-человечески, без канцелярита и без рекламных штампов "
        'вроде "успей купить" или "лучшая цена".\n'
        "- НЕ выдумывай технические характеристики, размеры, материалы, "
        "комплектацию и любые другие факты, которых нет выше: про сам товар "
        "известны только название и бренд. Всё остальное пиши как общие "
        "рассуждения о такой категории вещей, а не как утверждения об этой "
        "конкретной модели.\n"
        "- НЕ упоминай цену, скидку, рейтинг, количество отзывов и мнения "
        "покупателей — этих данных в статье не будет, ссылаться на них нельзя.\n"
        '- Не обращайся к читателю "дорогой читатель" и не заканчивай '
        'фразами в духе "подводя итог".\n\n'
        "Верни ТОЛЬКО валидный JSON, без markdown-разметки вокруг него и без "
        "пояснений, в формате:\n"
        '{"title": "цепляющий заголовок статьи, не более 90 символов", '
        '"paragraphs": ["абзац 1", "абзац 2", "абзац 3", "абзац 4", "..."]}\n\n'
        "В paragraphs — от 8 до 12 абзацев по 2-4 предложения: чем такая вещь "
        "бывает полезна, кому и в каких ситуациях подходит, на что смотреть "
        "при выборе, как ей пользоваться или с чем сочетать, на какие похожие "
        "варианты обратить внимание, как за такой вещью ухаживать/хранить, "
        "какие вопросы стоит задать себе перед покупкой. Суммарный объём всех "
        "абзацев вместе — не меньше 3000 символов (примерно 450-500 слов), "
        "лучше чуть больше, чем меньше. Не повторяй одну и ту же мысль "
        "разными словами ради объёма — лучше раскрой больше отдельных углов "
        "темы."
    )


def generate_single_product_copy(p: Product, topic: str = "") -> Optional[dict]:
    """Текст статьи-обзора об одном товаре.

    Возвращает {"title": str, "paragraphs": [str, ...]} либо None, если Groq
    не настроен/недоступен/ответил не тем — вызывающий код
    (content_generator.generate_single_product_article) тогда подставляет
    запасной шаблон, и публикация не срывается из-за недоступности AI.
    """
    if not p:
        return None

    if not config.GROQ_API_KEY:
        logger.info("[AI] GROQ_API_KEY не задан — используем шаблонный текст")
        return None

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "user", "content": _build_single_prompt(p, topic)}
                ],
                "temperature": 0.8,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
    except Exception as e:
        logger.warning(f"[AI] Не удалось получить текст от Groq: {e}")
        return None

    paragraphs = [
        str(x).strip() for x in (parsed.get("paragraphs") or []) if str(x).strip()
    ]
    if not paragraphs:
        logger.warning("[AI] Groq не вернул ни одного абзаца — используем шаблонный текст")
        return None

    return {
        "title": str(parsed.get("title") or "").strip(),
        "paragraphs": paragraphs[:14],
    }
