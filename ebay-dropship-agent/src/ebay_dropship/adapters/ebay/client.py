"""eBay Sell API クライアント。OAuth・レート制限・リトライを内包する。

Phase 1 のスコープ:OAuth・レート制限クライアント・読み取り系の疎通確認(get_rate_limits)。
Inventory/Fulfillment/Browse への書き込み・検索は Phase 3〜5 で実装する。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ebay_dropship.adapters.ebay.auth import EbayOAuthClient
from ebay_dropship.adapters.ebay.rate_limit import CallBudget, retry_with_backoff

SANDBOX_API_BASE = "https://api.sandbox.ebay.com"
PRODUCTION_API_BASE = "https://api.ebay.com"

RATE_LIMIT_PATH = "/developer/analytics/v1_beta/rate_limit/"


class EbayApiError(Exception):
    pass


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
    ):
        self.sandbox = sandbox
        self.base_url = SANDBOX_API_BASE if sandbox else PRODUCTION_API_BASE
        self._http = http_client or httpx.Client(timeout=10.0)
        self._auth = EbayOAuthClient(
            client_id, client_secret, refresh_token, sandbox=sandbox, http_client=self._http
        )
        # 5000 は Sell API の代表的な日次上限の目安。実際の値は get_rate_limits() で都度確認する。
        self.call_budget = call_budget or CallBudget(daily_limit=5000)

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

    def _get(self, path: str, params: dict | None = None) -> dict:
        self.call_budget.record_call()

        def do_request() -> httpx.Response:
            return self._http.get(
                f"{self.base_url}{path}", headers=self._authorized_headers(), params=params
            )

        response = retry_with_backoff(do_request)
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

    # --- Browse / Taxonomy (Phase 3) ---
    def search_competitive_listings(self, keywords: str, category_id: str | None = None) -> list[dict]:
        raise NotImplementedError("Phase 3 で実装")

    # --- Inventory (Phase 4) ---
    def create_or_update_inventory_item(self, sku: str, payload: dict) -> dict:
        raise NotImplementedError("Phase 4 で実装")

    def create_offer(self, sku: str, payload: dict) -> dict:
        raise NotImplementedError("Phase 4 で実装")

    def publish_offer(self, offer_id: str) -> dict:
        raise NotImplementedError("Phase 4 で実装")

    # --- Fulfillment (Phase 5) ---
    def get_orders(self, since: str | None = None) -> list[dict]:
        raise NotImplementedError("Phase 5 で実装")
