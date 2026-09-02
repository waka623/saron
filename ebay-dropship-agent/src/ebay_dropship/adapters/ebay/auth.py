"""eBay OAuth 2.0(refresh token フロー)。トークンをメモリにキャッシュし、期限切れ時のみ自動リフレッシュする。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
PRODUCTION_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"

# eBay公式ドキュメントで定義されたOAuthスコープURI(OAuth scopes for the Sell APIs)。
# BASE_SCOPEは読み取り専用の公開API(Browse等)向け、それ以外はSell API群(ユーザーの同意=
# refresh_tokenが必要)向け。個別のSell APIを呼ぶために必要な最小のスコープをここに列挙する。
BASE_SCOPE = "https://api.ebay.com/oauth/api_scope"
SELL_INVENTORY_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.inventory"
SELL_FULFILLMENT_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.fulfillment"
SELL_ACCOUNT_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.account"
SELL_ANALYTICS_READONLY_SCOPE = "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly"

# ユーザートークン(refresh_tokenフロー)で要求するスコープ。このコードベースが実際に呼ぶ
# Sell API群(Inventory/Fulfillment/Analytics)すべてを1つのトークンでカバーする
# (eBayのOAuthは1つのアクセストークンに複数スコープを持たせられる)。
# 注意: refresh_token自体が、これらのスコープをSandboxの「Get A Token」等での同意時に
# 許可されていない場合、ここでいくら要求してもinvalid_scopeで拒否される
# (このコード側の修正だけでは解決しない。同意をやり直してrefresh_tokenを再発行する必要がある)。
DEFAULT_SCOPES = (
    f"{BASE_SCOPE} {SELL_INVENTORY_SCOPE} {SELL_FULFILLMENT_SCOPE} "
    f"{SELL_ACCOUNT_SCOPE} {SELL_ANALYTICS_READONLY_SCOPE}"
)


class EbayAuthError(Exception):
    pass


@dataclass
class AccessToken:
    value: str
    expires_at: float  # unix time

    def is_expired(self, now: float, skew_seconds: float = 60.0) -> bool:
        return now >= (self.expires_at - skew_seconds)


class EbayOAuthClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        sandbox: bool = True,
        http_client: httpx.Client | None = None,
        scopes: str = DEFAULT_SCOPES,
        clock: Callable[[], float] = time.time,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.sandbox = sandbox
        self.token_url = SANDBOX_TOKEN_URL if sandbox else PRODUCTION_TOKEN_URL
        self.scopes = scopes
        self._http = http_client or httpx.Client(timeout=10.0)
        self._clock = clock
        self._token: AccessToken | None = None

    def get_access_token(self) -> str:
        if self._token is None or self._token.is_expired(now=self._clock()):
            self._token = self._refresh()
        return self._token.value

    def _refresh(self) -> AccessToken:
        if not self.client_id or not self.client_secret or not self.refresh_token:
            raise EbayAuthError(
                "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET / EBAY_REFRESH_TOKEN が未設定です。"
                ".env に Sandbox の値を設定してください(compliance.md 第5章)。"
            )
        response = self._http.post(
            self.token_url,
            auth=(self.client_id, self.client_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "scope": self.scopes,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise EbayAuthError(f"トークン取得に失敗しました: {response.status_code} {response.text}")
        data = response.json()
        return AccessToken(value=data["access_token"], expires_at=self._clock() + data["expires_in"])


class EbayApplicationOAuthClient:
    """eBay OAuth 2.0(client credentials フロー)。ユーザーの同意なしで取得できるアプリケーション

    トークン。Browse等、特定の出品者の情報を扱わない読み取り専用APIに使う
    (Sell API群はユーザートークン=`EbayOAuthClient`を使うこと。データが違う)。
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        sandbox: bool = True,
        http_client: httpx.Client | None = None,
        scopes: str = BASE_SCOPE,
        clock: Callable[[], float] = time.time,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.sandbox = sandbox
        self.token_url = SANDBOX_TOKEN_URL if sandbox else PRODUCTION_TOKEN_URL
        self.scopes = scopes
        self._http = http_client or httpx.Client(timeout=10.0)
        self._clock = clock
        self._token: AccessToken | None = None

    def get_access_token(self) -> str:
        if self._token is None or self._token.is_expired(now=self._clock()):
            self._token = self._refresh()
        return self._token.value

    def _refresh(self) -> AccessToken:
        if not self.client_id or not self.client_secret:
            raise EbayAuthError(
                "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET が未設定です。.env に Sandbox の値を設定してください。"
            )
        response = self._http.post(
            self.token_url,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials", "scope": self.scopes},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise EbayAuthError(f"アプリケーショントークン取得に失敗しました: {response.status_code} {response.text}")
        data = response.json()
        return AccessToken(value=data["access_token"], expires_at=self._clock() + data["expires_in"])
