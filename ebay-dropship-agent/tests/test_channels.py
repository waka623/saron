"""SalesChannel抽象(channels/)のテスト。S0: EbayChannel/選択ロジック。S1: ShopifyChannelの実装。

eBayの挙動そのものは既存の test_orchestrator_do*.py 系で担保済み(そちらは変更後も全green)。
ここでは (a) CHANNEL設定に応じて正しい実装が選ばれること、(b) EbayChannelがEbayClientへの
薄い委譲であること、(c) ShopifyChannelの各メソッドがShopifyClient経由で正しく動くこと、を検証する。
実eBay/Shopifyへの接続は行わない。
"""

from __future__ import annotations

import httpx
import pytest

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.adapters.shopify.client import ShopifyApiError, ShopifyClient
from ebay_dropship.adapters.shopify.transport import ShopifyTransportError
from ebay_dropship.channels import EbayChannel, ShopifyChannel, create_channel
from ebay_dropship.channels.base import SalesChannel
from ebay_dropship.config import Settings
from tests.fakes.shopify_transport_fake import FakeShopifyTransport


def _client() -> EbayClient:
    return EbayClient("id", "secret", "refresh", http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))


def _shopify_settings(**overrides) -> Settings:
    defaults = {
        "channel": "shopify",
        "shopify_store_domain": "test-store.myshopify.com",
        "shopify_access_token": "shpat_fake",
        "shopify_api_version": "2024-10",
    }
    defaults.update(overrides)
    return Settings(**defaults)


# --- CHANNEL既定でEbayChannelが選ばれること ---


def test_create_channel_defaults_to_ebay():
    settings = Settings()

    channel = create_channel(settings)

    assert isinstance(channel, EbayChannel)
    assert settings.channel == "ebay"


def test_create_channel_selects_ebay_explicitly():
    settings = Settings(channel="ebay")

    assert isinstance(create_channel(settings), EbayChannel)


def test_create_channel_selects_shopify_when_configured():
    assert isinstance(create_channel(_shopify_settings()), ShopifyChannel)


def test_create_channel_fails_fast_when_shopify_selected_without_credentials():
    """CHANNEL=shopifyなのに認証情報が無い場合、実際にAPIを叩く前に構築時点で気づけるようにする

    (deny by default。曖昧な状態のまま後工程へ進ませない)。
    """
    with pytest.raises(ShopifyTransportError):
        create_channel(Settings(channel="shopify"))


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


# --- ShopifyChannel(S1): SalesChannelの各メソッドの実装 ---


def _shopify_channel(handler) -> ShopifyChannel:
    return ShopifyChannel(ShopifyClient(FakeShopifyTransport(handler)))


def test_shopify_channel_is_a_sales_channel():
    assert isinstance(_shopify_channel(lambda q, v: {"data": {}}), SalesChannel)


def test_create_or_update_inventory_item_creates_draft_product_from_ebay_shaped_payload():
    """payloadはdo.py側で常にeBay Inventory API形状(product.title/description)のまま渡ってくる。"""

    def handler(query: str, variables: dict) -> dict:
        assert variables["input"]["status"] == "DRAFT"
        assert variables["input"]["title"] == "Acme Widget"
        assert variables["input"]["variants"] == [{"sku": "SKU-1", "price": "0.00"}]
        return {
            "data": {
                "productCreate": {
                    "product": {
                        "id": "gid://shopify/Product/1",
                        "variants": {"edges": [{"node": {"id": "gid://shopify/ProductVariant/1"}}]},
                    },
                    "userErrors": [],
                }
            }
        }

    channel = _shopify_channel(handler)
    ebay_shaped_payload = {"product": {"title": "Acme Widget", "description": "desc"}}

    result = channel.create_or_update_inventory_item("SKU-1", ebay_shaped_payload)

    assert result == {"product_id": "gid://shopify/Product/1", "variant_id": "gid://shopify/ProductVariant/1"}


def test_create_offer_finds_product_by_sku_and_sets_price():
    calls = []

    def handler(query: str, variables: dict) -> dict:
        calls.append(query)
        if "findVariantBySku" in query:
            assert variables["query"] == "sku:SKU-1"
            return {
                "data": {
                    "productVariants": {
                        "edges": [
                            {"node": {"id": "gid://shopify/ProductVariant/9", "product": {"id": "gid://shopify/Product/9"}}}
                        ]
                    }
                }
            }
        assert "productVariantsBulkUpdate" in query
        assert variables == {
            "productId": "gid://shopify/Product/9",
            "variants": [{"id": "gid://shopify/ProductVariant/9", "price": "19.99"}],
        }
        return {"data": {"productVariantsBulkUpdate": {"userErrors": []}}}

    channel = _shopify_channel(handler)

    result = channel.create_offer("SKU-1", {"pricingSummary": {"price": {"value": "19.99"}}})

    assert result == {"offerId": "gid://shopify/Product/9"}


def test_create_offer_raises_when_sku_not_found():
    def handler(query: str, variables: dict) -> dict:
        return {"data": {"productVariants": {"edges": []}}}

    channel = _shopify_channel(handler)

    with pytest.raises(ShopifyApiError, match="SKU-MISSING"):
        channel.create_offer("SKU-MISSING", {"pricingSummary": {"price": {"value": "9.99"}}})


def test_publish_offer_activates_product_and_returns_listing_id():
    def handler(query: str, variables: dict) -> dict:
        assert variables["input"] == {"id": "gid://shopify/Product/9", "status": "ACTIVE"}
        return {"data": {"productUpdate": {"product": {"id": "gid://shopify/Product/9", "status": "ACTIVE"}, "userErrors": []}}}

    channel = _shopify_channel(handler)

    result = channel.publish_offer("gid://shopify/Product/9")

    assert result == {"listingId": "gid://shopify/Product/9"}


def test_update_offer_looks_up_default_variant_then_sets_price():
    def handler(query: str, variables: dict) -> dict:
        if "getDefaultVariant" in query:
            return {"data": {"product": {"variants": {"edges": [{"node": {"id": "gid://shopify/ProductVariant/9"}}]}}}}
        assert "productVariantsBulkUpdate" in query
        assert variables["variants"] == [{"id": "gid://shopify/ProductVariant/9", "price": "24.99"}]
        return {"data": {"productVariantsBulkUpdate": {"userErrors": []}}}

    channel = _shopify_channel(handler)

    channel.update_offer("gid://shopify/Product/9", {"pricingSummary": {"price": {"value": "24.99"}}})


def test_get_item_aspects_for_category_always_returns_empty_list():
    """Shopifyにこの概念(eBay Taxonomy固有)は無いため、常に空を返す(補完対象なし)。"""
    channel = _shopify_channel(lambda q, v: {"data": {}})

    assert channel.get_item_aspects_for_category("9355") == []


def test_get_orders_maps_shopify_shape_to_ebay_shaped_dicts():
    def handler(query: str, variables: dict) -> dict:
        return {
            "data": {
                "orders": {
                    "edges": [
                        {
                            "node": {
                                "id": "gid://shopify/Order/1",
                                "name": "#1001",
                                "displayFulfillmentStatus": "UNFULFILLED",
                                "currentTotalPriceSet": {"shopMoney": {"amount": "29.99", "currencyCode": "USD"}},
                            }
                        }
                    ]
                }
            }
        }

    channel = _shopify_channel(handler)

    orders = channel.get_orders()

    assert orders == [
        {
            "orderId": "#1001",
            "orderFulfillmentStatus": "UNFULFILLED",
            "pricingSummary": {"total": {"value": "29.99", "currency": "USD"}},
        }
    ]


# --- SalesChannel自体は抽象クラスでインスタンス化できないこと ---


def test_sales_channel_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        SalesChannel()  # type: ignore[abstract]
