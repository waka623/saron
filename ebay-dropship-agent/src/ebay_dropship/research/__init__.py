"""AGENT_PROMPTS.md 1章「リサーチ判断エージェント」(Plan)。

恒久ルール: 出品候補の可否はここで決定論的(ルールベース)に判断する。LLM には判断させない。
将来 LLM を使う場合も文面生成のみに限定し、その出力は guardrails の検証を経てから提案にする
(このモジュールでは文面生成自体を行わないため該当しない)。
"""

from __future__ import annotations

from decimal import Decimal

from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.config import settings as default_settings
from ebay_dropship.pricing import calculate_net_profit
from ebay_dropship.research.models import MarketSnapshot, SupplierProduct

# eBay Account API 導入(将来フェーズ)までの暫定値。実測手数料率に置き換える。
DEFAULT_EBAY_FEE_PCT = Decimal(13)

HIGH_COMPETITION_THRESHOLD = 30
LOW_COMPETITION_THRESHOLD = 5
HIGH_DEMAND_SALES_THRESHOLD = 15
LOW_DEMAND_SALES_THRESHOLD = 3

_FAVORABLE_DEMAND = frozenset({"medium", "high"})
_FAVORABLE_COMPETITION = frozenset({"low", "medium"})


def _classify_demand(recent_sales_30d: int | None) -> str:
    if recent_sales_30d is None:
        return "unknown"
    if recent_sales_30d >= HIGH_DEMAND_SALES_THRESHOLD:
        return "high"
    if recent_sales_30d >= LOW_DEMAND_SALES_THRESHOLD:
        return "medium"
    return "low"


def _classify_competition(competitor_count: int | None) -> str:
    if competitor_count is None:
        return "unknown"
    if competitor_count >= HIGH_COMPETITION_THRESHOLD:
        return "high"
    if competitor_count <= LOW_COMPETITION_THRESHOLD:
        return "low"
    return "medium"


def _base_payload(
    sku: str, target_price: Decimal | None, demand: str, competition: str, recommended: bool
) -> dict:
    return {
        "sku": sku,
        "target_price": target_price,
        "estimated_demand": demand,
        "competition": competition,
        "recommended": recommended,
    }


def evaluate_candidate(
    product: SupplierProduct,
    market: MarketSnapshot,
    *,
    settings: Settings = default_settings,
    fee_pct: Decimal = DEFAULT_EBAY_FEE_PCT,
) -> Proposal:
    """1つのサプライヤー商品を出品候補にすべきか判断する。proposal_type は none/hold のみ(実行を伴わない)。"""

    if product.category in settings.excluded_categories_list:
        return Proposal(
            proposal_type=ProposalType.HOLD,
            priority=Priority.NEEDS_REVIEW,
            summary=f"{product.sku}: 除外カテゴリ('{product.category}')のため候補外。",
            rationale=(
                f"カテゴリ '{product.category}' は除外カテゴリ設定(compliance.md 第2章)に含まれるため、"
                "出品候補にせず要確認とする。"
            ),
            risk_level=RiskLevel.HIGH,
            estimated_profit=None,
            requires_human_approval=True,
            payload=_base_payload(product.sku, None, "unknown", "unknown", False),
        )

    if market.median_price is None:
        return Proposal(
            proposal_type=ProposalType.HOLD,
            priority=Priority.NEEDS_REVIEW,
            summary=f"{product.sku}: 相場データが取得できず判断不能。",
            rationale="相場中央値が取得できなかった。推測せず要確認とする(deny by default)。",
            risk_level=RiskLevel.LOW,
            estimated_profit=None,
            requires_human_approval=True,
            payload=_base_payload(product.sku, None, "unknown", "unknown", False),
        )

    target_price = market.median_price
    net_profit = calculate_net_profit(target_price, product.cost, fee_pct, market.shipping_cost)
    margin_pct = (net_profit / target_price * Decimal(100)) if target_price else Decimal(0)

    demand = _classify_demand(market.recent_sales_30d)
    competition = _classify_competition(market.competitor_count)

    if net_profit < settings.min_net_profit or margin_pct < settings.target_margin_pct:
        return Proposal(
            proposal_type=ProposalType.NONE,
            priority=Priority.LOW,
            summary=f"{product.sku}: 目標利益に届かないため候補外。",
            rationale=(
                f"想定価格{target_price}・原価{product.cost}・手数料{fee_pct}%・送料{market.shipping_cost}で"
                f"純利益{net_profit}(利益率{margin_pct:.1f}%)。"
                f"最低純利益{settings.min_net_profit}または目標利益率{settings.target_margin_pct}%を満たさない。"
            ),
            risk_level=RiskLevel.LOW,
            estimated_profit=net_profit,
            requires_human_approval=False,
            payload=_base_payload(product.sku, target_price, demand, competition, False),
        )

    if demand not in _FAVORABLE_DEMAND or competition not in _FAVORABLE_COMPETITION:
        return Proposal(
            proposal_type=ProposalType.NONE,
            priority=Priority.LOW,
            summary=f"{product.sku}: 需要・競合の条件を満たさないため候補外。",
            rationale=(
                f"純利益{net_profit}(利益率{margin_pct:.1f}%)は目標を満たすが、"
                f"需要={demand}・競合={competition}のため見送り。"
            ),
            risk_level=RiskLevel.LOW,
            estimated_profit=net_profit,
            requires_human_approval=False,
            payload=_base_payload(product.sku, target_price, demand, competition, False),
        )

    return Proposal(
        proposal_type=ProposalType.HOLD,
        priority=Priority.MEDIUM,
        summary=f"{product.sku}: 出品候補として次段(listing)へ。",
        rationale=(
            f"想定価格{target_price}で純利益{net_profit}(利益率{margin_pct:.1f}%)。"
            f"需要={demand}・競合={competition}で目標を満たすため出品候補に採用。"
        ),
        risk_level=RiskLevel.LOW,
        estimated_profit=net_profit,
        requires_human_approval=False,
        payload=_base_payload(product.sku, target_price, demand, competition, True),
    )
