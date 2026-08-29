"""AGENT_PROMPTS.md 1章「リサーチ判断エージェント」を呼び出すモジュール(Phase 3 で実装)。"""

from ebay_dropship.approval import Proposal


def evaluate_candidate(sku: str) -> Proposal:
    """サプライヤー商品1件を出品候補にすべきか判断し、Proposal(none/hold)を返す。"""
    raise NotImplementedError("Phase 3 で実装")
