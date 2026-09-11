"""Построение реферальных ссылок для разных партнёрских программ."""
import re
from urllib.parse import quote, urlencode
from config import config
from models import Marketplace


def build_referral_url(product_url: str, marketplace: Marketplace) -> str:
    """Строит реферальную ссылку на основе доступных партнёрских программ."""
    if not product_url:
        return product_url

    # 1. AliExpress Portals (прямая партнёрка)
    if marketplace == Marketplace.ALIEXPRESS and config.ALIEXPRESS_AFFILIATE_ID:
        return _aliexpress_portals(product_url)

    # 2. GdeSlon (CPA-сеть) — для WB, Ozon, YM
    if config.GDESLON_AFFILIATE_ID:
        campaign = _get_gdeslon_campaign(marketplace)
        if campaign:
            return _gdeslon_link(product_url, campaign)

    # 3. Fallback — прямая ссылка без реферала
    return product_url


def _aliexpress_portals(url: str) -> str:
    """AliExpress Portals — добавляем tracking параметры."""
    aff_id = config.ALIEXPRESS_AFFILIATE_ID
    if not aff_id:
        return url

    # AliExpress Portals формат: добавляем aff_fcid и aff_fsk
    sep = "&" if "?" in url else "?"
    params = {
        "aff_fcid": aff_id,
        "aff_platform": "promotions",
        "terminal_id": "telegram",
    }
    return f"{url}{sep}{urlencode(params)}"


def _get_gdeslon_campaign(marketplace: Marketplace) -> str:
    """Получаем campaign_id для конкретного маркетплейса из GdeSlon."""
    campaigns = {
        Marketplace.WB: config.GDESLON_WB_CAMPAIGN_ID,
        Marketplace.OZON: config.GDESLON_OZON_CAMPAIGN_ID,
        Marketplace.YANDEX_MARKET: config.GDESLON_YM_CAMPAIGN_ID,
        Marketplace.ALIEXPRESS: config.GDESLON_WB_CAMPAIGN_ID,  # fallback
    }
    return campaigns.get(marketplace, "")


def _gdeslon_link(url: str, campaign_id: str) -> str:
    """GdeSlon — формируем ссылку через CPA-сеть."""
    aff_id = config.GDESLON_AFFILIATE_ID
    if not aff_id or not campaign_id:
        return url

    # GdeSlon формат: https://gdeslon.ru/click/ID?campaign=ID&url=ENCODED_URL
    encoded_url = quote(url, safe="")
    return f"https://gdeslon.ru/click/{aff_id}?campaign={campaign_id}&url={encoded_url}"


def get_affiliate_info() -> dict:
    """Возвращает информацию о настроенных партнёрках."""
    info = {}

    if config.ALIEXPRESS_AFFILIATE_ID:
        info["AliExpress Portals"] = {
            "status": "active",
            "affiliate_id": config.ALIEXPRESS_AFFILIATE_ID[:8] + "...",
        }

    if config.GDESLON_AFFILIATE_ID:
        campaigns = {}
        if config.GDESLON_WB_CAMPAIGN_ID:
            campaigns["Wildberries"] = config.GDESLON_WB_CAMPAIGN_ID
        if config.GDESLON_OZON_CAMPAIGN_ID:
            campaigns["Ozon"] = config.GDESLON_OZON_CAMPAIGN_ID
        if config.GDESLON_YM_CAMPAIGN_ID:
            campaigns["Yandex Market"] = config.GDESLON_YM_CAMPAIGN_ID

        info["GdeSlon"] = {
            "status": "active",
            "affiliate_id": config.GDESLON_AFFILIATE_ID[:8] + "...",
            "campaigns": campaigns,
        }

    if not info:
        info["none"] = {"status": "no affiliate programs configured"}

    return info
