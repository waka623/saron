"""S2: `research.py::evaluate_shopify_listing_candidate`(Shopify向け利益ガード、自己設定価格版)。

既存の`evaluate_candidate`(eBay向け、市場相場ベース)のテストとは独立(あちらは無変更)。
需要・競合の自動判定は行わない(Shopifyにはそれを取得する公式APIが無いため)。
"""

from __future__ import annotations

from decimal import Decimal

from ebay_dropship.approval import ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.research import calculate_shopify_net_profit, evaluate_shopify_listing_candidate
from ebay_dropship.research.models import SupplierProduct

SETTINGS = Settings()  # target_margin_pct=15 / min_net_profit=5(既定)


def _product(**overrides) -> SupplierProduct:
    defaults = {"sku": "MUG-1", "cost": Decimal("10.00"), "stock": 999, "lead_time_days": 3, "category": "home_goods"}
    defaults.update(overrides)
    return SupplierProduct(**defaults)


def test_calculate_shopify_net_profit_includes_percentage_and_fixed_fee():
    # price=25, cost=10, shipping=3, fee=2.9%*25+0.30=1.025
    net_profit = calculate_shopify_net_profit(Decimal("25.00"), Decimal("10.00"), Decimal("3.00"))

    assert net_profit == Decimal("10.975")


def test_recommends_when_profit_guard_is_satisfied():
    # price=30, cost=10, shipping=3 -> fee=2.9%*30+0.30=1.17, net=30-10-3-1.17=15.83, margin=52.8%
    proposal = evaluate_shopify_listing_candidate(
        _product(), self_set_price=Decimal("30.00"), shipping_cost=Decimal("3.00"), settings=SETTINGS
    )

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.payload["recommended"] is True
    assert proposal.requires_human_approval is False


def test_rejects_when_margin_below_target():
    # price=12, cost=10, shipping=0.5 -> fee=2.9%*12+0.30=0.648, net=12-10-0.5-0.648=0.852 (<$5)
    proposal = evaluate_shopify_listing_candidate(
        _product(), self_set_price=Decimal("12.00"), shipping_cost=Decimal("0.50"), settings=SETTINGS
    )

    assert proposal.proposal_type == ProposalType.NONE
    assert proposal.payload["recommended"] is False


def test_holds_for_excluded_category():
    product = _product(category="hazmat")

    proposal = evaluate_shopify_listing_candidate(
        product, self_set_price=Decimal("30.00"), shipping_cost=Decimal("3.00"), settings=SETTINGS
    )

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.requires_human_approval is True
    assert proposal.payload["recommended"] is False


def test_does_not_use_demand_or_competition_fields():
    """Shopify版はSupplierProductにdemand/competition情報を含めなくても判断できる(簡素化方針)。"""
    proposal = evaluate_shopify_listing_candidate(
        _product(), self_set_price=Decimal("30.00"), shipping_cost=Decimal("3.00"), settings=SETTINGS
    )

    assert "estimated_demand" not in proposal.payload
    assert "competition" not in proposal.payload
