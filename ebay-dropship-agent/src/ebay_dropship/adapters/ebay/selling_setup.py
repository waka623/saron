"""`ebay-dropship sandbox setup-selling` が使う、ビジネスポリシー・出荷元ロケーションの

最小構成ペイロードと「無ければ作成・有れば再利用」の冪等ロジック。

execute-publish --live の publishOffer は、listingPolicies(支払い/返品/配送)と
merchantLocationKey が有効な値を指していないと失敗する。ここではその前提を整えるため、
名前で既存ポリシー/ロケーションを探し、無ければ最小構成で新規作成する(何度実行しても
重複作成しない)。実ネットワークI/Oは受け取った `ebay_client` 経由でのみ行う
(このモジュール自身はテストしやすいよう副作用を極力薄く保つ)。
"""

from __future__ import annotations

from dataclasses import dataclass

from ebay_dropship.envfile import upsert_env_var

MARKETPLACE_ID = "EBAY_US"
DEFAULT_MERCHANT_LOCATION_KEY = "default"

POLICY_NAME_PREFIX = "ebay-dropship-agent"
PAYMENT_POLICY_NAME = f"{POLICY_NAME_PREFIX} Default Payment Policy"
RETURN_POLICY_NAME = f"{POLICY_NAME_PREFIX} Default Return Policy"
FULFILLMENT_POLICY_NAME = f"{POLICY_NAME_PREFIX} Default Fulfillment Policy"


def find_policy_id(policies: list[dict], name: str, id_field: str) -> str | None:
    for policy in policies:
        if policy.get("name") == name:
            return policy.get(id_field)
    return None


def build_payment_policy_payload(marketplace_id: str = MARKETPLACE_ID) -> dict:
    # EBAY_US は Managed Payments 前提のため paymentMethods は指定しない(eBay公式の最小構成)。
    return {
        "name": PAYMENT_POLICY_NAME,
        "marketplaceId": marketplace_id,
        "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
    }


def build_return_policy_payload(marketplace_id: str = MARKETPLACE_ID) -> dict:
    return {
        "name": RETURN_POLICY_NAME,
        "marketplaceId": marketplace_id,
        "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
        "returnsAccepted": False,
    }


def build_fulfillment_policy_payload(marketplace_id: str = MARKETPLACE_ID) -> dict:
    return {
        "name": FULFILLMENT_POLICY_NAME,
        "marketplaceId": marketplace_id,
        "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
        "handlingTime": {"value": 3, "unit": "DAY"},
        "shippingOptions": [
            {
                "optionType": "DOMESTIC",
                "costType": "FLAT_RATE",
                "shippingServices": [
                    {
                        "shippingServiceCode": "USPSPriority",
                        "shippingCost": {"value": "0.00", "currency": "USD"},
                        "freeShipping": True,
                    }
                ],
            }
        ],
    }


def build_merchant_location_payload() -> dict:
    """米国ダミー住所(Sandbox検証専用。実出荷元ではない)。"""
    return {
        "location": {
            "address": {
                "addressLine1": "2211 N First St",
                "city": "San Jose",
                "stateOrProvince": "CA",
                "postalCode": "95131",
                "country": "US",
            }
        },
        "locationTypes": ["WAREHOUSE"],
        "name": f"{POLICY_NAME_PREFIX} Default Location (Sandbox)",
        "merchantLocationStatus": "ENABLED",
    }


@dataclass
class SetupSellingReport:
    opted_in_this_run: bool
    payment_policy_id: str
    payment_policy_created: bool
    return_policy_id: str
    return_policy_created: bool
    fulfillment_policy_id: str
    fulfillment_policy_created: bool
    merchant_location_key: str
    merchant_location_created: bool


def run_setup_selling(ebay_client, env_file: str = ".env") -> SetupSellingReport:
    """冪等: 既に作成済みの名前一致ポリシー/ロケーションがあれば再利用し、無ければ最小構成で作成する。"""
    opted_in_this_run = ebay_client.opt_in_selling_policy_management()

    payment_policies = ebay_client.list_payment_policies(MARKETPLACE_ID)
    payment_policy_id = find_policy_id(payment_policies, PAYMENT_POLICY_NAME, "paymentPolicyId")
    payment_policy_created = False
    if not payment_policy_id:
        created = ebay_client.create_payment_policy(build_payment_policy_payload())
        payment_policy_id = created["paymentPolicyId"]
        payment_policy_created = True

    return_policies = ebay_client.list_return_policies(MARKETPLACE_ID)
    return_policy_id = find_policy_id(return_policies, RETURN_POLICY_NAME, "returnPolicyId")
    return_policy_created = False
    if not return_policy_id:
        created = ebay_client.create_return_policy(build_return_policy_payload())
        return_policy_id = created["returnPolicyId"]
        return_policy_created = True

    fulfillment_policies = ebay_client.list_fulfillment_policies(MARKETPLACE_ID)
    fulfillment_policy_id = find_policy_id(fulfillment_policies, FULFILLMENT_POLICY_NAME, "fulfillmentPolicyId")
    fulfillment_policy_created = False
    if not fulfillment_policy_id:
        created = ebay_client.create_fulfillment_policy(build_fulfillment_policy_payload())
        fulfillment_policy_id = created["fulfillmentPolicyId"]
        fulfillment_policy_created = True

    merchant_location_key = DEFAULT_MERCHANT_LOCATION_KEY
    existing_location = ebay_client.get_merchant_location(merchant_location_key)
    merchant_location_created = False
    if existing_location is None:
        ebay_client.create_merchant_location(merchant_location_key, build_merchant_location_payload())
        merchant_location_created = True

    upsert_env_var(env_file, "EBAY_PAYMENT_POLICY_ID", payment_policy_id)
    upsert_env_var(env_file, "EBAY_RETURN_POLICY_ID", return_policy_id)
    upsert_env_var(env_file, "EBAY_FULFILLMENT_POLICY_ID", fulfillment_policy_id)
    upsert_env_var(env_file, "EBAY_MERCHANT_LOCATION_KEY", merchant_location_key)

    return SetupSellingReport(
        opted_in_this_run=opted_in_this_run,
        payment_policy_id=payment_policy_id,
        payment_policy_created=payment_policy_created,
        return_policy_id=return_policy_id,
        return_policy_created=return_policy_created,
        fulfillment_policy_id=fulfillment_policy_id,
        fulfillment_policy_created=fulfillment_policy_created,
        merchant_location_key=merchant_location_key,
        merchant_location_created=merchant_location_created,
    )
