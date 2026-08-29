"""MarketDataProvider の mock/Browse実装テスト(mock→sandbox→本番を差し替え可能なことの確認)。"""

from decimal import Decimal

import httpx

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.research.market_data import EbayBrowseMarketDataProvider, MockMarketDataProvider
from ebay_dropship.research.models import MarketSnapshot


def test_mock_provider_returns_fixture_for_known_keyword():
    fixture = MarketSnapshot(
        median_price=Decimal("29.99"), competitor_count=8, recent_sales_30d=20, shipping_cost=Decimal("3.50")
    )
    provider = MockMarketDataProvider({"wireless mouse": fixture})

    result = provider.fetch_market_snapshot(
        "wireless mouse", category_id="123", shipping_cost=Decimal("3.50")
    )

    assert result == fixture


def test_mock_provider_returns_unknown_snapshot_for_unfixtured_keyword():
    provider = MockMarketDataProvider({})

    result = provider.fetch_market_snapshot("no such product", category_id="123", shipping_cost=Decimal("3.50"))

    assert result.median_price is None
    assert result.competitor_count is None


def _browse_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        if request.url.path == "/buy/browse/v1/item_summary/search":
            return httpx.Response(
                200,
                json={
                    "itemSummaries": [
                        {"price": {"value": "28.00", "currency": "USD"}},
                        {"price": {"value": "29.99", "currency": "USD"}},
                        {"price": {"value": "32.50", "currency": "USD"}},
                    ]
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_ebay_browse_provider_computes_median_price_and_competitor_count():
    """実キーが無いため Sandbox 疎通はモックで代替(EbayClient.sandboxフラグでSandbox/本番を切替可能)。"""
    http_client = httpx.Client(transport=_browse_transport())
    client = EbayClient("id", "secret", "refresh", sandbox=True, http_client=http_client)
    provider = EbayBrowseMarketDataProvider(client)

    result = provider.fetch_market_snapshot(
        "wireless mouse", category_id="123", shipping_cost=Decimal("3.50")
    )

    assert result.median_price == Decimal("29.99")
    assert result.competitor_count == 3
    assert result.recent_sales_30d is None  # Browse APIでは取得不可(既知の限界。docstring参照)


def test_ebay_browse_provider_returns_no_data_when_no_results():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 7200})
        return httpx.Response(200, json={"itemSummaries": []})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = EbayClient("id", "secret", "refresh", http_client=http_client)
    provider = EbayBrowseMarketDataProvider(client)

    result = provider.fetch_market_snapshot("obscure item", category_id="999", shipping_cost=Decimal("3.50"))

    assert result.median_price is None
    assert result.competitor_count is None
