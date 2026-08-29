"""AGENT_PROMPTS.md 2章「出品ドラフト生成エージェント」(Plan)。

恒久ルール: publishしてよいか・価格・holdなどの判断は決定論的(ルールベース)に行い、LLMには判断させない。
文面(タイトル・説明文)は ListingCopyGenerator インターフェース越しに生成し、将来 LLM 実装へ差し替え可能にする。
生成された文面がどちらの実装から来ても、公開前に必ず禁止表現チェック(本モジュール)を通す。
"""

from __future__ import annotations

from decimal import Decimal

from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.listing.copy_generator import ListingCopyGenerator, TemplateListingCopyGenerator
from ebay_dropship.listing.models import ListingDraftInput
from ebay_dropship.pricing import calculate_net_profit

DEFAULT_EBAY_FEE_PCT = Decimal(13)

# 誇大・断定的な表現の例。marketplace規約で問題になりやすい語をここに追加していく(compliance.md 第2章)。
FORBIDDEN_CLAIM_WORDS: tuple[str, ...] = (
    "絶対",
    "100%保証",
    "業界no.1",
    "永久保証",
    "正規品保証",
)


def _forbidden_claims(text: str) -> list[str]:
    lowered = text.lower()
    return [word for word in FORBIDDEN_CLAIM_WORDS if word.lower() in lowered]


def generate_draft(
    draft_input: ListingDraftInput,
    *,
    copy_generator: ListingCopyGenerator | None = None,
    fee_pct: Decimal = DEFAULT_EBAY_FEE_PCT,
) -> Proposal:
    generator = copy_generator or TemplateListingCopyGenerator()

    missing = [key for key, value in draft_input.required_item_specifics.items() if not value]
    if missing:
        return Proposal(
            proposal_type=ProposalType.HOLD,
            priority=Priority.NEEDS_REVIEW,
            summary=f"{draft_input.sku}: 必須item specificsが不足のため要確認。",
            rationale=f"必須のitem specificsが未入力: {missing}。埋まるまで出品ドラフトを確定できない。",
            risk_level=RiskLevel.MEDIUM,
            estimated_profit=None,
            requires_human_approval=True,
            payload={
                "sku": draft_input.sku,
                "title": None,
                "category_id": draft_input.category_id,
                "item_specifics": draft_input.required_item_specifics,
                "description": None,
                "list_price": None,
                "handling_time_days": draft_input.lead_time_days,
                "missing_item_specifics": missing,
            },
        )

    copy = generator.generate(draft_input)
    violations = _forbidden_claims(copy.title) + _forbidden_claims(copy.description)
    if violations:
        return Proposal(
            proposal_type=ProposalType.HOLD,
            priority=Priority.NEEDS_REVIEW,
            summary=f"{draft_input.sku}: 生成文に禁止表現を検出したため要確認。",
            rationale=f"誇大・断定表現を検出: {violations}。文面を修正するまで publish しない。",
            risk_level=RiskLevel.MEDIUM,
            estimated_profit=None,
            requires_human_approval=True,
            payload={
                "sku": draft_input.sku,
                "title": copy.title,
                "category_id": draft_input.category_id,
                "item_specifics": draft_input.required_item_specifics,
                "description": copy.description,
                "list_price": None,
                "handling_time_days": draft_input.lead_time_days,
                "forbidden_claims": violations,
            },
        )

    net_profit = calculate_net_profit(
        draft_input.target_price, draft_input.cost, fee_pct, draft_input.shipping_cost
    )

    return Proposal(
        proposal_type=ProposalType.PUBLISH,
        priority=Priority.MEDIUM,
        summary=f"{draft_input.sku}: 出品ドラフトを作成(想定価格{draft_input.target_price})。",
        rationale=(
            f"想定価格{draft_input.target_price}・原価{draft_input.cost}・手数料{fee_pct}%・"
            f"送料{draft_input.shipping_cost}で純利益{net_profit}。"
            "必須item specifics充足・禁止表現なしを確認済み。"
        ),
        risk_level=RiskLevel.LOW,
        estimated_profit=net_profit,
        requires_human_approval=True,
        payload={
            "sku": draft_input.sku,
            "title": copy.title,
            "category_id": draft_input.category_id,
            "item_specifics": draft_input.required_item_specifics,
            "description": copy.description,
            "list_price": draft_input.target_price,
            "handling_time_days": draft_input.lead_time_days,
        },
    )
