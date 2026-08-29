"""相場データ取得の抽象化。mock(テスト/開発)→sandbox→本番をこのインターフェース越しに差し替える。

サプライヤー連携(supplier/)と同じ設計方針: 具体的な取得手段を実装差し替え可能にし、
呼び出し側(research評価ロジック)はインターフェースだけに依存する。
"""

from __future__ import annotations

import statistics
from abc import ABC, abstractmethod
from decimal import Decimal

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.research.models import MarketSnapshot


class MarketDataProvider(ABC):
    @abstractmethod
    def fetch_market_snapshot(
        self, keywords: str, category_id: str, shipping_cost: Decimal
    ) -> MarketSnapshot: ...


class MockMarketDataProvider(MarketDataProvider):
    """テスト・開発用の固定フィクスチャ提供者。キーワード一致しなければ相場データ無し扱い。"""

    def __init__(self, fixtures: dict[str, MarketSnapshot]):
        self._fixtures = fixtures

    def fetch_market_snapshot(
        self, keywords: str, category_id: str, shipping_cost: Decimal
    ) -> MarketSnapshot:
        if keywords in self._fixtures:
            return self._fixtures[keywords]
        return MarketSnapshot(
            median_price=None, competitor_count=None, recent_sales_30d=None, shipping_cost=shipping_cost
        )


class EbayBrowseMarketDataProvider(MarketDataProvider):
    """Browse API 経由。EbayClient.sandbox の値で Sandbox/本番が切り替わる(コード変更不要)。

    既知の限界: Browse API は販売実績(直近30日の売れ行き)を提供しないため recent_sales_30d は常に None。
    需要判定に売れ行きシグナルが必要な場合は、別途 Analytics/Marketplace Insights の統合が必要(将来拡張)。
    """

    def __init__(self, client: EbayClient):
        self._client = client

    def fetch_market_snapshot(
        self, keywords: str, category_id: str, shipping_cost: Decimal
    ) -> MarketSnapshot:
        items = self._client.search_competitive_listings(keywords, category_id=category_id)
        prices = [Decimal(item["price"]["value"]) for item in items if "price" in item]
        median_price = statistics.median(prices) if prices else None
        competitor_count = len(items) if items else None
        return MarketSnapshot(
            median_price=median_price,
            competitor_count=competitor_count,
            recent_sales_30d=None,
            shipping_cost=shipping_cost,
        )
