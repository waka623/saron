"""`ebay-dropship sandbox get-refresh-token`が使うauthorization codeフローのロジックのテスト。

実eBayへの接続は行わない(httpxはMockTransport、または本テストでは直接呼ばないものは省略)。
URL組み立て・code抽出・.env書き込みは純粋なロジックとして個別にテストする。
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from ebay_dropship.adapters.ebay.auth import (
    DEFAULT_SCOPES,
    PRODUCTION_AUTHORIZE_URL,
    SANDBOX_AUTHORIZE_URL,
    EbayAuthError,
    build_authorization_url,
    exchange_authorization_code_for_refresh_token,
    extract_authorization_code,
)
from ebay_dropship.envfile import upsert_env_var

# --- build_authorization_url ---


def test_build_authorization_url_uses_sandbox_host_by_default():
    url = build_authorization_url("my-client-id", "my-runame")

    assert url.startswith(SANDBOX_AUTHORIZE_URL + "?")


def test_build_authorization_url_uses_production_host_when_requested():
    url = build_authorization_url("my-client-id", "my-runame", sandbox=False)

    assert url.startswith(PRODUCTION_AUTHORIZE_URL + "?")


def test_build_authorization_url_includes_required_params():
    url = build_authorization_url("my-client-id", "my-runame", scopes=DEFAULT_SCOPES)

    query = parse_qs(urlparse(url).query)
    assert query["client_id"] == ["my-client-id"]
    assert query["redirect_uri"] == ["my-runame"]
    assert query["response_type"] == ["code"]
    assert query["prompt"] == ["login"]
    assert query["scope"] == [DEFAULT_SCOPES]


# --- extract_authorization_code ---


def test_extract_authorization_code_from_redirect_url():
    redirected = "https://example.com/callback?code=v%5E1.1%23abc123&expires_in=299"

    code = extract_authorization_code(redirected)

    assert code == "v^1.1#abc123"  # URLデコードされている


def test_extract_authorization_code_raises_on_ebay_error():
    redirected = "https://example.com/callback?error=access_denied&error_description=User+denied+access"

    with pytest.raises(EbayAuthError, match="access_denied"):
        extract_authorization_code(redirected)


def test_extract_authorization_code_raises_when_code_missing_and_no_error():
    redirected = "https://example.com/callback?foo=bar"

    with pytest.raises(EbayAuthError, match="code"):
        extract_authorization_code(redirected)


# --- exchange_authorization_code_for_refresh_token ---


def test_exchange_returns_refresh_token_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/identity/v1/oauth2/token"
        return httpx.Response(
            200,
            json={"access_token": "at", "refresh_token": "v^1.1#rt-secret", "expires_in": 7200},
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    result = exchange_authorization_code_for_refresh_token(
        http_client, "client-id", "client-secret", "auth-code", "my-runame", sandbox=True
    )

    assert result["refresh_token"] == "v^1.1#rt-secret"


def test_exchange_raises_with_ebay_error_details_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "code expired"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(EbayAuthError, match="invalid_grant"):
        exchange_authorization_code_for_refresh_token(
            http_client, "client-id", "client-secret", "auth-code", "my-runame"
        )


# --- upsert_env_var ---


def test_upsert_env_var_creates_file_when_missing(tmp_path):
    env_path = tmp_path / ".env"

    upsert_env_var(env_path, "EBAY_REFRESH_TOKEN", "v^1.1#new-token")

    assert env_path.read_text(encoding="utf-8") == "EBAY_REFRESH_TOKEN=v^1.1#new-token\n"


def test_upsert_env_var_replaces_existing_line_and_keeps_others(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comment\nEBAY_CLIENT_ID=abc\nEBAY_REFRESH_TOKEN=old-token\nEBAY_ENV=sandbox\n", encoding="utf-8"
    )

    upsert_env_var(env_path, "EBAY_REFRESH_TOKEN", "new-token")

    content = env_path.read_text(encoding="utf-8")
    assert "EBAY_REFRESH_TOKEN=new-token" in content
    assert "old-token" not in content
    assert "# comment" in content
    assert "EBAY_CLIENT_ID=abc" in content
    assert "EBAY_ENV=sandbox" in content


def test_upsert_env_var_appends_when_key_absent(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("EBAY_CLIENT_ID=abc\n", encoding="utf-8")

    upsert_env_var(env_path, "EBAY_REFRESH_TOKEN", "brand-new-token")

    content = env_path.read_text(encoding="utf-8")
    assert "EBAY_CLIENT_ID=abc" in content
    assert "EBAY_REFRESH_TOKEN=brand-new-token" in content
