"""eBay OAuth 2.0(refresh token フロー)。トークンをメモリにキャッシュし、期限切れ時のみ自動リフレッシュする。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
PRODUCTION_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SANDBOX_AUTHORIZE_URL = "https://auth.sandbox.ebay.com/oauth2/authorize"
PRODUCTION_AUTHORIZE_URL = "https://auth.ebay.com/oauth2/authorize"

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


# --- authorization code フロー(refresh_tokenの初回発行用) ---
#
# eBayの「Get a User Token」ツール(開発者ポータル)はaccess token(2時間)のみを返し、
# refresh_token(18か月)を返さない。refresh_tokenを得るには、authorization codeフローを
# 自前で1回実行する必要がある(`ebay-dropship sandbox get-refresh-token`が使う)。
# ここでは対話的なUI(ブラウザを開く・入力を待つ等)を一切持たず、CLI側から呼べる純粋な関数として
# 提供する(URL組み立て・codeの抽出・トークン交換はいずれもネットワーク以外は副作用が無く、
# ユニットテストしやすい)。


def build_authorization_url(
    client_id: str, redirect_uri: str, *, sandbox: bool = True, scopes: str = DEFAULT_SCOPES
) -> str:
    """ユーザーがブラウザで開いてサインイン・同意するための認可URLを組み立てる。

    `redirect_uri`はeBayの用語では「RuName」(実際のURLではなく、開発者ポータルに登録した文字列)。
    """
    base = SANDBOX_AUTHORIZE_URL if sandbox else PRODUCTION_AUTHORIZE_URL
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "prompt": "login",
        "scope": scopes,
    }
    return f"{base}?{urlencode(params)}"


def extract_authorization_code(redirected_url: str) -> str:
    """同意後にリダイレクトされたURL全体から`code`クエリパラメータを取り出す(URLデコード込み)。

    ユーザーが同意を拒否した場合等はcodeの代わりに`error`/`error_description`が付くため、
    その場合はeBayのエラー内容をそのまま例外メッセージにする。
    """
    query = parse_qs(urlparse(redirected_url).query)
    if "code" in query and query["code"][0]:
        return query["code"][0]
    error = query.get("error", [None])[0]
    if error:
        error_description = query.get("error_description", [""])[0]
        raise EbayAuthError(f"eBayからエラーが返されました: {error} {error_description}".rstrip())
    raise EbayAuthError(
        "貼り付けられたURLに'code'パラメータが見つかりません。"
        "同意後にリダイレクトされたURL全体をそのまま貼り付けてください。"
    )


def exchange_authorization_code_for_refresh_token(
    http_client: httpx.Client,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    *,
    sandbox: bool = True,
) -> dict:
    """authorization codeをrefresh_token(+access_token)に交換する(grant_type=authorization_code)。

    レスポンスをそのままdictで返す(呼び出し側が`refresh_token`キーを取り出す)。
    """
    token_url = SANDBOX_TOKEN_URL if sandbox else PRODUCTION_TOKEN_URL
    response = http_client.post(
        token_url,
        auth=(client_id, client_secret),
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code != 200:
        try:
            error_body = response.json()
        except ValueError:
            error_body = {}
        error = error_body.get("error", str(response.status_code))
        error_description = error_body.get("error_description", response.text)
        raise EbayAuthError(f"refresh_token取得に失敗しました: {error} {error_description}".rstrip())
    return response.json()
