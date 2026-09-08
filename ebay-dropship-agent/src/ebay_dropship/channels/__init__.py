"""販路(sales channel)の抽象化と選択(S0)。

`settings.channel`(`.env`の`CHANNEL`、既定`"ebay"`)でどの販路を使うか選ぶ。
S0では`"ebay"`のみが動作する(`"shopify"`は未実装スタブを返す。DECISIONS.md参照)。
"""

from __future__ import annotations

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.channels.base import SalesChannel
from ebay_dropship.channels.ebay import EbayChannel
from ebay_dropship.channels.shopify import ShopifyChannel
from ebay_dropship.config import Settings

__all__ = ["EbayChannel", "SalesChannel", "ShopifyChannel", "create_channel"]


def create_channel(settings: Settings) -> SalesChannel:
    if settings.channel == "shopify":
        return ShopifyChannel()
    return EbayChannel(EbayClient.from_settings(settings))
