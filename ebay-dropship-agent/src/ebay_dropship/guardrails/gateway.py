"""外部副作用(出品公開・価格変更・取り下げ・発注)を実行する唯一の入口。

Phase 4 以降で eBay Sell API への実書き込み(EbayClient.create_offer 等)や
サプライヤーへの発注を実装する際は、必ずこの `execute_side_effect` を経由すること。
guardrails を通らずに `executor` を呼び出す経路を他に作らない
(`tests/test_guardrail_gateway.py::test_ebay_write_methods_are_only_called_through_guardrail_gateway` で機械的に検査する)。
"""

from __future__ import annotations

from collections.abc import Callable

from ebay_dropship.approval import Proposal, ProposalStatus, ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.guardrails import (
    ComplianceError,
    GuardrailResult,
    check_not_retail_arbitrage,
    check_profit_guard,
    check_publish_payload_complete,
    check_rate_budget,
    check_requires_human_approval,
    check_supplier_stock,
)

PROFIT_GATED_TYPES = frozenset({ProposalType.PRICE_CHANGE, ProposalType.PURCHASE})


class GuardrailDenied(ComplianceError):
    def __init__(self, results: list[GuardrailResult]):
        self.results = [r for r in results if not r.passed]
        reasons = "; ".join(r.reason for r in self.results)
        super().__init__(reasons or "guardrails denied")


def execute_side_effect(
    proposal: Proposal,
    executor: Callable[[Proposal], None],
    *,
    settings: Settings,
    calls_remaining: int,
    calls_needed: int = 1,
    available_quantity: int | None = None,
    requested_quantity: int | None = None,
    source_description: str = "",
) -> Proposal:
    """proposal を承認済みかつ全guardrailを満たした場合にのみ executor(proposal) を呼ぶ。

    deny by default: いずれかの guardrail が deny、または判定に必要な情報が欠けている場合は
    GuardrailDenied を送出し、executor は一切呼ばれない。
    """
    if proposal.status != ProposalStatus.APPROVED:
        raise ComplianceError(
            f"承認されていない提案(status={proposal.status})は実行できません。承認ワークフローを経由してください。"
        )

    results: list[GuardrailResult] = []

    if check_requires_human_approval(proposal.proposal_type) and not proposal.requires_human_approval:
        results.append(
            GuardrailResult.deny(
                "requires_human_approval=False の書き込み系提案は実行できません(データ不整合のため deny)。"
            )
        )

    results.append(check_not_retail_arbitrage(source_description or proposal.rationale))
    results.append(check_rate_budget(calls_remaining, calls_needed))

    if proposal.proposal_type in PROFIT_GATED_TYPES:
        results.append(check_profit_guard(proposal.estimated_profit, settings.min_net_profit))

    if proposal.proposal_type is ProposalType.PUBLISH:
        results.append(check_publish_payload_complete(proposal.payload))

    if proposal.proposal_type is ProposalType.PURCHASE:
        if available_quantity is None or requested_quantity is None:
            results.append(GuardrailResult.deny("発注には在庫確認用の数量情報が必須です(不足のため deny)。"))
        else:
            results.append(check_supplier_stock(available_quantity, requested_quantity))

    failed = [r for r in results if not r.passed]
    if failed:
        raise GuardrailDenied(failed)

    executor(proposal)
    return proposal
