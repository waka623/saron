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

from ebay_dropship.adapters.ebay.auth import EbayApplicationOAuthClient, EbayOAuthClient
from ebay_dropship.adapters.ebay.rate_limit import CallBudget, retry_with_backoff

SANDBOX_API_BASE = "https://api.sandbox.ebay.com"
PRODUCTION_API_BASE = "https://api.ebay.com"

RATE_LIMIT_PATH = "/developer/analytics/v1_beta/rate_limit/"
BROWSE_SEARCH_PATH = "/buy/browse/v1/item_summary/search"
INVENTORY_ITEM_PATH = "/sell/inventory/v1/inventory_item"
OFFER_PATH = "/sell/inventory/v1/offer"
FULFILLMENT_ORDER_PATH = "/sell/fulfillment/v1/order"
ACCOUNT_OPT_IN_PATH = "/sell/account/v1/program/opt_in"
PAYMENT_POLICY_PATH = "/sell/account/v1/payment_policy"
RETURN_POLICY_PATH = "/sell/account/v1/return_policy"
FULFILLMENT_POLICY_PATH = "/sell/account/v1/fulfillment_policy"
INVENTORY_LOCATION_PATH = "/sell/inventory/v1/location"
TAXONOMY_DEFAULT_TREE_PATH = "/commerce/taxonomy/v1/get_default_category_tree_id"
TAXONOMY_ASPECTS_PATH = "/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category"

# eBay Inventory API のエラーコード。offer が既にSKUに紐づいて存在する場合(重複防止・冪等性のため参照)。
DUPLICATE_OFFER_ERROR_ID = 25002
# eBay公式ドキュメントに基づく想定値(Account API opt_in が「既にオプトイン済み」を返すとき)。
# 実Sandboxでの実際の値がこれと異なる場合は、Task 3の実疎通で確認して修正する(DECISIONS.md参照)。
ALREADY_OPTED_IN_ERROR_ID = 20404


def _has_error_id(data: dict, error_id: int) -> bool:
    return any(error.get("errorId") == error_id for error in data.get("errors", []))


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
        marketplace_id: str = "EBAY_US",
        content_language: str = "en-US",
    ):
        self.sandbox = sandbox
        self.base_url = SANDBOX_API_BASE if sandbox else PRODUCTION_API_BASE
        self._http = http_client or httpx.Client(timeout=10.0)
        self._auth = EbayOAuthClient(
            client_id, client_secret, refresh_token, sandbox=sandbox, http_client=self._http
        )
        # Browse等、特定の出品者データを扱わない読み取り専用API用のアプリケーショントークン
        # (ユーザーの同意=refresh_token不要)。Sell API群は引き続き上のユーザートークンを使う。
        self._app_auth = EbayApplicationOAuthClient(
            client_id, client_secret, sandbox=sandbox, http_client=self._http
        )
        # 5000 は Sell API の代表的な日次上限の目安。実際の値は get_rate_limits() で都度確認する。
        self.call_budget = call_budget or CallBudget(daily_limit=5000)
        self._retry_sleep = retry_sleep
        # errorId 25709("Invalid value for header Content-Language")等の回避。
        # Inventory/Offer系の書き込み呼び出しとBrowse APIが要求するヘッダーの値。ハードコードせず
        # .env(config.Settings)から渡す(marketplace変更時にコード変更不要にするため)。
        self.marketplace_id = marketplace_id
        self.content_language = content_language

    @classmethod
    def from_settings(cls, settings) -> EbayClient:
        """設定(.env)から構築する。実キーに差し替える際はコード変更不要で .env を編集するだけでよい。"""
        return cls(
            client_id=settings.ebay_client_id,
            client_secret=settings.ebay_client_secret,
            refresh_token=settings.ebay_refresh_token,
            sandbox=settings.ebay_env != "production",
            marketplace_id=settings.ebay_marketplace_id,
            content_language=settings.ebay_content_language,
        )

    @property
    def client_id(self) -> str:
        return self._auth.client_id

    def get_access_token(self) -> str:
        return self._auth.get_access_token()

    def _authorized_headers(self, *, use_app_token: bool = False) -> dict:
        token = self._app_auth.get_access_token() if use_app_token else self.get_access_token()
        return {"Authorization": f"Bearer {token}"}

    def _content_language_headers(self) -> dict:
        """Inventory/Offer系の書き込み呼び出しに必須(未指定だとerrorId 25709)。"""
        return {"Content-Language": self.content_language}

    def _marketplace_headers(self) -> dict:
        """Browse API等、X-EBAY-C-MARKETPLACE-IDヘッダーを要求する呼び出し用。"""
        return {"X-EBAY-C-MARKETPLACE-ID": self.marketplace_id}

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        use_app_token: bool = False,
        extra_headers: dict | None = None,
    ) -> httpx.Response:
        self.call_budget.record_call()

        def do_request() -> httpx.Response:
            headers = self._authorized_headers(use_app_token=use_app_token)
            if extra_headers:
                headers.update(extra_headers)
            return self._http.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                params=params,
                json=json,
            )

        return retry_with_backoff(do_request, sleep=self._retry_sleep)

    def _get(
        self,
        path: str,
        params: dict | None = None,
        *,
        use_app_token: bool = False,
        extra_headers: dict | None = None,
    ) -> dict:
        response = self._request(
            "GET", path, params=params, use_app_token=use_app_token, extra_headers=extra_headers
        )
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
        """Browse API の item_summary/search(読み取り専用)。相場・競合点数の算出に使う。

        特定の出品者データを扱わないため、ユーザーの同意が要らないアプリケーショントークンを使う
        (Sell API群のユーザートークンとは別。auth.py参照)。
        """
        params: dict = {"q": keywords}
        if category_id:
            params["category_ids"] = category_id
        data = self._get(
            BROWSE_SEARCH_PATH, params=params, use_app_token=True, extra_headers=self._marketplace_headers()
        )
        return data.get("itemSummaries", [])

    # --- Taxonomy (今回未使用。必要になれば同様のパターンで追加) ---

    # --- Inventory (Phase 4) ---
    def create_or_update_inventory_item(self, sku: str, payload: dict) -> dict:
        """PUT は仕様上べき等(同じSKUへの再送は上書きになり重複を生まない)。

        Content-Language ヘッダーが必須(未指定だと errorId 25709 "Invalid value for header
        Content-Language" になる。実Sandbox疎通で確認済み)。
        """
        response = self._request(
            "PUT", f"{INVENTORY_ITEM_PATH}/{sku}", json=payload, extra_headers=self._content_language_headers()
        )
        if response.status_code >= 400:
            raise EbayApiError(
                f"inventory_item({sku}) 更新に失敗: {response.status_code} {response.text}"
            )
        return response.json() if response.content else {}

    def create_offer(self, sku: str, payload: dict) -> dict:
        """既にSKUのofferが存在する場合は EbayOfferAlreadyExistsError を送出する(呼び出し側で冪等に再利用する)。"""
        response = self._request(
            "POST", OFFER_PATH, json={**payload, "sku": sku}, extra_headers=self._content_language_headers()
        )
        if response.status_code == 400:
            data = response.json() if response.content else {}
            existing_offer_id = _extract_duplicate_offer_id(data)
            if existing_offer_id:
                raise EbayOfferAlreadyExistsError(sku=sku, existing_offer_id=existing_offer_id)
        if response.status_code >= 400:
            raise EbayApiError(f"offer({sku}) 作成に失敗: {response.status_code} {response.text}")
        return response.json()

    def publish_offer(self, offer_id: str) -> dict:
        response = self._request(
            "POST", f"{OFFER_PATH}/{offer_id}/publish", extra_headers=self._content_language_headers()
        )
        if response.status_code >= 400:
            raise EbayApiError(f"publish_offer({offer_id}) に失敗: {response.status_code} {response.text}")
        return response.json()

    def update_offer(self, offer_id: str, payload: dict) -> dict:
        """PUT は仕様上べき等(同じ内容の再送は同じ結果になる)。price_change 実行に使う。"""
        response = self._request(
            "PUT", f"{OFFER_PATH}/{offer_id}", json=payload, extra_headers=self._content_language_headers()
        )
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

    # --- Account (`sandbox setup-selling` 専用。承認ゲートを経由するproposal実行とは別系統の
    # アカウント設定操作であり、guardrails.gateway を通さない。個別のproposalに紐づく副作用ではない
    # ため。呼び出しは cli/__init__.py の sandbox setup-selling コマンドのみ) ---
    def opt_in_selling_policy_management(self) -> bool:
        """Account API opt_in(SELLING_POLICY_MANAGEMENT)。既にオプトイン済みなら False を返す(冪等)。"""
        response = self._request(
            "POST", ACCOUNT_OPT_IN_PATH, json={"programType": "SELLING_POLICY_MANAGEMENT"}
        )
        if response.status_code < 400:
            return True
        data = response.json() if response.content else {}
        if _has_error_id(data, ALREADY_OPTED_IN_ERROR_ID):
            return False
        raise EbayApiError(f"opt_in(SELLING_POLICY_MANAGEMENT)に失敗: {response.status_code} {response.text}")

    def list_payment_policies(self, marketplace_id: str) -> list[dict]:
        data = self._get(PAYMENT_POLICY_PATH, params={"marketplace_id": marketplace_id})
        return data.get("paymentPolicies", [])

    def create_payment_policy(self, payload: dict) -> dict:
        response = self._request("POST", PAYMENT_POLICY_PATH, json=payload)
        if response.status_code >= 400:
            raise EbayApiError(f"payment_policy作成に失敗: {response.status_code} {response.text}")
        return response.json()

    def list_return_policies(self, marketplace_id: str) -> list[dict]:
        data = self._get(RETURN_POLICY_PATH, params={"marketplace_id": marketplace_id})
        return data.get("returnPolicies", [])

    def create_return_policy(self, payload: dict) -> dict:
        response = self._request("POST", RETURN_POLICY_PATH, json=payload)
        if response.status_code >= 400:
            raise EbayApiError(f"return_policy作成に失敗: {response.status_code} {response.text}")
        return response.json()

    def list_fulfillment_policies(self, marketplace_id: str) -> list[dict]:
        data = self._get(FULFILLMENT_POLICY_PATH, params={"marketplace_id": marketplace_id})
        return data.get("fulfillmentPolicies", [])

    def create_fulfillment_policy(self, payload: dict) -> dict:
        response = self._request("POST", FULFILLMENT_POLICY_PATH, json=payload)
        if response.status_code >= 400:
            raise EbayApiError(f"fulfillment_policy作成に失敗: {response.status_code} {response.text}")
        return response.json()

    # --- Inventory location (`sandbox setup-selling` 専用) ---
    def get_merchant_location(self, merchant_location_key: str) -> dict | None:
        """存在しない場合は None を返す(呼び出し側が「無ければ作成」を判断できるように例外にしない)。"""
        response = self._request("GET", f"{INVENTORY_LOCATION_PATH}/{merchant_location_key}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise EbayApiError(f"merchant_location取得に失敗: {response.status_code} {response.text}")
        return response.json()

    def create_merchant_location(self, merchant_location_key: str, payload: dict) -> None:
        response = self._request(
            "POST",
            f"{INVENTORY_LOCATION_PATH}/{merchant_location_key}",
            json=payload,
            extra_headers=self._content_language_headers(),
        )
        if response.status_code >= 400:
            raise EbayApiError(f"merchant_location作成に失敗: {response.status_code} {response.text}")

    # --- Taxonomy (publish前のカテゴリ必須アスペクト確認に使用。読み取り専用・アプリケーショントークン) ---
    def get_item_aspects_for_category(self, category_id: str, marketplace_id: str = "EBAY_US") -> list[dict]:
        tree_data = self._get(
            TAXONOMY_DEFAULT_TREE_PATH, params={"marketplace_id": marketplace_id}, use_app_token=True
        )
        tree_id = tree_data.get("categoryTreeId")
        if not tree_id:
            return []
        data = self._get(
            TAXONOMY_ASPECTS_PATH.format(tree_id=tree_id),
            params={"category_id": category_id},
            use_app_token=True,
        )
        return data.get("aspects", [])
