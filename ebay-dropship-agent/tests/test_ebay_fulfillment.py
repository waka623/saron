"""EbayClient.get_orders(読み取り専用)のモック疎通 + orders.ingest_orders との結合確認。"""

import httpx

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.orders import ingest_orders
from tests.fakes.ebay_fulfillment_fake import FakeFulfillmentBackend


def test_get_orders_mocked_sandbox_connectivity_and_ingest_isolates_duplicates_and_bad_rows():
    backend = FakeFulfillmentBackend()
    backend.orders_response = [
        {
            "order_id": "ORD-1",
            "sku": "X1",
            "quantity": 1,
            "customer_paid": "29.99",
            "ship_to_country": "US",
            "due_date": "2026-09-05T00:00:00+00:00",
            "assumed_supplier_cost": "12.00",
        },
        # 重複受注(ページネーション境界などで同じ注文が2回返る想定)
        {
            "order_id": "ORD-1",
            "sku": "X1",
            "quantity": 1,
            "customer_paid": "29.99",
            "ship_to_country": "US",
            "due_date": "2026-09-05T00:00:00+00:00",
            "assumed_supplier_cost": "12.00",
        },
        # 部分成功: このレコードだけ不正(必須フィールド欠落)
        {"order_id": "ORD-2", "sku": "X2"},
    ]
    http_client = httpx.Client(transport=backend.transport())
    client = EbayClient("id", "secret", "refresh", http_client=http_client)

    raw_orders = client.get_orders()
    result = ingest_orders(raw_orders)

    assert len(raw_orders) == 3
    assert [o.order_id for o in result.orders] == ["ORD-1"]
    assert result.duplicate_order_ids == ["ORD-1"]
    assert len(result.errors) == 1
