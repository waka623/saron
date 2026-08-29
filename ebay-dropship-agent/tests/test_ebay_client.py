"""EbayClient の読み取り系疎通確認テスト。実Sandboxキーが揃うまではモックで通す(第1フェーズの完了条件)。"""

import httpx

from ebay_dropship.adapters.ebay import EbayApiError, EbayClient, RateLimitStatus
from ebay_dropship.adapters.ebay.client import RATE_LIMIT_PATH, SANDBOX_API_BASE
from ebay_dropship.config import Settings


def _mock_ebay_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        if request.url.path == RATE_LIMIT_PATH:
            assert request.headers["Authorization"] == "Bearer mock-token"
            return httpx.Response(
                200,
                json={
                    "rateLimits": [
                        {
                            "apiName": "Analytics",
                            "resources": [{"rates": [{"limit": 5000, "remaining": 4990}]}],
                        }
                    ]
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_get_rate_limits_mocked_sandbox_connectivity():
    http_client = httpx.Client(transport=_mock_ebay_transport())
    client = EbayClient("id", "secret", "refresh", sandbox=True, http_client=http_client)

    statuses = client.get_rate_limits()

    assert client.base_url == SANDBOX_API_BASE
    assert statuses == [RateLimitStatus(api_name="Analytics", calls_remaining=4990, daily_limit=5000)]


def test_get_rate_limits_raises_ebay_api_error_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        return httpx.Response(401, text="invalid token")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = EbayClient("id", "secret", "refresh", http_client=http_client)

    try:
        client.get_rate_limits()
        assert False, "EbayApiError が送出されるべき"
    except EbayApiError as exc:
        assert "401" in str(exc)


def test_call_budget_blocks_before_hitting_network():
    from ebay_dropship.adapters.ebay import CallBudget, RateLimitExceeded

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise AssertionError("コールバジェット枯渇時はHTTPに到達しないはず")

    http_client = httpx.Client(transport=httpx.MockTransport(unreachable))
    client = EbayClient(
        "id", "secret", "refresh", http_client=http_client, call_budget=CallBudget(daily_limit=0)
    )

    import pytest

    with pytest.raises(RateLimitExceeded):
        client.get_rate_limits()


def test_from_settings_uses_config_without_hardcoded_secrets():
    settings = Settings(
        ebay_env="sandbox",
        ebay_client_id="dummy-id-from-env",
        ebay_client_secret="dummy-secret-from-env",
        ebay_refresh_token="dummy-refresh-from-env",
    )

    client = EbayClient.from_settings(settings)

    assert client.sandbox is True
    assert client.client_id == "dummy-id-from-env"
