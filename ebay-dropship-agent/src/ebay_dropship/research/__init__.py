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


# --- S2: Shopify向け利益ガード(自己設定価格版)。DECISIONS.md参照 ---
#
# eBay版のevaluate_candidate(上記)は一切変更していない。Shopifyには市場相場を取得できる
# 公式APIが無いため、需要・競合の自動判定は行わず、利益ガード(目標利益率・最低純利益)のみで
# 出品候補の可否を判断する簡素化版として別関数にした。

# Shopify Payments標準レート(要確認: プラン・カード種別・地域により変動しうる。実際の契約内容で
# 確認して調整すること。ここでは一般的なオンライン決済手数料の目安を暫定値として置いている)。
SHOPIFY_PAYMENT_FEE_PCT = Decimal("2.9")
SHOPIFY_PAYMENT_FIXED_FEE = Decimal("0.30")


def calculate_shopify_net_profit(
    price: Decimal,
    cost: Decimal,
    shipping: Decimal,
    fee_pct: Decimal = SHOPIFY_PAYMENT_FEE_PCT,
    fixed_fee: Decimal = SHOPIFY_PAYMENT_FIXED_FEE,
) -> Decimal:
    """純利益 = 価格 − 原価(POD) − 送料 − 決済手数料(定率+固定)。

    eBay版`pricing.calculate_net_profit`と違い、Shopify決済は定率に加えて定額手数料が乗る。
    """
    fee = price * (fee_pct / Decimal(100)) + fixed_fee
    return price - cost - shipping - fee


def evaluate_shopify_listing_candidate(
    product: SupplierProduct,
    self_set_price: Decimal,
    shipping_cost: Decimal,
    *,
    settings: Settings = default_settings,
) -> Proposal:
    """Shopify向け出品候補判断(Plan)。市場相場が無いため自己設定価格をそのまま使い、

    需要・競合の自動判定は行わない(DECISIONS.mdの簡素化方針)。利益ガード(目標利益率・
    最低純利益)のみで可否を判断する。proposal_type は hold(候補採用)/none(利益ガード未達)のみ
    (需要・競合による絞り込みが無いため、eBay版のような「利益は十分だが見送り」のnoneは無い)。
    """
    if product.category in settings.excluded_categories_list:
        return Proposal(
            proposal_type=ProposalType.HOLD,
            priority=Priority.NEEDS_REVIEW,
            summary=f"{product.sku}: 除外カテゴリ('{product.category}')のため候補外。",
            rationale=(
                f"カテゴリ '{product.category}' は除外カテゴリ設定(compliance.md 第2章)に"
                "含まれるため、出品候補にせず要確認とする。"
            ),
            risk_level=RiskLevel.HIGH,
            estimated_profit=None,
            requires_human_approval=True,
            payload={"sku": product.sku, "self_set_price": None, "recommended": False},
        )

    net_profit = calculate_shopify_net_profit(self_set_price, product.cost, shipping_cost)
    margin_pct = (net_profit / self_set_price * Decimal(100)) if self_set_price else Decimal(0)

    if net_profit < settings.min_net_profit or margin_pct < settings.target_margin_pct:
        return Proposal(
            proposal_type=ProposalType.NONE,
            priority=Priority.LOW,
            summary=f"{product.sku}: 目標利益に届かないため候補外。",
            rationale=(
                f"自己設定価格{self_set_price}・原価{product.cost}・送料{shipping_cost}・"
                f"Shopify決済手数料{SHOPIFY_PAYMENT_FEE_PCT}%+${SHOPIFY_PAYMENT_FIXED_FEE}で"
                f"純利益{net_profit}(利益率{margin_pct:.1f}%)。"
                f"最低純利益{settings.min_net_profit}または目標利益率{settings.target_margin_pct}%を満たさない。"
            ),
            risk_level=RiskLevel.LOW,
            estimated_profit=net_profit,
            requires_human_approval=False,
            payload={"sku": product.sku, "self_set_price": self_set_price, "recommended": False},
        )

    return Proposal(
        proposal_type=ProposalType.HOLD,
        priority=Priority.MEDIUM,
        summary=f"{product.sku}: 出品候補として次段(listing)へ。",
        rationale=(
            f"自己設定価格{self_set_price}で純利益{net_profit}(利益率{margin_pct:.1f}%)。"
            "需要・競合の自動判定は行わない(Shopify簡素化方針)ため、利益ガード通過のみで候補採用。"
        ),
        risk_level=RiskLevel.LOW,
        estimated_profit=net_profit,
        requires_human_approval=False,
        payload={"sku": product.sku, "self_set_price": self_set_price, "recommended": True},
    )
