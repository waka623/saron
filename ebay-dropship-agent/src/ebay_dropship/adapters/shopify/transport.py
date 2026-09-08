"""Shopify Admin API(GraphQL)への実際のHTTP通信を抽象化する。

`research/market_data.py::MarketDataProvider`と同じ流儀: `ShopifyClient`はこのインターフェース
だけに依存し、テストは実HTTPを一切使わないフェイク実装(`tests/fakes/shopify_transport_fake.py`)で
検証する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx


class ShopifyTransportError(Exception):
    pass


class ShopifyTransport(ABC):
    @abstractmethod
    def execute(self, query: str, variables: dict | None = None) -> dict:
        """GraphQL Admin APIへ1回POSTし、レスポンスJSON全体(`data`/`errors`を含む)を返す。"""
        ...


class HttpShopifyTransport(ShopifyTransport):
    """実際にShopify Admin API(GraphQL)へPOSTする実装。

    要確認: `api_version`はここでは仮定の既定値を置いていない(設定必須)。
    https://shopify.dev/docs/api/usage/versioning で現在のstableバージョンを確認し、
    `.env`の`SHOPIFY_API_VERSION`に設定すること。
    """

    def __init__(
        self,
        store_domain: str,
        access_token: str,
        api_version: str,
        http_client: httpx.Client | None = None,
    ):
        if not store_domain or not access_token or not api_version:
            raise ShopifyTransportError(
                "SHOPIFY_STORE_DOMAIN / SHOPIFY_ACCESS_TOKEN / SHOPIFY_API_VERSION を"
                ".envに設定してください(APIバージョンは仮定せず明示設定を必須にしている。"
                "https://shopify.dev/docs/api/usage/versioning で現在のstableバージョンを確認)。"
            )
        self._url = f"https://{store_domain}/admin/api/{api_version}/graphql.json"
        self._access_token = access_token
        self._http = http_client or httpx.Client(timeout=10.0)

    def execute(self, query: str, variables: dict | None = None) -> dict:
        response = self._http.post(
            self._url,
            json={"query": query, "variables": variables or {}},
            headers={
                "X-Shopify-Access-Token": self._access_token,
                "Content-Type": "application/json",
            },
        )
        if response.status_code >= 400:
            raise ShopifyTransportError(
                f"Shopify GraphQL呼び出しに失敗: {response.status_code} {response.text}"
            )
        return response.json()
