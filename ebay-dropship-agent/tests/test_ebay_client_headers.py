"""Inventory/Offer系の書き込み呼び出しとBrowse APIに必須のHTTPヘッダーのテスト。

実Sandbox疎通で errorId 25709("Invalid value for header Content-Language")が
発生したことを受けて追加。Content-Language / X-EBAY-C-MARKETPLACE-ID が正しく送られる
ことをモックで検証する(実eBayへは接続しない)。
"""

from __future__ import annotations

import httpx

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.config import Settings


def _client(handler, **kwargs) -> EbayClient:
    def token_or_delegate(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        return handler(request)

    return EbayClient(
        "id",
        "secret",
        "refresh",
        sandbox=True,
        http_client=httpx.Client(transport=httpx.MockTransport(token_or_delegate)),
        **kwargs,
    )


def test_default_marketplace_and_content_language_are_ebay_us_en_us():
    client = _client(lambda r: httpx.Response(200))

    assert client.marketplace_id == "EBAY_US"
    assert client.content_language == "en-US"


def test_create_or_update_inventory_item_sends_content_language_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Language"] == "en-US"
        return httpx.Response(204)

    _client(handler).create_or_update_inventory_item("SKU-1", {"condition": "NEW"})


def test_create_offer_sends_content_language_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Language"] == "en-US"
        return httpx.Response(201, json={"offerId": "offer-1"})

    _client(handler).create_offer("SKU-1", {"categoryId": "9355"})


def test_publish_offer_sends_content_language_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Language"] == "en-US"
        return httpx.Response(200, json={"listingId": "listing-1"})

    _client(handler).publish_offer("offer-1")


def test_update_offer_sends_content_language_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Language"] == "en-US"
        return httpx.Response(204)

    _client(handler).update_offer("offer-1", {"pricingSummary": {}})


def test_create_merchant_location_sends_content_language_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Language"] == "en-US"
        return httpx.Response(204)

    _client(handler).create_merchant_location("default", {"location": {}})


def test_search_competitive_listings_sends_marketplace_id_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"
        return httpx.Response(200, json={"itemSummaries": []})

    _client(handler).search_competitive_listings("widget")


def test_headers_use_configured_marketplace_and_language_when_customized():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Content-Language"] == "de-DE"
        return httpx.Response(204)

    client = _client(handler, marketplace_id="EBAY_DE", content_language="de-DE")

    client.create_or_update_inventory_item("SKU-1", {"condition": "NEW"})

    def marketplace_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_DE"
        return httpx.Response(200, json={"itemSummaries": []})

    client2 = _client(marketplace_handler, marketplace_id="EBAY_DE", content_language="de-DE")
    client2.search_competitive_listings("widget")


def test_from_settings_passes_marketplace_and_content_language():
    settings = Settings(
        ebay_client_id="id", ebay_client_secret="secret", ebay_refresh_token="refresh",
        ebay_marketplace_id="EBAY_GB", ebay_content_language="en-GB",
    )

    client = EbayClient.from_settings(settings)

    assert client.marketplace_id == "EBAY_GB"
    assert client.content_language == "en-GB"


def test_from_settings_defaults_to_ebay_us_en_us_when_unset():
    settings = Settings(ebay_client_id="id", ebay_client_secret="secret", ebay_refresh_token="refresh")

    client = EbayClient.from_settings(settings)

    assert client.marketplace_id == "EBAY_US"
    assert client.content_language == "en-US"
