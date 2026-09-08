"""`adapters/printify/`(PrintifyClient/PrintifyProvider)のテスト。実Printifyへは接続しない

(`FakePrintifyBackend`でHTTPを差し替える)。
"""

from __future__ import annotations

import httpx
import pytest

from ebay_dropship.adapters.printify.client import PrintifyApiError, PrintifyClient
from ebay_dropship.adapters.printify.provider import PrintifyProvider
from ebay_dropship.pod import SupplierOrder, SupplierOrderItem
from tests.fakes.printify_fake import FakePrintifyBackend


def _client(backend: FakePrintifyBackend) -> PrintifyClient:
    return PrintifyClient("token", "shop-1", http_client=httpx.Client(transport=backend.transport()))


def _order(**overrides) -> SupplierOrder:
    defaults = {
        "order_id": "shopify-order-1",
        "ship_to_name": "Jane Doe",
        "ship_to_address1": "123 Main St",
        "ship_to_city": "Springfield",
        "ship_to_region": "IL",
        "ship_to_country": "US",
        "ship_to_zip": "62701",
        "ship_to_email": "jane@example.com",
    }
    defaults.update(overrides)
    return SupplierOrder(**defaults)


# --- PrintifyClient ---


def test_create_order_returns_response_json():
    backend = FakePrintifyBackend()
    client = _client(backend)

    result = client.create_order({"external_id": "x1", "line_items": [{"sku": "MUG-1", "quantity": 1}]})

    assert result["status"] == "pending"
    assert backend.created_orders == [{"external_id": "x1", "line_items": [{"sku": "MUG-1", "quantity": 1}]}]


def test_create_order_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="invalid line_items")

    client = PrintifyClient("token", "shop-1", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(PrintifyApiError, match="422"):
        client.create_order({})


def test_get_order_returns_order_data():
    backend = FakePrintifyBackend()
    client = _client(backend)
    created = client.create_order({"external_id": "x1", "line_items": []})

    result = client.get_order(created["id"])

    assert result["status"] == "pending"


def test_get_order_raises_when_not_found():
    backend = FakePrintifyBackend()
    client = _client(backend)

    with pytest.raises(PrintifyApiError, match="404"):
        client.get_order("does-not-exist")


# --- PrintifyProvider(SupplierProvider実装) ---


def test_submit_order_returns_supplier_order_id():
    backend = FakePrintifyBackend()
    provider = PrintifyProvider(_client(backend))

    supplier_order_id = provider.submit_order(_order(), SupplierOrderItem(sku="MUG-1", quantity=2))

    assert supplier_order_id == "1"
    assert backend.created_orders[0]["external_id"] == "shopify-order-1"
    assert backend.created_orders[0]["line_items"] == [{"sku": "MUG-1", "quantity": 2}]
    assert backend.created_orders[0]["address_to"]["city"] == "Springfield"


def test_get_fulfillment_returns_no_tracking_when_not_shipped():
    backend = FakePrintifyBackend()
    provider = PrintifyProvider(_client(backend))
    supplier_order_id = provider.submit_order(_order(), SupplierOrderItem(sku="MUG-1", quantity=1))

    fulfillment = provider.get_fulfillment(supplier_order_id)

    assert fulfillment.status == "pending"
    assert fulfillment.tracking_number is None


def test_get_fulfillment_returns_tracking_once_shipped():
    backend = FakePrintifyBackend()
    provider = PrintifyProvider(_client(backend))
    supplier_order_id = provider.submit_order(_order(), SupplierOrderItem(sku="MUG-1", quantity=1))
    backend.fulfillments[supplier_order_id] = {
        "status": "fulfilled",
        "shipments": [{"carrier": "USPS", "number": "9400111", "url": "https://tools.usps.com/9400111"}],
    }

    fulfillment = provider.get_fulfillment(supplier_order_id)

    assert fulfillment.status == "fulfilled"
    assert fulfillment.tracking_number == "9400111"
    assert fulfillment.tracking_url == "https://tools.usps.com/9400111"
    assert fulfillment.carrier == "USPS"
