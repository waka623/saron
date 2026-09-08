"""販路(sales channel)の抽象化と選択。

`settings.channel`(`.env`の`CHANNEL`、既定`"ebay"`)でどの販路を使うか選ぶ。
既定は必ずeBay(誤爆防止)。Shopifyは明示的に`CHANNEL=shopify`を設定した場合のみ選ばれる。
"""

from __future__ import annotations

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.adapters.shopify import HttpShopifyTransport, ShopifyClient
from ebay_dropship.channels.base import SalesChannel
from ebay_dropship.channels.ebay import EbayChannel
from ebay_dropship.channels.shopify import ShopifyChannel
from ebay_dropship.config import Settings

__all__ = ["EbayChannel", "SalesChannel", "ShopifyChannel", "create_channel"]


def create_channel(settings: Settings) -> SalesChannel:
    if settings.channel == "shopify":
        transport = HttpShopifyTransport(
            store_domain=settings.shopify_store_domain,
            access_token=settings.shopify_access_token,
            api_version=settings.shopify_api_version,
        )
        return ShopifyChannel(ShopifyClient(transport))
    return EbayChannel(EbayClient.from_settings(settings))
