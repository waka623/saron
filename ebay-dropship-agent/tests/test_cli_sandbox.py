"""`ebay-dropship sandbox ...` のテスト。

実eBay Sandboxには接続できない環境でも検証できるよう、`EbayClient.from_settings`を
モックトランスポート付きのクライアントに差し替える(実ネットワークは一切使わない)。
既存のInventoryフェイク(tests/fakes/ebay_inventory_fake.py)にFulfillment/Analyticsの
最小限のルートを足したローカルの完結したフェイクを使う。
"""

from __future__ import annotations

import json

import httpx
import pytest
from click.testing import CliRunner

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.cli import cli
from ebay_dropship.config import settings
from ebay_dropship.store import (
    Base,
    create_engine_from_settings,
)


class SandboxFakeBackend:
    """Inventory(publish)+Fulfillment(getOrders)+Analytics(getRateLimits)をまとめて再現するフェイク。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_auth = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))

        if path.endswith("/oauth2/token"):
            if self.fail_auth:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad refresh token"})
            return httpx.Response(200, json={"access_token": "fake-sandbox-token", "expires_in": 7200})

        if path.startswith("/sell/inventory/v1/inventory_item/") and request.method == "PUT":
            return httpx.Response(204)

        if path == "/sell/inventory/v1/offer" and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(201, json={"offerId": f"offer-{body['sku']}"})

        if path.endswith("/publish") and request.method == "POST":
            offer_id = path.split("/")[-2]
            return httpx.Response(200, json={"listingId": f"listing-{offer_id}"})

        if path == "/sell/fulfillment/v1/order" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "orders": [
                        {
                            "orderId": "SANDBOX-ORDER-1",
                            "orderFulfillmentStatus": "NOT_STARTED",
                            "pricingSummary": {"total": {"value": "29.99", "currency": "USD"}},
                        }
                    ]
                },
            )

        if path == "/developer/analytics/v1_beta/rate_limit/" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "rateLimits": [
                        {
                            "apiName": "sell_inventory",
                            "resources": [{"rates": [{"remaining": 4999, "limit": 5000}]}],
                        }
                    ]
                },
            )

        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture()
def cli_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'sandbox_cli_test.db'}")
    monkeypatch.setattr(settings, "ebay_env", "sandbox")
    monkeypatch.setattr(settings, "ebay_client_id", "fake-id")
    monkeypatch.setattr(settings, "ebay_client_secret", "fake-secret")
    monkeypatch.setattr(settings, "ebay_refresh_token", "fake-refresh")
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def backend():
    return SandboxFakeBackend()


def _patch_from_settings(monkeypatch, backend: SandboxFakeBackend) -> None:
    def _fake_from_settings(cls, _settings):
        return EbayClient(
            "fake-id", "fake-secret", "fake-refresh",
            sandbox=True, http_client=httpx.Client(transport=backend.transport()),
        )

    monkeypatch.setattr(EbayClient, "from_settings", classmethod(_fake_from_settings))


# --- EBAY_ENV=production では全コマンドを拒否する ---


@pytest.mark.parametrize(
    "args",
    [
        ["sandbox", "check-auth"],
        ["sandbox", "rate-limits"],
        ["sandbox", "get-orders"],
        ["sandbox", "execute-publish", "dummy-id"],
    ],
)
def test_sandbox_commands_refuse_when_env_is_production(cli_db, monkeypatch, args):
    monkeypatch.setattr(settings, "ebay_env", "production")
    runner = CliRunner()

    result = runner.invoke(cli, args)

    assert result.exit_code != 0
    assert "production" in result.output


# --- check-auth ---


def test_check_auth_succeeds_and_never_prints_the_token(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()

    result = runner.invoke(cli, ["sandbox", "check-auth"])

    assert result.exit_code == 0
    assert "fake-sandbox-token" not in result.output
    assert "取得" in result.output


def test_check_auth_reports_failure_cleanly(cli_db, backend, monkeypatch):
    backend.fail_auth = True
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()

    result = runner.invoke(cli, ["sandbox", "check-auth"])

    assert result.exit_code != 0


# --- rate-limits ---


def test_rate_limits_prints_remaining_and_limit(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()

    result = runner.invoke(cli, ["sandbox", "rate-limits"])

    assert result.exit_code == 0
    assert "sell_inventory" in result.output
    assert "4999" in result.output


# --- get-orders ---


def test_get_orders_prints_summary_without_pii(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()

    result = runner.invoke(cli, ["sandbox", "get-orders"])

    assert result.exit_code == 0
    assert "SANDBOX-ORDER-1" in result.output
    assert "29.99" in result.output


# --- seed-test-item / execute-publish ---


def test_seed_test_item_requires_category_id(cli_db):
    runner = CliRunner()

    result = runner.invoke(cli, ["sandbox", "seed-test-item"])

    assert result.exit_code != 0


def test_seed_then_execute_publish_dry_run_sends_nothing(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()
    seed_result = runner.invoke(cli, ["sandbox", "seed-test-item", "--category-id", "9355"])
    assert seed_result.exit_code == 0
    proposal_id = seed_result.output.splitlines()[0].split(": ")[1]
    approve_result = runner.invoke(cli, ["proposals", "approve", proposal_id, "--by", "tester"])
    assert approve_result.exit_code == 0

    result = runner.invoke(cli, ["sandbox", "execute-publish", proposal_id])

    assert result.exit_code == 0
    assert backend.calls == []  # dry-runなので何も送信していない
    assert "dry-run" in result.output


def test_seed_then_execute_publish_live_actually_calls_sandbox_fake(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()
    seed_result = runner.invoke(cli, ["sandbox", "seed-test-item", "--category-id", "9355", "--sku", "SANDBOX-TEST-9"])
    proposal_id = seed_result.output.splitlines()[0].split(": ")[1]
    runner.invoke(cli, ["proposals", "approve", proposal_id, "--by", "tester"])

    result = runner.invoke(cli, ["sandbox", "execute-publish", proposal_id, "--live"])

    assert result.exit_code == 0, result.output
    assert ("PUT", "/sell/inventory/v1/inventory_item/SANDBOX-TEST-9") in backend.calls
    assert ("POST", "/sell/inventory/v1/offer") in backend.calls
    assert any(method == "POST" and path.endswith("/publish") for method, path in backend.calls)
    assert "実行完了" in result.output


def test_execute_publish_unknown_proposal_id_fails_cleanly(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()

    result = runner.invoke(cli, ["sandbox", "execute-publish", "does-not-exist"])

    assert result.exit_code != 0
