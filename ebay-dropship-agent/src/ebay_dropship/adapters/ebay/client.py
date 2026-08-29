"""eBay Sell API クライアント。OAuth・レート制限・リトライを内包する。

Phase 1: OAuth・レート制限クライアント・読み取り系の疎通確認(get_rate_limits)。
Phase 3: Browse(検索・読み取り専用)。
Phase 4: Inventory の書き込み(inventory_item/offer/publish/update_offer)。
Phase 5: Fulfillment(受注取得、読み取り専用)。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from ebay_dropship.adapters.ebay.auth import EbayOAuthClient
from ebay_dropship.adapters.ebay.rate_limit import CallBudget, retry_with_backoff

SANDBOX_API_BASE = "https://api.sandbox.ebay.com"
PRODUCTION_API_BASE = "https://api.ebay.com"

RATE_LIMIT_PATH = "/developer/analytics/v1_beta/rate_limit/"
BROWSE_SEARCH_PATH = "/buy/browse/v1/item_summary/search"
INVENTORY_ITEM_PATH = "/sell/inventory/v1/inventory_item"
OFFER_PATH = "/sell/inventory/v1/offer"
FULFILLMENT_ORDER_PATH = "/sell/fulfillment/v1/order"

# eBay Inventory API のエラーコード。offer が既にSKUに紐づいて存在する場合(重複防止・冪等性のため参照)。
DUPLICATE_OFFER_ERROR_ID = 25002


class EbayApiError(Exception):
    pass


class EbayOfferAlreadyExistsError(EbayApiError):
    """create_offer が「既にこのSKUのofferが存在する」を返したとき。冪等な再利用のため既存offer_idを保持する。"""

    def __init__(self, sku: str, existing_offer_id: str):
        self.sku = sku
        self.existing_offer_id = existing_offer_id
        super().__init__(f"SKU={sku} のオファーは既に存在します(offerId={existing_offer_id})")


def _extract_duplicate_offer_id(data: dict) -> str | None:
    for error in data.get("errors", []):
        if error.get("errorId") == DUPLICATE_OFFER_ERROR_ID:
            for param in error.get("parameters", []):
                if param.get("name") == "offerId":
                    return param.get("value")
    return None


@dataclass
class RateLimitStatus:
    api_name: str
    calls_remaining: int
    daily_limit: int


class EbayClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        sandbox: bool = True,
        http_client: httpx.Client | None = None,
        call_budget: CallBudget | None = None,
        retry_sleep: Callable[[float], None] = time.sleep,
    ):
        self.sandbox = sandbox
        self.base_url = SANDBOX_API_BASE if sandbox else PRODUCTION_API_BASE
        self._http = http_client or httpx.Client(timeout=10.0)
        self._auth = EbayOAuthClient(
            client_id, client_secret, refresh_token, sandbox=sandbox, http_client=self._http
        )
        # 5000 は Sell API の代表的な日次上限の目安。実際の値は get_rate_limits() で都度確認する。
        self.call_budget = call_budget or CallBudget(daily_limit=5000)
        self._retry_sleep = retry_sleep

    @classmethod
    def from_settings(cls, settings) -> EbayClient:
        """設定(.env)から構築する。実キーに差し替える際はコード変更不要で .env を編集するだけでよい。"""
        return cls(
            client_id=settings.ebay_client_id,
            client_secret=settings.ebay_client_secret,
            refresh_token=settings.ebay_refresh_token,
            sandbox=settings.ebay_env != "production",
        )

    @property
    def client_id(self) -> str:
        return self._auth.client_id

    def get_access_token(self) -> str:
        return self._auth.get_access_token()

    def _authorized_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    def _request(
        self, method: str, path: str, *, json: dict | None = None, params: dict | None = None
    ) -> httpx.Response:
        self.call_budget.record_call()

        def do_request() -> httpx.Response:
            return self._http.request(
                method,
                f"{self.base_url}{path}",
                headers=self._authorized_headers(),
                params=params,
                json=json,
            )

        return retry_with_backoff(do_request, sleep=self._retry_sleep)

    def _get(self, path: str, params: dict | None = None) -> dict:
        response = self._request("GET", path, params=params)
        if response.status_code >= 400:
            raise EbayApiError(f"{path} 呼び出しに失敗: {response.status_code} {response.text}")
        return response.json()

    def get_rate_limits(self) -> list[RateLimitStatus]:
        """Developer Analytics API の getRateLimits(読み取り専用)で残コール数を取得する。

        実キーが未設定の間は Sandbox でも 401 になる。実キー投入後、そのまま実疎通確認に使える。
        """
        data = self._get(RATE_LIMIT_PATH)
        statuses: list[RateLimitStatus] = []
        for api in data.get("rateLimits", []):
            api_name = api.get("apiName", "unknown")
            for resource in api.get("resources", []):
                for rate in resource.get("rates", []):
                    statuses.append(
                        RateLimitStatus(
                            api_name=api_name,
                            calls_remaining=rate.get("remaining", 0),
                            daily_limit=rate.get("limit", 0),
                        )
                    )
        return statuses

    # --- Browse (Phase 3) ---
    def search_competitive_listings(self, keywords: str, category_id: str | None = None) -> list[dict]:
        """Browse API の item_summary/search(読み取り専用)。相場・競合点数の算出に使う。"""
        params: dict = {"q": keywords}
        if category_id:
            params["category_ids"] = category_id
        data = self._get(BROWSE_SEARCH_PATH, params=params)
        return data.get("itemSummaries", [])

    # --- Taxonomy (今回未使用。必要になれば同様のパターンで追加) ---

    # --- Inventory (Phase 4) ---
    def create_or_update_inventory_item(self, sku: str, payload: dict) -> dict:
        """PUT は仕様上べき等(同じSKUへの再送は上書きになり重複を生まない)。"""
        response = self._request("PUT", f"{INVENTORY_ITEM_PATH}/{sku}", json=payload)
        if response.status_code >= 400:
            raise EbayApiError(
                f"inventory_item({sku}) 更新に失敗: {response.status_code} {response.text}"
            )
        return response.json() if response.content else {}

    def create_offer(self, sku: str, payload: dict) -> dict:
        """既にSKUのofferが存在する場合は EbayOfferAlreadyExistsError を送出する(呼び出し側で冪等に再利用する)。"""
        response = self._request("POST", OFFER_PATH, json={**payload, "sku": sku})
        if response.status_code == 400:
            data = response.json() if response.content else {}
            existing_offer_id = _extract_duplicate_offer_id(data)
            if existing_offer_id:
                raise EbayOfferAlreadyExistsError(sku=sku, existing_offer_id=existing_offer_id)
        if response.status_code >= 400:
            raise EbayApiError(f"offer({sku}) 作成に失敗: {response.status_code} {response.text}")
        return response.json()

    def publish_offer(self, offer_id: str) -> dict:
        response = self._request("POST", f"{OFFER_PATH}/{offer_id}/publish")
        if response.status_code >= 400:
            raise EbayApiError(f"publish_offer({offer_id}) に失敗: {response.status_code} {response.text}")
        return response.json()

    def update_offer(self, offer_id: str, payload: dict) -> dict:
        """PUT は仕様上べき等(同じ内容の再送は同じ結果になる)。price_change 実行に使う。"""
        response = self._request("PUT", f"{OFFER_PATH}/{offer_id}", json=payload)
        if response.status_code >= 400:
            raise EbayApiError(f"update_offer({offer_id}) に失敗: {response.status_code} {response.text}")
        return response.json() if response.content else {}

    # --- Fulfillment (Phase 5) ---
    def get_orders(self, since: str | None = None) -> list[dict]:
        """Fulfillment API の getOrders(読み取り専用)。orders/ingest_orders で不正行・重複を隔離する。"""
        params: dict = {}
        if since:
            params["filter"] = f"creationdate:[{since}..]"
        data = self._get(FULFILLMENT_ORDER_PATH, params=params)
        return data.get("orders", [])
