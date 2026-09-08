"""Shopify GraphQL通信のフェイク実装(実HTTPを使わない)。

`research/market_data.py::MockMarketDataProvider`と同じ流儀: テストはこのフェイクへ
差し込んだ`handler`でクエリごとの応答を制御し、実Shopifyストアへは一切接続しない。
"""

from __future__ import annotations

from collections.abc import Callable

from ebay_dropship.adapters.shopify.transport import ShopifyTransport


class FakeShopifyTransport(ShopifyTransport):
    def __init__(self, handler: Callable[[str, dict], dict]):
        self.calls: list[tuple[str, dict]] = []
        self._handler = handler

    def execute(self, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        self.calls.append((query, variables))
        return self._handler(query, variables)
