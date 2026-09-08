"""Printify REST APIのフェイク(実HTTPを使わない)。`tests/fakes/ebay_inventory_fake.py`と同じ流儀。"""

from __future__ import annotations

import json

import httpx


class FakePrintifyBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.created_orders: list[dict] = []
        self._next_id = 1
        # order_id -> {"status": ..., "shipments": [...]}
        self.fulfillments: dict[str, dict] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))

        if path.endswith("/orders.json") and request.method == "POST":
            body = json.loads(request.content)
            self.created_orders.append(body)
            order_id = str(self._next_id)
            self._next_id += 1
            self.fulfillments[order_id] = {"status": "pending", "shipments": []}
            return httpx.Response(200, json={"id": order_id, "status": "pending"})

        if "/orders/" in path and path.endswith(".json") and request.method == "GET":
            order_id = path.rsplit("/", 1)[-1].removesuffix(".json")
            data = self.fulfillments.get(order_id)
            if data is None:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json={"id": order_id, **data})

        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
