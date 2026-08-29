"""AGENT_PROMPTS.md 2章「出品ドラフト生成エージェント」を呼び出すモジュール(Phase 3 で実装)。"""

from ebay_dropship.approval import Proposal


def generate_draft(sku: str) -> Proposal:
    """採用商品の出品ドラフトを生成し、Proposal(publish/hold)を返す。"""
    raise NotImplementedError("Phase 3 で実装")
