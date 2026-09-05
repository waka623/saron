"""`ebay-dropship sandbox ...` のテスト。

実eBay Sandboxには接続できない環境でも検証できるよう、`EbayClient.from_settings`を
モックトランスポート付きのクライアントに差し替える(実ネットワークは一切使わない)。
既存のInventoryフェイク(tests/fakes/ebay_inventory_fake.py)にFulfillment/Analyticsの
最小限のルートを足したローカルの完結したフェイクを使う。
"""

from __future__ import annotations

import json
import tempfile

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
    """Inventory(publish)+Fulfillment(getOrders)+Analytics(getRateLimits)をまとめて再現するフェイク。

    setup-selling(Account API opt_in/ポリシー、Inventory location)とTaxonomy(必須アスペクト)も
    最小限再現する。ポリシー/ロケーションは辞書に保持し、CLIを複数回呼んでも冪等に振る舞う
    (実Sandboxの「無ければ作成・有れば再利用」を模す)。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_auth = False
        self.already_opted_in = False
        self._policies: dict[str, list[dict]] = {"payment": [], "return": [], "fulfillment": []}
        self._policy_id_fields = {
            "payment": "paymentPolicyId",
            "return": "returnPolicyId",
            "fulfillment": "fulfillmentPolicyId",
        }
        self._locations: dict[str, dict] = {}
        self._next_policy_seq = 1
        self.last_inventory_item_body: dict | None = None
        self.last_offer_body: dict | None = None
        # category_id=9355 の必須アスペクト。"Brand"はseed-test-item側で常に指定されるため
        # ここでは指定漏れになりがちな"Type"だけを必須にして、自動補完の検証をしやすくする。
        self.required_aspects_by_category = {"9355": ["Type"]}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))

        if path.endswith("/oauth2/token"):
            if self.fail_auth:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad refresh token"})
            return httpx.Response(200, json={"access_token": "fake-sandbox-token", "expires_in": 7200})

        if path.startswith("/sell/inventory/v1/inventory_item/") and request.method == "PUT":
            self.last_inventory_item_body = json.loads(request.content)
            return httpx.Response(204)

        if path == "/sell/inventory/v1/offer" and request.method == "POST":
            body = json.loads(request.content)
            self.last_offer_body = body
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

        if path == "/sell/account/v1/program/opt_in" and request.method == "POST":
            if self.already_opted_in:
                return httpx.Response(400, json={"errors": [{"errorId": 20404, "message": "already opted in"}]})
            self.already_opted_in = True
            return httpx.Response(200)

        for kind, list_path in (
            ("payment", "/sell/account/v1/payment_policy"),
            ("return", "/sell/account/v1/return_policy"),
            ("fulfillment", "/sell/account/v1/fulfillment_policy"),
        ):
            if path == list_path and request.method == "GET":
                key = {"payment": "paymentPolicies", "return": "returnPolicies", "fulfillment": "fulfillmentPolicies"}[
                    kind
                ]
                return httpx.Response(200, json={key: self._policies[kind]})
            if path == list_path and request.method == "POST":
                body = json.loads(request.content)
                policy_id = f"{kind}-policy-{self._next_policy_seq}"
                self._next_policy_seq += 1
                id_field = self._policy_id_fields[kind]
                self._policies[kind].append({**body, id_field: policy_id})
                return httpx.Response(201, json={id_field: policy_id})

        if path.startswith("/sell/inventory/v1/location/"):
            location_key = path.rsplit("/", 1)[-1]
            if request.method == "GET":
                location = self._locations.get(location_key)
                return httpx.Response(200, json=location) if location else httpx.Response(404)
            if request.method == "POST":
                self._locations[location_key] = json.loads(request.content)
                return httpx.Response(204)

        if path == "/commerce/taxonomy/v1/get_default_category_tree_id" and request.method == "GET":
            return httpx.Response(200, json={"categoryTreeId": "0"})

        if path == "/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category" and request.method == "GET":
            category_id = request.url.params.get("category_id")
            required = self.required_aspects_by_category.get(category_id, [])
            aspects = [
                {"localizedAspectName": name, "aspectConstraint": {"aspectRequired": True}} for name in required
            ]
            return httpx.Response(200, json={"aspects": aspects})

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
        ["sandbox", "setup-selling"],
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
    # C: category_id=9355の必須アスペクト"Type"がTaxonomy経由で自動補完されている(seed時は未指定)。
    assert backend.last_inventory_item_body["product"]["aspects"]["Type"] == ["Unbranded"]
    assert backend.last_inventory_item_body["product"]["aspects"]["Brand"] == ["Acme"]  # 既存指定は上書きしない


def test_execute_publish_live_injects_listing_policies_and_merchant_location_from_settings(
    cli_db, backend, monkeypatch
):
    monkeypatch.setattr(settings, "ebay_payment_policy_id", "payment-policy-from-env")
    monkeypatch.setattr(settings, "ebay_return_policy_id", "return-policy-from-env")
    monkeypatch.setattr(settings, "ebay_fulfillment_policy_id", "fulfillment-policy-from-env")
    monkeypatch.setattr(settings, "ebay_merchant_location_key", "warehouse-1")
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()
    seed_result = runner.invoke(
        cli, ["sandbox", "seed-test-item", "--category-id", "9355", "--sku", "SANDBOX-TEST-POLICY"]
    )
    proposal_id = seed_result.output.splitlines()[0].split(": ")[1]
    runner.invoke(cli, ["proposals", "approve", proposal_id, "--by", "tester"])

    result = runner.invoke(cli, ["sandbox", "execute-publish", proposal_id, "--live"])

    assert result.exit_code == 0, result.output
    assert backend.last_offer_body["listingPolicies"] == {
        "fulfillmentPolicyId": "fulfillment-policy-from-env",
        "paymentPolicyId": "payment-policy-from-env",
        "returnPolicyId": "return-policy-from-env",
    }
    assert backend.last_offer_body["merchantLocationKey"] == "warehouse-1"
    # errorId 25709 "Invalid value for marketplaceId.": createOfferのbodyにmarketplaceId/formatが必須。
    assert backend.last_offer_body["marketplaceId"] == "EBAY_US"
    assert backend.last_offer_body["format"] == "FIXED_PRICE"
    assert backend.last_offer_body["sku"] == "SANDBOX-TEST-POLICY"


def test_execute_publish_live_uses_configured_marketplace_id_in_offer_body(cli_db, backend, monkeypatch):
    monkeypatch.setattr(settings, "ebay_marketplace_id", "EBAY_GB")
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()
    seed_result = runner.invoke(
        cli, ["sandbox", "seed-test-item", "--category-id", "9355", "--sku", "SANDBOX-TEST-MKT"]
    )
    proposal_id = seed_result.output.splitlines()[0].split(": ")[1]
    runner.invoke(cli, ["proposals", "approve", proposal_id, "--by", "tester"])

    result = runner.invoke(cli, ["sandbox", "execute-publish", proposal_id, "--live"])

    assert result.exit_code == 0, result.output
    assert backend.last_offer_body["marketplaceId"] == "EBAY_GB"


def test_execute_publish_dry_run_preview_reflects_configured_listing_policies(cli_db, backend, monkeypatch):
    monkeypatch.setattr(settings, "ebay_payment_policy_id", "payment-policy-from-env")
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()
    seed_result = runner.invoke(cli, ["sandbox", "seed-test-item", "--category-id", "9355"])
    proposal_id = seed_result.output.splitlines()[0].split(": ")[1]
    runner.invoke(cli, ["proposals", "approve", proposal_id, "--by", "tester"])

    result = runner.invoke(cli, ["sandbox", "execute-publish", proposal_id])

    assert result.exit_code == 0
    assert "payment-policy-from-env" in result.output
    # dry-runのプレビューにもmarketplaceId/formatが反映されていること(ネットワーク呼び出しは増やさない)。
    assert "'marketplaceId': 'EBAY_US'" in result.output
    assert "'format': 'FIXED_PRICE'" in result.output
    assert backend.calls == []


# --- setup-selling ---


def test_setup_selling_first_run_creates_policies_and_location_and_masks_ids(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    with tempfile.TemporaryDirectory() as tmp:
        env_path = f"{tmp}/.env"
        runner = CliRunner()

        result = runner.invoke(cli, ["sandbox", "setup-selling", "--env-file", env_path])

        assert result.exit_code == 0, result.output
        assert "新規作成" in result.output
        with open(env_path, encoding="utf-8") as f:
            content = f.read()
        assert "EBAY_PAYMENT_POLICY_ID=payment-policy-1" in content
        assert "EBAY_RETURN_POLICY_ID=return-policy-2" in content
        assert "EBAY_FULFILLMENT_POLICY_ID=fulfillment-policy-3" in content
        assert "EBAY_MERCHANT_LOCATION_KEY=default" in content
        # policyId自体はマスクされ、生の値は出力に出ない(先頭数文字のみ許容)。
        assert "payment-policy-1" not in result.output


def test_setup_selling_is_idempotent_on_second_run(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    with tempfile.TemporaryDirectory() as tmp:
        env_path = f"{tmp}/.env"
        runner = CliRunner()
        first = runner.invoke(cli, ["sandbox", "setup-selling", "--env-file", env_path])
        assert first.exit_code == 0, first.output

        second = runner.invoke(cli, ["sandbox", "setup-selling", "--env-file", env_path])

        assert second.exit_code == 0, second.output
        assert "既存を再利用" in second.output
        assert "既にオプトイン済み" in second.output
        # 2回目で重複作成されていない(list呼び出しは1件ずつしか返らない=バックエンド側で重複が無い)。
        assert len(backend._policies["payment"]) == 1
        assert len(backend._policies["return"]) == 1
        assert len(backend._policies["fulfillment"]) == 1


def test_execute_publish_unknown_proposal_id_fails_cleanly(cli_db, backend, monkeypatch):
    _patch_from_settings(monkeypatch, backend)
    runner = CliRunner()

    result = runner.invoke(cli, ["sandbox", "execute-publish", "does-not-exist"])

    assert result.exit_code != 0
