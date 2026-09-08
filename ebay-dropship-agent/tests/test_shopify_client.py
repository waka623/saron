"""`adapters/shopify/client.py::ShopifyClient`のテスト。実Shopifyへは接続しない

(`FakeShopifyTransport`でGraphQL呼び出しを差し替える)。
"""

from __future__ import annotations

import pytest

from ebay_dropship.adapters.shopify.client import ShopifyApiError, ShopifyClient
from tests.fakes.shopify_transport_fake import FakeShopifyTransport


def test_create_draft_product_sends_draft_status_and_returns_ids():
    def handler(query: str, variables: dict) -> dict:
        assert "productCreate" in query
        assert variables["input"]["status"] == "DRAFT"
        assert variables["input"]["title"] == "Acme Widget"
        assert variables["input"]["variants"] == [{"sku": "SKU-1", "price": "0.00"}]
        return {
            "data": {
                "productCreate": {
                    "product": {"id": "gid://shopify/Product/1", "variants": {"edges": [{"node": {"id": "gid://shopify/ProductVariant/1"}}]}},
                    "userErrors": [],
                }
            }
        }

    client = ShopifyClient(FakeShopifyTransport(handler))

    result = client.create_draft_product(
        title="Acme Widget", description_html="<p>desc</p>", sku="SKU-1", price="0.00"
    )

    assert result == {"product_id": "gid://shopify/Product/1", "variant_id": "gid://shopify/ProductVariant/1"}


def test_create_draft_product_raises_on_user_errors():
    def handler(query: str, variables: dict) -> dict:
        return {"data": {"productCreate": {"product": None, "userErrors": [{"field": ["title"], "message": "required"}]}}}

    client = ShopifyClient(FakeShopifyTransport(handler))

    with pytest.raises(ShopifyApiError, match="required"):
        client.create_draft_product(title="", description_html="", sku="SKU-1", price="0.00")


def test_raises_on_top_level_graphql_errors():
    def handler(query: str, variables: dict) -> dict:
        return {"errors": [{"message": "Field 'x' doesn't exist"}]}

    client = ShopifyClient(FakeShopifyTransport(handler))

    with pytest.raises(ShopifyApiError, match="doesn't exist"):
        client.create_draft_product(title="t", description_html="", sku="SKU-1", price="0.00")


def test_find_by_sku_returns_product_and_variant_ids():
    def handler(query: str, variables: dict) -> dict:
        assert variables["query"] == "sku:SKU-1"
        return {
            "data": {
                "productVariants": {
                    "edges": [{"node": {"id": "gid://shopify/ProductVariant/9", "product": {"id": "gid://shopify/Product/9"}}}]
                }
            }
        }

    client = ShopifyClient(FakeShopifyTransport(handler))

    result = client.find_by_sku("SKU-1")

    assert result == {"product_id": "gid://shopify/Product/9", "variant_id": "gid://shopify/ProductVariant/9"}


def test_find_by_sku_returns_none_when_not_found():
    def handler(query: str, variables: dict) -> dict:
        return {"data": {"productVariants": {"edges": []}}}

    client = ShopifyClient(FakeShopifyTransport(handler))

    assert client.find_by_sku("MISSING-SKU") is None


def test_get_default_variant_id_returns_first_variant():
    def handler(query: str, variables: dict) -> dict:
        assert variables["id"] == "gid://shopify/Product/9"
        return {"data": {"product": {"variants": {"edges": [{"node": {"id": "gid://shopify/ProductVariant/9"}}]}}}}

    client = ShopifyClient(FakeShopifyTransport(handler))

    assert client.get_default_variant_id("gid://shopify/Product/9") == "gid://shopify/ProductVariant/9"


def test_get_default_variant_id_raises_when_product_missing():
    def handler(query: str, variables: dict) -> dict:
        return {"data": {"product": None}}

    client = ShopifyClient(FakeShopifyTransport(handler))

    with pytest.raises(ShopifyApiError):
        client.get_default_variant_id("gid://shopify/Product/missing")


def test_set_variant_price_sends_bulk_update_mutation():
    def handler(query: str, variables: dict) -> dict:
        assert "productVariantsBulkUpdate" in query
        assert variables == {
            "productId": "gid://shopify/Product/9",
            "variants": [{"id": "gid://shopify/ProductVariant/9", "price": "19.99"}],
        }
        return {"data": {"productVariantsBulkUpdate": {"userErrors": []}}}

    client = ShopifyClient(FakeShopifyTransport(handler))

    client.set_variant_price("gid://shopify/Product/9", "gid://shopify/ProductVariant/9", "19.99")


def test_publish_product_sets_status_active():
    def handler(query: str, variables: dict) -> dict:
        assert variables["input"] == {"id": "gid://shopify/Product/9", "status": "ACTIVE"}
        return {"data": {"productUpdate": {"product": {"id": "gid://shopify/Product/9", "status": "ACTIVE"}, "userErrors": []}}}

    client = ShopifyClient(FakeShopifyTransport(handler))

    client.publish_product("gid://shopify/Product/9")


def test_get_orders_passes_since_as_created_at_filter():
    def handler(query: str, variables: dict) -> dict:
        assert variables["query"] == "created_at:>=2026-01-01"
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

    client = ShopifyClient(FakeShopifyTransport(handler))

    orders = client.get_orders(since="2026-01-01")

    assert orders == [
        {
            "id": "gid://shopify/Order/1",
            "name": "#1001",
            "displayFulfillmentStatus": "UNFULFILLED",
            "currentTotalPriceSet": {"shopMoney": {"amount": "29.99", "currencyCode": "USD"}},
        }
    ]


def test_get_orders_without_since_passes_no_query_filter():
    def handler(query: str, variables: dict) -> dict:
        assert variables["query"] is None
        return {"data": {"orders": {"edges": []}}}

    client = ShopifyClient(FakeShopifyTransport(handler))

    assert client.get_orders() == []
