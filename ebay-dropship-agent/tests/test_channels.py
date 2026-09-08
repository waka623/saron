"""S0で導入したSalesChannel抽象(channels/)のテスト。

eBayの挙動そのものは既存の test_orchestrator_do*.py 系で担保済み(そちらは変更後も全green)。
ここでは (a) CHANNEL設定に応じて正しい実装が選ばれること、(b) EbayChannelがEbayClientへの
薄い委譲であること、(c) ShopifyChannelが未実装スタブとして安全に失敗すること、を検証する。
実eBay/Shopifyへの接続は行わない。
"""

from __future__ import annotations

import httpx
import pytest

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.channels import EbayChannel, ShopifyChannel, create_channel
from ebay_dropship.channels.base import SalesChannel
from ebay_dropship.config import Settings


def _client() -> EbayClient:
    return EbayClient("id", "secret", "refresh", http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))


# --- CHANNEL既定でEbayChannelが選ばれること ---


def test_create_channel_defaults_to_ebay():
    settings = Settings()

    channel = create_channel(settings)

    assert isinstance(channel, EbayChannel)
    assert settings.channel == "ebay"


def test_create_channel_selects_ebay_explicitly():
    settings = Settings(channel="ebay")

    assert isinstance(create_channel(settings), EbayChannel)


def test_create_channel_selects_shopify_stub_when_configured():
    settings = Settings(channel="shopify")

    assert isinstance(create_channel(settings), ShopifyChannel)


# --- EbayChannel: EbayClientへの薄い委譲であることの確認 ---


def test_ebay_channel_delegates_get_orders_to_client():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        return httpx.Response(200, json={"orders": [{"orderId": "O1"}]})

    client = EbayClient("id", "secret", "refresh", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    channel = EbayChannel(client)

    orders = channel.get_orders(since="2026-01-01T00:00:00Z")

    assert orders == [{"orderId": "O1"}]


def test_ebay_channel_is_a_sales_channel():
    assert isinstance(EbayChannel(_client()), SalesChannel)


# --- ShopifyChannel: S0では未実装スタブ ---


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.create_or_update_inventory_item("sku", {}),
        lambda c: c.create_offer("sku", {}),
        lambda c: c.publish_offer("offer-1"),
        lambda c: c.update_offer("offer-1", {}),
        lambda c: c.get_item_aspects_for_category("9355"),
        lambda c: c.get_orders(),
    ],
)
def test_shopify_channel_methods_raise_not_implemented(call):
    channel = ShopifyChannel()

    with pytest.raises(NotImplementedError):
        call(channel)


def test_shopify_channel_is_a_sales_channel():
    assert isinstance(ShopifyChannel(), SalesChannel)


# --- SalesChannel自体は抽象クラスでインスタンス化できないこと ---


def test_sales_channel_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        SalesChannel()  # type: ignore[abstract]
