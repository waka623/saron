"""AGENT_PROMPTS.md 4章「受注処理判断エージェント」を呼び出すモジュール(Phase 5 で実装)。"""

from ebay_dropship.approval import Proposal


def evaluate_purchase(order_id: str) -> Proposal:
    """新規受注をサプライヤーへ発注してよいか判断し、Proposal(purchase/hold)を返す。"""
    raise NotImplementedError("Phase 5 で実装")
