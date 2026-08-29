"""guardrails のスケルトンテスト。Phase 2 で実装が入ったら skip を外して検証する。"""

import pytest

from ebay_dropship import guardrails


@pytest.mark.skip(reason="Phase 2 で check_not_retail_arbitrage を実装後に有効化")
def test_blocks_retail_arbitrage_wording():
    result = guardrails.check_not_retail_arbitrage("注文が来たらAmazonで買って顧客へ直送する")
    assert result.passed is False


@pytest.mark.skip(reason="Phase 2 で check_not_retail_arbitrage を実装後に有効化")
def test_allows_wholesale_direct_ship_wording():
    result = guardrails.check_not_retail_arbitrage("卸サプライヤーが顧客へ直送する")
    assert result.passed is True


@pytest.mark.skip(reason="Phase 2 で check_requires_human_approval を実装後に有効化")
@pytest.mark.parametrize(
    "proposal_type", ["publish", "price_change", "withdraw", "purchase"]
)
def test_write_operations_require_human_approval(proposal_type):
    assert guardrails.check_requires_human_approval(proposal_type) is True


@pytest.mark.skip(reason="Phase 2 で check_profit_guard を実装後に有効化")
def test_profit_guard_blocks_below_min_net_profit():
    result = guardrails.check_profit_guard(estimated_profit=2.0, min_net_profit=5.0)
    assert result.passed is False


@pytest.mark.skip(reason="Phase 2 で check_profit_guard を実装後に有効化")
def test_profit_guard_allows_above_min_net_profit():
    result = guardrails.check_profit_guard(estimated_profit=8.0, min_net_profit=5.0)
    assert result.passed is True


@pytest.mark.skip(reason="Phase 2 で check_rate_budget を実装後に有効化")
def test_rate_budget_blocks_when_insufficient_calls_remain():
    result = guardrails.check_rate_budget(calls_remaining=3, calls_needed=10)
    assert result.passed is False


@pytest.mark.skip(reason="Phase 2 で check_supplier_stock を実装後に有効化")
def test_supplier_stock_holds_when_insufficient():
    result = guardrails.check_supplier_stock(available_quantity=0, requested_quantity=1)
    assert result.passed is False
