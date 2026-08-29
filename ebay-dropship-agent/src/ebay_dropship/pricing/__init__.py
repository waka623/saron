"""AGENT_PROMPTS.md 3章「価格・次アクション判断エージェント」を呼び出すモジュール(Phase 6 で実装)。"""

from decimal import Decimal

from ebay_dropship.approval import Proposal


def evaluate_next_action(listing_id: str) -> Proposal:
    """出品の直近実績から次アクション(price_change/withdraw/hold/none)を提案する。"""
    raise NotImplementedError("Phase 6 で実装")


def calculate_net_profit(price: Decimal, cost: Decimal, fee_pct: Decimal, shipping: Decimal) -> Decimal:
    """純利益 = 価格 − 原価 − eBay手数料 − 送料。金額は Decimal 固定(float禁止)。"""
    raise NotImplementedError("Phase 6 で実装")
