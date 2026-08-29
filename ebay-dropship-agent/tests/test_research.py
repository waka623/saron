"""リサーチ判断(Plan)のゴールデンケース。

数値(純利益)・判断(proposal_type/recommended)は事前に手計算で検算済みの値と完全一致させる。
検算(fee_pct=13%, cost=12.00, shipping=3.50, price=29.99の場合):
  fee = 29.99 * 0.13 = 3.8987
  net_profit = 29.99 - 12.00 - 3.8987 - 3.50 = 10.5913
自由文(rationale)は完全一致にせず、必要な情報を含むことのみ確認する。
"""

from decimal import Decimal

from ebay_dropship.approval import Priority, ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.research import evaluate_candidate
from ebay_dropship.research.models import MarketSnapshot, SupplierProduct

SETTINGS = Settings()  # target_margin_pct=20 / min_net_profit=5(ユーザー確定値)
FEE_PCT = Decimal(13)


def _product(**overrides) -> SupplierProduct:
    defaults = {
        "sku": "X1",
        "cost": Decimal("12.00"),
        "stock": 50,
        "lead_time_days": 5,
        "category": "home_goods",
    }
    defaults.update(overrides)
    return SupplierProduct(**defaults)


def _market(**overrides) -> MarketSnapshot:
    defaults = {
        "median_price": Decimal("29.99"),
        "competitor_count": 8,
        "recent_sales_30d": 20,
        "shipping_cost": Decimal("3.50"),
    }
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


def test_recommends_when_profit_demand_and_competition_are_favorable():
    proposal = evaluate_candidate(_product(), _market(), settings=SETTINGS, fee_pct=FEE_PCT)

    assert proposal.proposal_type == ProposalType.HOLD  # 実行は伴わない。候補は次段(listing)へ
    assert proposal.estimated_profit == Decimal("10.5913")
    assert proposal.payload["recommended"] is True
    assert proposal.payload["estimated_demand"] == "high"
    assert proposal.payload["competition"] == "medium"
    assert proposal.requires_human_approval is False


def test_rejects_when_cost_too_high_even_at_market_price():
    """目標割れ原価: 相場価格で売っても利益ガードを満たせないケース。"""
    product = _product(cost=Decimal("28.00"))

    proposal = evaluate_candidate(product, _market(), settings=SETTINGS, fee_pct=FEE_PCT)

    assert proposal.proposal_type == ProposalType.NONE
    assert proposal.estimated_profit == Decimal("-5.4087")
    assert proposal.payload["recommended"] is False


def test_holds_when_market_data_missing():
    """相場データ無し: 推測せず要確認に倒す(deny by default)。"""
    market = MarketSnapshot(
        median_price=None, competitor_count=None, recent_sales_30d=None, shipping_cost=Decimal("3.50")
    )

    proposal = evaluate_candidate(_product(), market, settings=SETTINGS, fee_pct=FEE_PCT)

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.priority == Priority.NEEDS_REVIEW
    assert proposal.estimated_profit is None
    assert proposal.payload["recommended"] is False


def test_rejects_when_demand_is_weak_despite_sufficient_profit():
    """需要薄い: 利益は十分でも直近の売れ行きが弱ければ見送り。"""
    market = _market(recent_sales_30d=1, competitor_count=5)

    proposal = evaluate_candidate(_product(), market, settings=SETTINGS, fee_pct=FEE_PCT)

    assert proposal.proposal_type == ProposalType.NONE
    assert proposal.payload["recommended"] is False
    assert proposal.payload["estimated_demand"] == "low"
    assert proposal.estimated_profit == Decimal("10.5913")


def test_rejects_when_competition_is_excessive_despite_sufficient_profit():
    """競合過多: 利益・需要は十分でも出品数が多すぎれば見送り。"""
    market = _market(competitor_count=40)

    proposal = evaluate_candidate(_product(), market, settings=SETTINGS, fee_pct=FEE_PCT)

    assert proposal.proposal_type == ProposalType.NONE
    assert proposal.payload["recommended"] is False
    assert proposal.payload["competition"] == "high"


def test_holds_for_excluded_category():
    product = _product(category="hazmat")  # settings.excluded_categories_list に含まれる

    proposal = evaluate_candidate(product, _market(), settings=SETTINGS, fee_pct=FEE_PCT)

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.priority == Priority.NEEDS_REVIEW
    assert proposal.payload["recommended"] is False
    assert proposal.requires_human_approval is True
