"""価格・次アクション判断(Act)のゴールデンケース。

AGENT_PROMPTS.md 3章の出力例(listing_id=A123, price=$40, cost=$22, fee=13%, shipping=$6,
view=210/watch=4/sold=0, 目標利益率20%)を採用する前に、記載の数値を再計算して検証した。

検算結果(price=$38, fee_pct=13%, shipping=$6 のとき):
  fee = 38 * 0.13 = 4.94
  net_profit = 38 - 22 - 4.94 - 6 = 5.06 (元記述の $4.66 とは一致しない)
検算結果($36 案): net_profit = 36-22-4.68-6 = 3.32 (元記述と一致・利益ガード割れ)
検算結果(利益ガード下限価格 floor = (5+22+6)/(1-0.13) = 37.931...):
  ROUND_UPで$37.94に切り上げ → net_profit = 37.94-22-4.9322-6 = 5.0078

元の例の $38/$4.66/12% は fee_pct=13%・shipping=$6 の前提で再計算すると数値が合わなかったため、
そのまま採用せず、再計算した $37.94(クランプ後価格)を正としてゴールデンに固定した
(DECISIONS.md Phase 6 節に記録)。$36 を試して利益ガードで却下・より浅い値下げにクランプする、
という判断ロジックの構造は元の例と同じ。

数値・判断(proposal_type/proposed_price/estimated_profit)は完全一致、自由文(rationale/action_detail)
は性質検証にとどめる。
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ebay_dropship.analytics import KpiSummary
from ebay_dropship.approval import ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.pricing import evaluate_next_action
from ebay_dropship.pricing.models import ListingSnapshot
from ebay_dropship.supplier import SupplierStock
from tests.fakes.supplier_fake import FakeSupplierAdapter

SETTINGS = Settings(min_net_profit=Decimal("5.0"))  # target_margin_pct=20(既定)
FEE_PCT = Decimal(13)
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


def _kpi(**overrides) -> KpiSummary:
    defaults = {
        "listing_id": "A123",
        "period_days": 30,
        "impressions": 1000,
        "views": 210,
        "watches": 4,
        "sold": 0,
        "returns": 0,
        "sell_through_rate": Decimal(0),
        "watch_rate": Decimal(4) / Decimal(210),
        "return_rate": None,
        "sample_sufficient": True,
        "has_return_rate_divergence": False,
    }
    defaults.update(overrides)
    return KpiSummary(**defaults)


def _listing(**overrides) -> ListingSnapshot:
    defaults = {
        "listing_id": "A123",
        "current_price": Decimal("40.00"),
        "cost": Decimal("22.00"),
        "shipping_cost": Decimal("6.00"),
        "kpi": _kpi(),
    }
    defaults.update(overrides)
    return ListingSnapshot(**defaults)


# --- price_change(利益ガードによるクランプ。AGENT_PROMPTS.md例を再計算のうえ採用) ---


def test_price_change_clamped_to_profit_guard_floor():
    proposal = evaluate_next_action(_listing(), settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.PRICE_CHANGE
    assert proposal.requires_human_approval is True
    assert proposal.payload["proposed_price"] == Decimal("37.94")
    assert proposal.estimated_profit == Decimal("5.0078")
    assert proposal.payload["demand_signal"] == "weak"
    # 自由文は性質のみ検証(完全一致にしない)
    assert "クランプ" in proposal.rationale or "クランプ" in proposal.payload["action_detail"]


# --- price_change(クランプ不要。ナイーブな一段階値下げがそのまま利益ガードを満たす) ---


def test_price_change_without_clamping_when_naive_discount_clears_guard():
    listing = _listing(
        current_price=Decimal("50.00"), cost=Decimal("20.00"), shipping_cost=Decimal("5.00")
    )

    proposal = evaluate_next_action(listing, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.PRICE_CHANGE
    assert proposal.payload["proposed_price"] == Decimal("45.00")
    assert proposal.estimated_profit == Decimal("14.15")
    assert "クランプ" not in proposal.payload["action_detail"]


# --- withdraw(不採算・値下げ余地も無い) ---


def test_withdraw_when_currently_unprofitable_and_not_selling():
    listing = _listing(current_price=Decimal("25.00"))  # cost=22, shipping=6, fee=13% → 赤字

    proposal = evaluate_next_action(listing, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.WITHDRAW
    assert proposal.estimated_profit == Decimal("-6.25")
    assert proposal.requires_human_approval is True


# --- hold(在庫消失・データ陳腐化。supplier併用) ---


def test_holds_when_supplier_sku_not_found():
    supplier = FakeSupplierAdapter({})
    listing = _listing(sku="X1")

    proposal = evaluate_next_action(listing, settings=SETTINGS, fee_pct=FEE_PCT, supplier=supplier, now=NOW)

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.requires_human_approval is True


def test_holds_when_supplier_data_stale():
    stale_settings = Settings(min_net_profit=Decimal("5.0"), supplier_data_max_age_minutes=60)
    supplier = FakeSupplierAdapter(
        {"X1": SupplierStock(sku="X1", cost=Decimal("22.00"), quantity=10, lead_time_days=3, as_of=NOW - timedelta(hours=3))}
    )
    listing = _listing(sku="X1")

    proposal = evaluate_next_action(listing, settings=stale_settings, fee_pct=FEE_PCT, supplier=supplier, now=NOW)

    assert proposal.proposal_type == ProposalType.HOLD


# --- none(据え置き): margin達成+需要正常 ---


def test_none_when_margin_meets_target_and_demand_is_not_weak():
    kpi = _kpi(sold=5, sell_through_rate=Decimal(5) / Decimal(200), views=200)
    listing = _listing(current_price=Decimal("40.00"), cost=Decimal("18.00"), shipping_cost=Decimal("4.00"), kpi=kpi)

    proposal = evaluate_next_action(listing, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.NONE
    assert proposal.payload["proposed_price"] is None


# --- none: 最小サンプル未達 ---


def test_none_when_sample_insufficient():
    kpi = _kpi(views=5, sample_sufficient=False)
    listing = _listing(kpi=kpi)

    proposal = evaluate_next_action(listing, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.NONE
    assert "サンプル不足" in proposal.rationale


# --- none: クールダウン中(直近変更済み) ---


def test_none_when_within_cooldown_period():
    listing = _listing(last_price_change_at=NOW - timedelta(days=2))  # cooldown=7日以内

    proposal = evaluate_next_action(listing, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.NONE
    assert "クールダウン" in proposal.rationale


def test_price_change_proposed_after_cooldown_period_elapsed():
    """クールダウン期間を過ぎていれば通常どおり判断する(境界の反対側も確認)。"""
    listing = _listing(last_price_change_at=NOW - timedelta(days=8))

    proposal = evaluate_next_action(listing, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.PRICE_CHANGE


# --- none: 重複排除(既に承認待ちの提案がある) ---


def test_none_when_pending_proposal_already_exists():
    listing = _listing(has_pending_proposal=True)

    proposal = evaluate_next_action(listing, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.NONE
    assert "重複" in proposal.rationale
