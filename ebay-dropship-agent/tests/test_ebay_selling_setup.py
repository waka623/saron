"""`run_setup_selling`(sandbox setup-sellingが使う冪等ロジック)のテスト。

実eBayへは接続しない。EbayClientの代わりに、必要なメソッドだけを持つ最小のフェイクを使う。
"""

from __future__ import annotations

from ebay_dropship.adapters.ebay.selling_setup import (
    FULFILLMENT_POLICY_NAME,
    PAYMENT_POLICY_NAME,
    RETURN_POLICY_NAME,
    run_setup_selling,
)


class _FakeEbayClient:
    def __init__(self, *, already_opted_in: bool = False, existing_policies: bool = False, existing_location: bool = False):
        self.already_opted_in = already_opted_in
        self.payment_policies = (
            [{"name": PAYMENT_POLICY_NAME, "paymentPolicyId": "existing-payment"}] if existing_policies else []
        )
        self.return_policies = (
            [{"name": RETURN_POLICY_NAME, "returnPolicyId": "existing-return"}] if existing_policies else []
        )
        self.fulfillment_policies = (
            [{"name": FULFILLMENT_POLICY_NAME, "fulfillmentPolicyId": "existing-fulfillment"}]
            if existing_policies
            else []
        )
        self.existing_location = {"merchantLocationKey": "default"} if existing_location else None
        self.created_payment_policies: list[dict] = []
        self.created_return_policies: list[dict] = []
        self.created_fulfillment_policies: list[dict] = []
        self.created_locations: list[tuple[str, dict]] = []

    def opt_in_selling_policy_management(self) -> bool:
        return not self.already_opted_in

    def list_payment_policies(self, marketplace_id: str) -> list[dict]:
        return self.payment_policies

    def create_payment_policy(self, payload: dict) -> dict:
        self.created_payment_policies.append(payload)
        return {"paymentPolicyId": "new-payment"}

    def list_return_policies(self, marketplace_id: str) -> list[dict]:
        return self.return_policies

    def create_return_policy(self, payload: dict) -> dict:
        self.created_return_policies.append(payload)
        return {"returnPolicyId": "new-return"}

    def list_fulfillment_policies(self, marketplace_id: str) -> list[dict]:
        return self.fulfillment_policies

    def create_fulfillment_policy(self, payload: dict) -> dict:
        self.created_fulfillment_policies.append(payload)
        return {"fulfillmentPolicyId": "new-fulfillment"}

    def get_merchant_location(self, merchant_location_key: str) -> dict | None:
        return self.existing_location

    def create_merchant_location(self, merchant_location_key: str, payload: dict) -> None:
        self.created_locations.append((merchant_location_key, payload))


def test_first_run_creates_everything_and_writes_env(tmp_path):
    client = _FakeEbayClient()
    env_path = tmp_path / ".env"

    report = run_setup_selling(client, env_file=str(env_path))

    assert report.opted_in_this_run is True
    assert report.payment_policy_created is True
    assert report.return_policy_created is True
    assert report.fulfillment_policy_created is True
    assert report.merchant_location_created is True
    assert report.payment_policy_id == "new-payment"
    assert report.return_policy_id == "new-return"
    assert report.fulfillment_policy_id == "new-fulfillment"
    assert report.merchant_location_key == "default"

    content = env_path.read_text(encoding="utf-8")
    assert "EBAY_PAYMENT_POLICY_ID=new-payment" in content
    assert "EBAY_RETURN_POLICY_ID=new-return" in content
    assert "EBAY_FULFILLMENT_POLICY_ID=new-fulfillment" in content
    assert "EBAY_MERCHANT_LOCATION_KEY=default" in content


def test_second_run_reuses_existing_policies_and_location_without_duplicating(tmp_path):
    client = _FakeEbayClient(already_opted_in=True, existing_policies=True, existing_location=True)
    env_path = tmp_path / ".env"

    report = run_setup_selling(client, env_file=str(env_path))

    assert report.opted_in_this_run is False
    assert report.payment_policy_created is False
    assert report.return_policy_created is False
    assert report.fulfillment_policy_created is False
    assert report.merchant_location_created is False
    assert report.payment_policy_id == "existing-payment"
    assert report.return_policy_id == "existing-return"
    assert report.fulfillment_policy_id == "existing-fulfillment"
    assert client.created_payment_policies == []
    assert client.created_return_policies == []
    assert client.created_fulfillment_policies == []
    assert client.created_locations == []


def test_run_setup_selling_overwrites_previous_env_values_on_rerun(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("EBAY_PAYMENT_POLICY_ID=stale-value\n", encoding="utf-8")
    client = _FakeEbayClient()

    run_setup_selling(client, env_file=str(env_path))

    content = env_path.read_text(encoding="utf-8")
    assert "stale-value" not in content
    assert "EBAY_PAYMENT_POLICY_ID=new-payment" in content
