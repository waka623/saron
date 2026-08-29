"""OAuth(トークン取得+自動リフレッシュ)のテスト。実キー無しでも httpx をモックして検証する。"""

import httpx
import pytest

from ebay_dropship.adapters.ebay.auth import EbayAuthError, EbayOAuthClient


def _token_transport(call_log: list, expires_in: int = 3600):
    def handler(request: httpx.Request) -> httpx.Response:
        call_log.append(request)
        return httpx.Response(200, json={"access_token": f"token-{len(call_log)}", "expires_in": expires_in})

    return httpx.MockTransport(handler)


def test_fetches_and_caches_token_until_expiry():
    calls: list = []
    http_client = httpx.Client(transport=_token_transport(calls, expires_in=3600))
    now = [1000.0]
    oauth = EbayOAuthClient("id", "secret", "refresh", http_client=http_client, clock=lambda: now[0])

    token1 = oauth.get_access_token()
    now[0] += 10  # 期限(3600秒後)にはまだ遠い
    token2 = oauth.get_access_token()

    assert token1 == token2
    assert len(calls) == 1  # キャッシュが効いてリフレッシュは1回だけ


def test_refreshes_token_after_expiry():
    calls: list = []
    http_client = httpx.Client(transport=_token_transport(calls, expires_in=100))
    now = [1000.0]
    oauth = EbayOAuthClient("id", "secret", "refresh", http_client=http_client, clock=lambda: now[0])

    token1 = oauth.get_access_token()
    now[0] += 1000  # 100秒の有効期限をとうに超過
    token2 = oauth.get_access_token()

    assert token1 != token2
    assert len(calls) == 2


def test_raises_clear_error_when_credentials_missing():
    oauth = EbayOAuthClient("", "", "", http_client=httpx.Client(transport=_token_transport([])))
    with pytest.raises(EbayAuthError, match="EBAY_CLIENT_ID"):
        oauth.get_access_token()


def test_raises_on_non_200_token_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    oauth = EbayOAuthClient("id", "secret", "bad-refresh-token", http_client=http_client)

    with pytest.raises(EbayAuthError, match="400"):
        oauth.get_access_token()
