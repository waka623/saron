"""AGENT_PROMPTS.md 3章「価格・次アクション判断エージェント」(Check→Act)。

恒久ルール: 次アクション(price_change/withdraw/hold/none)の判断は決定論的(ルールベース)のみ、
LLMは使わない。

フィードバック安定化ガード(ループを閉じるため必須):
- クールダウン/ヒステリシス: 直近 `pricing_cooldown_days` 日以内に価格変更済みなら再提案しない。
- 最小サンプル: view数が `pricing_min_sample_views` 未満ならactionせずnone(データが薄いうちは動かさない)。
- 重複排除: 既に承認待ちの提案があるなら積み増さない(呼び出し側が `has_pending_proposal` で伝える)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal

from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.config import settings as default_settings
from ebay_dropship.guardrails import check_supplier_data_freshness
from ebay_dropship.pricing.models import ListingSnapshot
from ebay_dropship.supplier import SupplierAdapter

# eBay Account API 導入(将来フェーズ)までの暫定値。research/listing/ordersと同じ既定値。
DEFAULT_EBAY_FEE_PCT = Decimal(13)

# 直近30日の成約率がこれ以上なら「hot」とみなす(それ以外はsold>0なら「normal」、sold=0なら「weak」)。
HOT_SELL_THROUGH_THRESHOLD = Decimal("0.05")


def calculate_net_profit(price: Decimal, cost: Decimal, fee_pct: Decimal, shipping: Decimal) -> Decimal:
    """純利益 = 価格 − 原価 − eBay手数料 − 送料。金額は Decimal 固定(float禁止)。

    fee_pct はパーセント表記の整数/小数(例: 13 は 13%)。research/listing/orders/pricingで共有する。
    """
    fee = price * (fee_pct / Decimal(100))
    return price - cost - fee - shipping


def _guard_floor_price(cost: Decimal, fee_pct: Decimal, shipping: Decimal, min_net_profit: Decimal) -> Decimal:
    """純利益がちょうど min_net_profit になる価格(これを下回ると利益ガードに抵触する下限)。"""
    return (min_net_profit + cost + shipping) / (Decimal(1) - fee_pct / Decimal(100))


def _classify_demand(kpi) -> str:
    if kpi.sold == 0:
        return "weak"
    if kpi.sell_through_rate is not None and kpi.sell_through_rate >= HOT_SELL_THROUGH_THRESHOLD:
        return "hot"
    return "normal"


def _none(listing: ListingSnapshot, current_profit: Decimal, current_margin_pct: Decimal, demand_signal: str, reason: str) -> Proposal:
    return Proposal(
        proposal_type=ProposalType.NONE,
        priority=Priority.LOW,
        summary=f"{listing.listing_id}: 現状維持。",
        rationale=reason,
        risk_level=RiskLevel.LOW,
        estimated_profit=current_profit,
        requires_human_approval=False,
        payload={
            "listing_id": listing.listing_id,
            "current_margin": current_margin_pct,
            "demand_signal": demand_signal,
            "proposed_price": None,
            "action_detail": reason,
        },
    )


def _hold(listing: ListingSnapshot, reason: str) -> Proposal:
    return Proposal(
        proposal_type=ProposalType.HOLD,
        priority=Priority.NEEDS_REVIEW,
        summary=f"{listing.listing_id}: 要確認(価格変更は保留)。",
        rationale=reason,
        risk_level=RiskLevel.MEDIUM,
        estimated_profit=None,
        requires_human_approval=True,
        payload={
            "listing_id": listing.listing_id,
            "current_margin": None,
            "demand_signal": "unknown",
            "proposed_price": None,
            "action_detail": reason,
        },
    )


def _withdraw(listing: ListingSnapshot, current_profit: Decimal, current_margin_pct: Decimal, demand_signal: str) -> Proposal:
    reason = (
        f"純利益{current_profit}(利益率{current_margin_pct:.1f}%)が赤字、かつ需要{demand_signal}で"
        "値下げによる改善余地も無いため取り下げを提案。"
    )
    return Proposal(
        proposal_type=ProposalType.WITHDRAW,
        priority=Priority.HIGH,
        summary=f"{listing.listing_id}: 不採算のため取り下げ提案。",
        rationale=reason,
        risk_level=RiskLevel.MEDIUM,
        estimated_profit=current_profit,
        requires_human_approval=True,
        payload={
            "listing_id": listing.listing_id,
            "current_margin": current_margin_pct,
            "demand_signal": demand_signal,
            "proposed_price": None,
            "action_detail": reason,
        },
    )


def _price_change(
    listing: ListingSnapshot, proposed_price: Decimal, proposed_profit: Decimal, demand_signal: str, *, clamped: bool
) -> Proposal:
    proposed_margin_pct = proposed_profit / proposed_price * Decimal(100)
    detail = (
        f"利益ガードでクランプ(これ以上の値下げは最低純利益を割るため{proposed_price}が下限)。"
        if clamped
        else "相場追随の値下げ。"
    )
    return Proposal(
        proposal_type=ProposalType.PRICE_CHANGE,
        priority=Priority.MEDIUM,
        summary=f"{listing.listing_id}: {proposed_price}へ値下げを提案。",
        rationale=(
            f"直近{listing.kpi.period_days}日 view={listing.kpi.views}/watch={listing.kpi.watches}/"
            f"sold={listing.kpi.sold}で需要{demand_signal}。{proposed_price}なら純利益{proposed_profit}"
            f"(利益率{proposed_margin_pct:.1f}%)。{detail}"
        ),
        risk_level=RiskLevel.LOW,
        estimated_profit=proposed_profit,
        requires_human_approval=True,
        payload={
            "listing_id": listing.listing_id,
            "current_margin": None,
            "demand_signal": demand_signal,
            "proposed_price": proposed_price,
            "action_detail": detail,
        },
    )


def evaluate_next_action(
    listing: ListingSnapshot,
    *,
    settings: Settings = default_settings,
    fee_pct: Decimal = DEFAULT_EBAY_FEE_PCT,
    supplier: SupplierAdapter | None = None,
    now: datetime | None = None,
) -> Proposal:
    """出品1件の直近実績から次アクションを提案する。proposal_type は price_change/withdraw/hold/none のみ。"""
    now = now or datetime.now(UTC)

    current_profit = calculate_net_profit(listing.current_price, listing.cost, fee_pct, listing.shipping_cost)
    current_margin_pct = current_profit / listing.current_price * Decimal(100)

    # 重複排除: 既に承認待ちの提案があれば積み増さない
    if listing.has_pending_proposal:
        return _none(
            listing, current_profit, current_margin_pct, "unknown",
            "既にこの出品への承認待ち提案があるため、重複して提案しない(重複排除)。",
        )

    # クールダウン/ヒステリシス
    if listing.last_price_change_at is not None:
        elapsed = now - listing.last_price_change_at
        if elapsed < timedelta(days=settings.pricing_cooldown_days):
            return _none(
                listing, current_profit, current_margin_pct, "unknown",
                f"直近{settings.pricing_cooldown_days}日以内に価格変更済み(クールダウン中)のため再提案しない。",
            )

    # 在庫消失・データ陳腐化(supplier併用時)
    if supplier is not None and listing.sku is not None:
        try:
            stock = supplier.fetch_stock(listing.sku)
        except KeyError:
            return _hold(listing, "サプライヤーにSKUが見つかりません(在庫消失の可能性)。価格変更は保留。")
        freshness = check_supplier_data_freshness(stock.as_of, settings.supplier_data_max_age_minutes, now)
        if not freshness.passed:
            return _hold(listing, f"サプライヤーデータの陳腐化を検出: {freshness.reason}")

    # 最小サンプル: データが薄いうちはactionしない
    if not listing.kpi.sample_sufficient:
        return _none(
            listing, current_profit, current_margin_pct, "unknown",
            f"直近{listing.kpi.period_days}日のview数({listing.kpi.views})がサンプル不足"
            f"({settings.pricing_min_sample_views}未満)のためaction保留。",
        )

    demand_signal = _classify_demand(listing.kpi)

    # 不採算(現在価格でも赤字)かつ売れていない → 取り下げ
    if current_profit < 0 and listing.kpi.sold == 0:
        return _withdraw(listing, current_profit, current_margin_pct, demand_signal)

    # 需要が弱くない(normal/hot)場合
    if demand_signal != "weak":
        if current_margin_pct >= settings.target_margin_pct:
            return _none(
                listing, current_profit, current_margin_pct, demand_signal,
                f"純利益{current_profit}(利益率{current_margin_pct:.1f}%)で目標達成、"
                f"需要も{demand_signal}のため据え置き。",
            )
        return _none(
            listing, current_profit, current_margin_pct, demand_signal,
            f"純利益{current_profit}(利益率{current_margin_pct:.1f}%)は目標未達だが需要{demand_signal}のため様子見。",
        )

    # 需要が弱い(weak) → 値下げを検討
    naive_price = (
        listing.current_price * (Decimal(100) - settings.pricing_discount_step_pct) / Decimal(100)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    naive_profit = calculate_net_profit(naive_price, listing.cost, fee_pct, listing.shipping_cost)
    if naive_profit >= settings.min_net_profit:
        return _price_change(listing, naive_price, naive_profit, demand_signal, clamped=False)

    floor_price = _guard_floor_price(listing.cost, fee_pct, listing.shipping_cost, settings.min_net_profit)
    if floor_price >= listing.current_price:
        # 値下げ余地が無い(現在価格自体がほぼ下限) → 取り下げを検討
        return _withdraw(listing, current_profit, current_margin_pct, demand_signal)

    clamped_price = floor_price.quantize(Decimal("0.01"), rounding=ROUND_UP)
    clamped_profit = calculate_net_profit(clamped_price, listing.cost, fee_pct, listing.shipping_cost)
    return _price_change(listing, clamped_price, clamped_profit, demand_signal, clamped=True)
