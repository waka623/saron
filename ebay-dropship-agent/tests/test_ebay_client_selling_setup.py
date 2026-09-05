"""EbayClient に追加した Account(ポリシー)/Inventory location/Taxonomy メソッドのテスト。

`sandbox setup-selling` と execute-publish のアスペクト自動補完が使う、実HTTP呼び出しの形
(パス・パラメータ・冪等な既存扱い)を検証する。実eBayへは接続しない(httpx.MockTransport)。
"""

from __future__ import annotations

import json

import httpx
import pytest

from ebay_dropship.adapters.ebay import EbayApiError, EbayClient


def _client(handler) -> EbayClient:
    def token_or_delegate(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        return handler(request)

    return EbayClient(
        "id", "secret", "refresh", sandbox=True, http_client=httpx.Client(transport=httpx.MockTransport(token_or_delegate))
    )


# --- opt_in_selling_policy_management ---


def test_opt_in_returns_true_on_first_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sell/account/v1/program/opt_in"
        assert json.loads(request.content) == {"programType": "SELLING_POLICY_MANAGEMENT"}
        return httpx.Response(200)

    assert _client(handler).opt_in_selling_policy_management() is True


def test_opt_in_returns_false_when_already_opted_in():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"errors": [{"errorId": 20404, "message": "You have already opted in."}]},
        )

    assert _client(handler).opt_in_selling_policy_management() is False


def test_opt_in_raises_on_unrelated_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": [{"errorId": 999, "message": "boom"}]})

    with pytest.raises(EbayApiError):
        _client(handler).opt_in_selling_policy_management()


# --- payment/return/fulfillment policy list+create ---


def test_list_payment_policies_passes_marketplace_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sell/account/v1/payment_policy"
        assert request.url.params["marketplace_id"] == "EBAY_US"
        return httpx.Response(200, json={"paymentPolicies": [{"name": "x", "paymentPolicyId": "p1"}]})

    policies = _client(handler).list_payment_policies("EBAY_US")

    assert policies == [{"name": "x", "paymentPolicyId": "p1"}]


def test_create_payment_policy_returns_new_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"paymentPolicyId": "new-id"})

    result = _client(handler).create_payment_policy({"name": "x"})

    assert result["paymentPolicyId"] == "new-id"


def test_create_return_policy_raises_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    with pytest.raises(EbayApiError):
        _client(handler).create_return_policy({"name": "x"})


def test_list_fulfillment_policies_returns_empty_list_when_none_exist():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert _client(handler).list_fulfillment_policies("EBAY_US") == []


# --- merchant location ---


def test_get_merchant_location_returns_none_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sell/inventory/v1/location/default"
        return httpx.Response(404)

    assert _client(handler).get_merchant_location("default") is None


def test_get_merchant_location_returns_data_when_found():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merchantLocationKey": "default"})

    assert _client(handler).get_merchant_location("default") == {"merchantLocationKey": "default"}


def test_create_merchant_location_posts_to_key_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sell/inventory/v1/location/default"
        assert request.method == "POST"
        return httpx.Response(204)

    _client(handler).create_merchant_location("default", {"name": "loc"})  # raises on failure only


# --- taxonomy ---


def test_get_item_aspects_for_category_resolves_tree_id_then_fetches_aspects():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/commerce/taxonomy/v1/get_default_category_tree_id":
            assert request.url.params["marketplace_id"] == "EBAY_US"
            return httpx.Response(200, json={"categoryTreeId": "0"})
        if request.url.path == "/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category":
            assert request.url.params["category_id"] == "9355"
            return httpx.Response(200, json={"aspects": [{"localizedAspectName": "Brand"}]})
        return httpx.Response(404)

    aspects = _client(handler).get_item_aspects_for_category("9355")

    assert aspects == [{"localizedAspectName": "Brand"}]
    assert calls == [
        "/commerce/taxonomy/v1/get_default_category_tree_id",
        "/commerce/taxonomy/v1/category_tree/0/get_item_aspects_for_category",
    ]


def test_get_item_aspects_for_category_returns_empty_list_when_tree_id_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    assert _client(handler).get_item_aspects_for_category("9355") == []
