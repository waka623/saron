"""Fulfillment API(getOrders)の擬似バックエンド。正常系だけでなく、重複受注や不正データを含む

レスポンスを返せるようにし、orders.ingest_orders 側の隔離ロジックを実データに近い形で検証する。
"""

from __future__ import annotations

import httpx


class FakeFulfillmentBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.orders_response: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        if path == "/sell/fulfillment/v1/order":
            return httpx.Response(200, json={"orders": self.orders_response})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
