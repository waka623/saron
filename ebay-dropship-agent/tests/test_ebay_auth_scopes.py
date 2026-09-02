"""OAuthスコープの回帰テスト(2026-09-01)。

adversarial review(2026-08-31)で、`EbayOAuthClient`が常に基本スコープ
(`https://api.ebay.com/oauth/api_scope`)のみでrefresh_tokenをリフレッシュしており、
Inventory/Fulfillment/Analytics(Sell API群)が本来要求する個別スコープ
(sell.inventory / sell.fulfillment / sell.account / sell.analytics.readonly)を
要求していないことを指摘した。実際に401になるかは実Sandbox疎通待ちだったが、
eBay公式ドキュメントで必須スコープが明記されているため、実401を待たずに先に修正する。

方針:
- Sell API群(Inventory/Fulfillment/Account/Analytics)へのアクセスはユーザートークン
  (refresh_tokenフロー)で行い、これらのスコープをすべて要求する。
- Browse等の読み取り専用APIは、ユーザーの同意が不要なアプリケーショントークン
  (client_credentialsフロー、基本スコープのみ)を使う。
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.adapters.ebay.auth import (
    BASE_SCOPE,
    SELL_ACCOUNT_SCOPE,
    SELL_ANALYTICS_READONLY_SCOPE,
    SELL_FULFILLMENT_SCOPE,
    SELL_INVENTORY_SCOPE,
)


class _ScopeRecordingBackend:
    """grant_typeごとに要求されたscopeと発行したトークンを記録するフェイク。"""

    def __init__(self) -> None:
        self.token_requests: list[dict] = []
        self.authorization_headers: dict[str, str] = {}  # path -> Authorization header

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth2/token"):
            body = parse_qs(request.content.decode())
            grant_type = body["grant_type"][0]
            scope = body.get("scope", [""])[0]
            self.token_requests.append({"grant_type": grant_type, "scope": scope})
            token = "user-token-xyz" if grant_type == "refresh_token" else "app-token-abc"
            return httpx.Response(200, json={"access_token": token, "expires_in": 7200})

        self.authorization_headers[path] = request.headers.get("authorization", "")

        if path == "/buy/browse/v1/item_summary/search":
            return httpx.Response(200, json={"itemSummaries": []})
        if path == "/developer/analytics/v1_beta/rate_limit/":
            return httpx.Response(200, json={"rateLimits": []})
        if path == "/sell/fulfillment/v1/order":
            return httpx.Response(200, json={"orders": []})
        if path.startswith("/sell/inventory/v1/inventory_item/") and request.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def _client(backend: _ScopeRecordingBackend) -> EbayClient:
    return EbayClient("id", "secret", "refresh", sandbox=True, http_client=httpx.Client(transport=backend.transport()))


def test_user_token_refresh_requests_all_required_sell_scopes():
    """ユーザートークン(refresh_tokenフロー)が、Sell API群に必要な全スコープを要求すること。"""
    backend = _ScopeRecordingBackend()
    client = _client(backend)

    client.get_rate_limits()  # 何でもよいのでユーザートークンを1回引かせる

    refresh_requests = [r for r in backend.token_requests if r["grant_type"] == "refresh_token"]
    assert len(refresh_requests) == 1
    requested_scopes = refresh_requests[0]["scope"].split()
    for required in (
        BASE_SCOPE,
        SELL_INVENTORY_SCOPE,
        SELL_FULFILLMENT_SCOPE,
        SELL_ACCOUNT_SCOPE,
        SELL_ANALYTICS_READONLY_SCOPE,
    ):
        assert required in requested_scopes, f"必須スコープ不足: {required}"


def test_search_competitive_listings_uses_application_token_not_user_token():
    """Browse(読み取り専用)はアプリケーショントークン(client_credentials、ユーザー同意不要)を使うこと。"""
    backend = _ScopeRecordingBackend()
    client = _client(backend)

    client.search_competitive_listings("wireless mouse", category_id="123")

    auth_header = backend.authorization_headers["/buy/browse/v1/item_summary/search"]
    assert auth_header == "Bearer app-token-abc"


def test_application_token_requests_only_base_scope():
    """アプリケーショントークンはSellの個別スコープを要求せず、基本スコープのみであること。"""
    backend = _ScopeRecordingBackend()
    client = _client(backend)

    client.search_competitive_listings("wireless mouse", category_id="123")

    app_requests = [r for r in backend.token_requests if r["grant_type"] == "client_credentials"]
    assert len(app_requests) == 1
    assert app_requests[0]["scope"] == BASE_SCOPE


def test_sell_apis_continue_to_use_the_user_token():
    """Inventory/Fulfillment/AnalyticsはBrowseに変わらずユーザートークンを使い続けること(回帰防止)。"""
    backend = _ScopeRecordingBackend()
    client = _client(backend)

    client.get_rate_limits()
    client.get_orders()
    client.create_or_update_inventory_item("SKU-1", {"foo": "bar"})

    for path in (
        "/developer/analytics/v1_beta/rate_limit/",
        "/sell/fulfillment/v1/order",
        "/sell/inventory/v1/inventory_item/SKU-1",
    ):
        assert backend.authorization_headers[path] == "Bearer user-token-xyz"
