"""`ebay-dropship sandbox get-refresh-token` のCLI統合テスト(対話入力+.env書き込みまで)。

実eBayへは接続しない。`httpx.Client`をこのテストだけ差し替え、authorization codeフローの
トークン交換をローカルで完結させる。
"""

from __future__ import annotations

import httpx
import pytest
from click.testing import CliRunner

from ebay_dropship.cli import cli
from ebay_dropship.config import settings


@pytest.fixture()
def sandbox_creds(monkeypatch):
    monkeypatch.setattr(settings, "ebay_env", "sandbox")
    monkeypatch.setattr(settings, "ebay_client_id", "test-client-id")
    monkeypatch.setattr(settings, "ebay_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "ebay_redirect_uri", "test-runame")


class _FakeHttpClient:
    def __init__(self, refresh_token: str = "v^1.1#brand-new-refresh-token", status_code: int = 200):
        self.refresh_token = refresh_token
        self.status_code = status_code
        self.requests: list[dict] = []

    def post(self, url, *, auth=None, data=None, headers=None):
        self.requests.append({"url": url, "auth": auth, "data": data})
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"error": "invalid_grant", "error_description": "bad code"})
        return httpx.Response(
            200, json={"access_token": "at-value", "refresh_token": self.refresh_token, "expires_in": 7200}
        )


def test_get_refresh_token_happy_path_saves_to_env_and_masks_output(sandbox_creds, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("EBAY_CLIENT_ID=test-client-id\n", encoding="utf-8")
    fake_http = _FakeHttpClient()
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake_http)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["sandbox", "get-refresh-token", "--env-file", str(env_path)],
        input="https://example.com/callback?code=abc123&expires_in=299\n",
    )

    assert result.exit_code == 0, result.output
    assert "v^1.1#brand-new-refresh-token" not in result.output  # トークン自体は出力しない
    assert "v^1.1#" in result.output  # 先頭の一部だけは表示
    assert "auth.sandbox.ebay.com" in result.output  # 認可URLはSandboxのものを表示
    assert env_path.read_text(encoding="utf-8").strip().endswith(
        "EBAY_REFRESH_TOKEN=v^1.1#brand-new-refresh-token"
    )
    # authorization_codeグラントで交換していること
    assert fake_http.requests[0]["data"]["grant_type"] == "authorization_code"
    assert fake_http.requests[0]["data"]["code"] == "abc123"


def test_get_refresh_token_uses_production_host_when_env_is_production(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ebay_env", "production")
    monkeypatch.setattr(settings, "ebay_client_id", "test-client-id")
    monkeypatch.setattr(settings, "ebay_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "ebay_redirect_uri", "test-runame")
    env_path = tmp_path / ".env"
    fake_http = _FakeHttpClient()
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake_http)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["sandbox", "get-refresh-token", "--env-file", str(env_path)],
        input="https://example.com/callback?code=abc123\n",
    )

    assert result.exit_code == 0, result.output
    assert "auth.ebay.com" in result.output
    assert "auth.sandbox.ebay.com" not in result.output


def test_get_refresh_token_fails_cleanly_when_credentials_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ebay_client_id", "")
    monkeypatch.setattr(settings, "ebay_client_secret", "")
    monkeypatch.setattr(settings, "ebay_redirect_uri", "")
    runner = CliRunner()

    result = runner.invoke(cli, ["sandbox", "get-refresh-token", "--env-file", str(tmp_path / ".env")])

    assert result.exit_code != 0


def test_get_refresh_token_fails_cleanly_when_user_denies_consent(sandbox_creds, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    fake_http = _FakeHttpClient()
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake_http)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["sandbox", "get-refresh-token", "--env-file", str(env_path)],
        input="https://example.com/callback?error=access_denied&error_description=User+cancelled\n",
    )

    assert result.exit_code != 0
    assert "access_denied" in result.output
    assert not env_path.exists()  # トークン交換まで到達していない
    assert fake_http.requests == []


def test_get_refresh_token_reports_ebay_error_on_exchange_failure(sandbox_creds, monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    fake_http = _FakeHttpClient(status_code=400)
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: fake_http)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["sandbox", "get-refresh-token", "--env-file", str(env_path)],
        input="https://example.com/callback?code=abc123\n",
    )

    assert result.exit_code != 0
    assert "invalid_grant" in result.output
