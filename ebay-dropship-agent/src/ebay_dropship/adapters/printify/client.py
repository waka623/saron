"""Printify REST API クライアント(v1)。`pod/__init__.py::SupplierProvider`実装が使う。

要確認: このセッションから実Printifyへ接続して検証できないため、実装前に必ず
https://developers.printify.com/ で最新のエンドポイント・フィールド名を確認すること。
特に`line_items`が`variant_id`必須(SKU直接指定不可)なバージョンもあるため、SKUから
variant_idを引く追加の呼び出しが必要になる場合がある(本実装はSKUをそのまま`line_items`に
渡せる前提で書いている)。
"""

from __future__ import annotations

import httpx

from ebay_dropship.pod import SupplierProviderError

PRINTIFY_API_BASE = "https://api.printify.com/v1"


class PrintifyApiError(SupplierProviderError):
    pass


class PrintifyClient:
    def __init__(self, api_token: str, shop_id: str, http_client: httpx.Client | None = None):
        self._api_token = api_token
        self._shop_id = shop_id
        self._http = http_client or httpx.Client(timeout=10.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_token}", "Content-Type": "application/json"}

    def create_order(self, payload: dict) -> dict:
        response = self._http.post(
            f"{PRINTIFY_API_BASE}/shops/{self._shop_id}/orders.json",
            json=payload,
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise PrintifyApiError(f"Printify注文作成に失敗: {response.status_code} {response.text}")
        return response.json()

    def get_order(self, printify_order_id: str) -> dict:
        response = self._http.get(
            f"{PRINTIFY_API_BASE}/shops/{self._shop_id}/orders/{printify_order_id}.json",
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise PrintifyApiError(f"Printify注文取得に失敗: {response.status_code} {response.text}")
        return response.json()
