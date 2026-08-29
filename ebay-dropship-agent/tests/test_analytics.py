"""KPI集計(Check)のテスト。売上ゼロ・サンプル不足・乖離ありのエッジケースを含む。"""

from decimal import Decimal

import pytest

from ebay_dropship.analytics import (
    FixtureMetricsProvider,
    ListingMetricsSnapshot,
    summarize_listing_metrics,
)


def _provider(**overrides) -> FixtureMetricsProvider:
    defaults = {
        "listing_id": "A123",
        "period_days": 30,
        "impressions": 1000,
        "views": 210,
        "watches": 4,
        "sold": 0,
        "returns": 0,
    }
    defaults.update(overrides)
    return FixtureMetricsProvider({"A123": ListingMetricsSnapshot(**defaults)})


def test_normal_case_computes_rates():
    provider = _provider(sold=5, returns=0, views=200)

    summary = summarize_listing_metrics("A123", provider, min_sample_views=30)

    assert summary.sell_through_rate == Decimal(5) / Decimal(200)
    assert summary.sample_sufficient is True
    assert summary.has_return_rate_divergence is False


def test_zero_sales_gives_zero_sell_through_rate():
    """売上ゼロ: 分母(views)は正なので0という値そのものが得られる(Noneではない)。"""
    provider = _provider(sold=0, views=210)

    summary = summarize_listing_metrics("A123", provider, min_sample_views=30)

    assert summary.sell_through_rate == Decimal(0)
    assert summary.return_rate is None  # sold=0のため返品率は計算不能(0除算を避けNoneにする)


def test_insufficient_sample_flagged():
    provider = _provider(views=5, sold=0)

    summary = summarize_listing_metrics("A123", provider, min_sample_views=30)

    assert summary.sample_sufficient is False


def test_zero_views_yields_none_rates_not_error():
    """さらに薄いエッジケース: view自体が0(0除算をNoneで回避)。"""
    provider = _provider(views=0, watches=0, sold=0, impressions=0)

    summary = summarize_listing_metrics("A123", provider, min_sample_views=30)

    assert summary.sell_through_rate is None
    assert summary.watch_rate is None
    assert summary.sample_sufficient is False


def test_return_rate_divergence_flagged_when_above_threshold():
    provider = _provider(sold=10, returns=2, views=200)  # 返品率20% > 閾値10%

    summary = summarize_listing_metrics("A123", provider, min_sample_views=30)

    assert summary.return_rate == Decimal("0.2")
    assert summary.has_return_rate_divergence is True


def test_return_rate_within_threshold_not_flagged():
    provider = _provider(sold=10, returns=1, views=200)  # 返品率10%はちょうど閾値、超過ではない

    summary = summarize_listing_metrics("A123", provider, min_sample_views=30)

    assert summary.has_return_rate_divergence is False


def test_unknown_listing_raises_key_error():
    provider = _provider()

    with pytest.raises(KeyError):
        summarize_listing_metrics("UNKNOWN", provider, min_sample_views=30)
