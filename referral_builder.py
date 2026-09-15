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


def add_erid_to_url(url: str, erid: str) -> str:
    """Добавляет параметр erid к уже готовой ссылке (например, CPA-ссылке
    с clid). По закону: один рекламный креатив (в нашем случае — один пост)
    получает один erid, который затем дублируется в КАЖДУЮ ссылку на
    рекламируемый ресурс внутри этого креатива — а не отдельный erid на
    каждую ссылку.
    """
    if not erid:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}erid={erid}"


def build_referral_url(product_url: str, marketplace: Marketplace = Marketplace.YANDEX_MARKET) -> str:
    """Главная функция: строит реферальную ссылку."""
    if marketplace == Marketplace.YANDEX_MARKET:
        return build_ym_cpa_link(product_url)
    return product_url


def get_post_footer(erid: str = None) -> str:
    """Футер поста с обязательной по закону маркировкой рекламы (erid).

    ВАЖНО: erid — это реальный уникальный идентификатор конкретного
    рекламного креатива, который выдаёт зарегистрированный ОРД (Оператор
    рекламных данных) после регистрации именно ЭТОГО поста. Его нельзя
    придумать самим и нельзя один раз получить и переиспользовать во всех
    постах подряд — по закону (ст. 18.1 ФЗ "О рекламе", штрафы по ст. 14.3
    КоАП РФ) erid должен быть свой у каждого креатива.

    Поэтому footer собирается только если erid реально передан явно на этот
    конкретный пост (через параметр или config.ORD_TOKEN как временную
    ручную подстановку) — никакой автоподстановки/заглушки здесь нет и не
    должно быть: лучше опубликовать без маркировки и заметить это, чем
    один раз где-то проставить фиктивный erid.

    У этого проекта уже есть партнёрский кабинет Яндекс Дистрибуции — там
    есть бесплатный раздел "Маркировка рекламы", который выдаёт настоящие
    erid именно для такой CPA-рекламы Яндекс Маркета, без регистрации в
    стороннем ОРД. Пока туда не подключились — footer просто пустой.
    """
    token = erid or config.ORD_TOKEN
    if not token:
        return ""

    # Формат обязательной надписи — как требует Яндекс Маркет для CPA-постов
    # через Дистрибуцию (см. их же справку по маркировке рекламы).
    return f"\nРеклама. ООО «Яндекс Маркет», ИНН 9704254424. erid: {token}"
