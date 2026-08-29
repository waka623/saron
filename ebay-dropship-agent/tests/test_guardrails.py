"""guardrails の実装テスト(Phase 2)。金額は Decimal 固定(float禁止)。"""

from decimal import Decimal

import pytest

from ebay_dropship import guardrails


def test_blocks_retail_arbitrage_wording():
    result = guardrails.check_not_retail_arbitrage("注文が来たらAmazonで買って顧客へ直送する")
    assert result.passed is False
    assert "小売アービトラージ" in result.reason


def test_allows_wholesale_direct_ship_wording():
    result = guardrails.check_not_retail_arbitrage("卸サプライヤーが顧客へ直送する")
    assert result.passed is True


def test_ambiguous_wording_denies_by_default():
    """卸直送とも小売とも判別できない記述は deny by default。"""
    result = guardrails.check_not_retail_arbitrage("在庫があるので発送します")
    assert result.passed is False
    assert "確認できません" in result.reason


@pytest.mark.parametrize("proposal_type", ["publish", "price_change", "withdraw", "purchase"])
def test_write_operations_require_human_approval(proposal_type):
    assert guardrails.check_requires_human_approval(proposal_type) is True


@pytest.mark.parametrize("proposal_type", ["hold", "none"])
def test_non_write_operations_do_not_require_human_approval(proposal_type):
    assert guardrails.check_requires_human_approval(proposal_type) is False


def test_profit_guard_blocks_below_min_net_profit():
    result = guardrails.check_profit_guard(
        estimated_profit=Decimal("2.0"), min_net_profit=Decimal("5.0")
    )
    assert result.passed is False


def test_profit_guard_allows_above_min_net_profit():
    result = guardrails.check_profit_guard(
        estimated_profit=Decimal("8.0"), min_net_profit=Decimal("5.0")
    )
    assert result.passed is True


def test_profit_guard_denies_when_profit_unknown():
    result = guardrails.check_profit_guard(estimated_profit=None, min_net_profit=Decimal("5.0"))
    assert result.passed is False


def test_rate_budget_blocks_when_insufficient_calls_remain():
    result = guardrails.check_rate_budget(calls_remaining=3, calls_needed=10)
    assert result.passed is False


def test_rate_budget_allows_when_sufficient_calls_remain():
    result = guardrails.check_rate_budget(calls_remaining=10, calls_needed=3)
    assert result.passed is True


def test_supplier_stock_holds_when_insufficient():
    result = guardrails.check_supplier_stock(available_quantity=0, requested_quantity=1)
    assert result.passed is False


def test_supplier_stock_allows_when_sufficient():
    result = guardrails.check_supplier_stock(available_quantity=5, requested_quantity=1)
    assert result.passed is True
