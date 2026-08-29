"""KPI 集計(Check)。

実 eBay Analytics API 疎通は本フェーズのスコープ外(実キー未着。DECISIONS.md の
Sandbox E2E ゲートにまとめて TODO 化する)。ここではフィクスチャ/固定データからの集計ロジックを実装し、
pricing(Act)の入力(pricing.models.ListingSnapshot.kpi)を作る。`MetricsProvider` インターフェース越しに
実装しているため、将来 `EbayAnalyticsMetricsProvider` へ差し替え可能(research/market_data.py と同じ方針)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

# 返品率がこれを超えたら「乖離あり」とフラグする(品質問題の早期検知)。
RETURN_RATE_DIVERGENCE_THRESHOLD = Decimal("0.10")


@dataclass(frozen=True)
class ListingMetricsSnapshot:
    listing_id: str
    period_days: int
    impressions: int
    views: int
    watches: int
    sold: int
    returns: int


@dataclass(frozen=True)
class KpiSummary:
    listing_id: str
    period_days: int
    impressions: int
    views: int
    watches: int
    sold: int
    returns: int
    sell_through_rate: Decimal | None  # sold / views
    watch_rate: Decimal | None  # watches / views
    return_rate: Decimal | None  # returns / sold
    sample_sufficient: bool
    has_return_rate_divergence: bool


class MetricsProvider(ABC):
    @abstractmethod
    def fetch_metrics(self, listing_id: str, period_days: int) -> ListingMetricsSnapshot: ...


class FixtureMetricsProvider(MetricsProvider):
    """フィクスチャ/固定データからKPIを返す(本フェーズの既定実装)。"""

    def __init__(self, fixtures: dict[str, ListingMetricsSnapshot]):
        self._fixtures = fixtures

    def fetch_metrics(self, listing_id: str, period_days: int) -> ListingMetricsSnapshot:
        if listing_id not in self._fixtures:
            raise KeyError(listing_id)
        return self._fixtures[listing_id]


def summarize_listing_metrics(
    listing_id: str,
    provider: MetricsProvider,
    *,
    period_days: int = 30,
    min_sample_views: int = 30,
) -> KpiSummary:
    snapshot = provider.fetch_metrics(listing_id, period_days)

    sell_through_rate = (
        Decimal(snapshot.sold) / Decimal(snapshot.views) if snapshot.views > 0 else None
    )
    watch_rate = Decimal(snapshot.watches) / Decimal(snapshot.views) if snapshot.views > 0 else None
    return_rate = Decimal(snapshot.returns) / Decimal(snapshot.sold) if snapshot.sold > 0 else None

    return KpiSummary(
        listing_id=snapshot.listing_id,
        period_days=snapshot.period_days,
        impressions=snapshot.impressions,
        views=snapshot.views,
        watches=snapshot.watches,
        sold=snapshot.sold,
        returns=snapshot.returns,
        sell_through_rate=sell_through_rate,
        watch_rate=watch_rate,
        return_rate=return_rate,
        sample_sufficient=snapshot.views >= min_sample_views,
        has_return_rate_divergence=(
            return_rate is not None and return_rate > RETURN_RATE_DIVERGENCE_THRESHOLD
        ),
    )
