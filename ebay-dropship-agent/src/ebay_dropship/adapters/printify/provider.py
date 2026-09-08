"""`pod/__init__.py::SupplierProvider`のPrintify実装。`PrintifyClient`への薄い委譲。

Printifyの実際のレスポンス形状(`status`/`shipments`)は要確認(client.pyのdocstring参照)。
本実装は`shipments`配列の先頭要素にtracking情報がある前提で書いている。
"""

from __future__ import annotations

from ebay_dropship.adapters.printify.client import PrintifyClient
from ebay_dropship.pod import FulfillmentInfo, SupplierOrder, SupplierOrderItem, SupplierProvider


class PrintifyProvider(SupplierProvider):
    def __init__(self, client: PrintifyClient):
        self._client = client

    def submit_order(self, order: SupplierOrder, item: SupplierOrderItem) -> str:
        payload = {
            "external_id": order.order_id,
            "line_items": [{"sku": item.sku, "quantity": item.quantity}],
            "send_shipping_notification": False,
            "address_to": {
                "first_name": order.ship_to_name,
                "email": order.ship_to_email,
                "country": order.ship_to_country,
                "region": order.ship_to_region,
                "address1": order.ship_to_address1,
                "city": order.ship_to_city,
                "zip": order.ship_to_zip,
            },
        }
        response = self._client.create_order(payload)
        return response["id"]

    def get_fulfillment(self, supplier_order_id: str) -> FulfillmentInfo:
        data = self._client.get_order(supplier_order_id)
        shipments = data.get("shipments") or []
        if not shipments:
            return FulfillmentInfo(
                status=data.get("status", "unknown"), tracking_number=None, tracking_url=None, carrier=None
            )
        shipment = shipments[0]
        return FulfillmentInfo(
            status=data.get("status", "unknown"),
            tracking_number=shipment.get("number"),
            tracking_url=shipment.get("url"),
            carrier=shipment.get("carrier"),
        )
