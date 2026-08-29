"""guardrailsの境界値のテスト欠落を埋める(adversarial security reviewで指摘)。

いずれの関数も、境界値ちょうど・1単位差での挙動は手動検証済みでoff-by-oneの不具合は
無いことを確認しているが、既存テストは「明らかに上/明らかに下」の値しか使っておらず、
閾値ちょうど・1単位差の境界そのものを固定するテストが無かった(「テスト欠落」として指摘)。
このファイルはそれを埋めるものであり、いずれのテストも既存の実装を変更せず green になる。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ebay_dropship import guardrails

# --- 利益ガード: ちょうど目標(min_net_profit)/1セント下(下限直下)/1セント上 ---


def test_profit_guard_exactly_at_target_allows():
    """ちょうど目標(min_net_profit)と同額なら通す(境界は含む側、'下回る'にはあたらない)。"""
    result = guardrails.check_profit_guard(Decimal("5.00"), Decimal("5.00"))
    assert result.passed is True


def test_profit_guard_one_cent_below_target_denies():
    """下限直下・1セント下: 最低純利益をわずか1セントでも割り込めばdeny。"""
    result = guardrails.check_profit_guard(Decimal("4.99"), Decimal("5.00"))
    assert result.passed is False


def test_profit_guard_one_cent_above_target_allows():
    """対称性の確認: 1セント上回っていれば当然通す(境界の向きが逆転していないこと)。"""
    result = guardrails.check_profit_guard(Decimal("5.01"), Decimal("5.00"))
    assert result.passed is True


# --- レート予算: 残数==必要数(ちょうど) / 1不足 ---


def test_rate_budget_exactly_sufficient_allows():
    result = guardrails.check_rate_budget(calls_remaining=3, calls_needed=3)
    assert result.passed is True


def test_rate_budget_one_short_denies():
    result = guardrails.check_rate_budget(calls_remaining=2, calls_needed=3)
    assert result.passed is False


# --- サプライヤー在庫: 在庫==要求数(ちょうど) / 1不足 ---


def test_supplier_stock_exactly_sufficient_allows():
    result = guardrails.check_supplier_stock(available_quantity=1, requested_quantity=1)
    assert result.passed is True


def test_supplier_stock_one_short_denies():
    result = guardrails.check_supplier_stock(available_quantity=0, requested_quantity=1)
    assert result.passed is False


# --- サプライヤーデータ鮮度: 経過時間==許容時間ちょうど / 1秒超過 ---


def test_supplier_data_freshness_exactly_at_max_age_allows():
    now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
    as_of = now - timedelta(minutes=30)
    result = guardrails.check_supplier_data_freshness(as_of, max_age_minutes=30, now=now)
    assert result.passed is True


def test_supplier_data_freshness_one_second_over_denies():
    now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
    as_of = now - timedelta(minutes=30, seconds=1)
    result = guardrails.check_supplier_data_freshness(as_of, max_age_minutes=30, now=now)
    assert result.passed is False
