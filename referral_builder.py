"""Построение CPA-ссылок Яндекс Дистрибуции + маркировка ОРИ."""
from urllib.parse import urlencode, quote
from config import config
from models import Marketplace


def build_ym_cpa_link(product_url: str) -> str:
    """Строит CPA-ссылку Яндекс Дистрибуции для товара Яндекс Маркета."""
    partner_id = config.YANDEX_DISTRIBUTION_PARTNER_ID
    if not partner_id:
        return product_url

    # Яндекс Дистрибуция CPA-формат
    # https://market.yandex.ru/product/ID?clid=PARTNER_ID
    if "market.yandex" in product_url:
        sep = "&" if "?" in product_url else "?"
        return f"{product_url}{sep}clid={partner_id}"

    return product_url


def build_referral_url(product_url: str, marketplace: Marketplace = Marketplace.YANDEX_MARKET) -> str:
    """Главная функция: строит реферальную ссылку."""
    if marketplace == Marketplace.YANDEX_MARKET:
        return build_ym_cpa_link(product_url)
    return product_url


def get_ory_marking() -> str:
    """Возвращает строку маркировки ОРИ для рекламного поста."""
    token = config.ORD_TOKEN
    if not token:
        return ""

    # ОРИ маркировка в формате, требуемом законом
    # Формат: #реклама + токен ОРД
    return f"#реклама {token}"


def get_advertising_disclaimer() -> str:
    """Возвращает дисклеймер для рекламного поста."""
    parts = []

    if config.ORD_TOKEN:
        parts.append(f"#реклама {config.ORD_TOKEN}")

    parts.append("Реклама. ООО «Яндекс Маркет». erid: ...")

    return "\n".join(parts)


def get_post_footer() -> str:
    """Футер поста с маркировкой."""
    lines = []

    if config.ORD_TOKEN:
        lines.append(f"\n#реклама {config.ORD_TOKEN}")

    return "\n".join(lines)
