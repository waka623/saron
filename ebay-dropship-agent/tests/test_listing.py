"""出品ドラフト生成(Plan)のゴールデンケース。

数値・判断(proposal_type/estimated_profit/missing_item_specifics等)は完全一致で検証する。
タイトル・説明文などの自由文は完全一致にせず、性質(必須語を含む/禁止表現が無い/納期が正直/
必須item specificsが埋まる)で検証する。
"""

from decimal import Decimal

from ebay_dropship.approval import Priority, ProposalType
from ebay_dropship.listing import generate_draft
from ebay_dropship.listing.models import ListingDraftInput

FEE_PCT = Decimal(13)
FORBIDDEN_WORDS = ("絶対", "100%保証", "業界no.1", "永久保証", "正規品保証")


def _draft_input(**overrides) -> ListingDraftInput:
    defaults = {
        "sku": "X1",
        "product_name": "Acme ワイヤレスマウス",
        "category_id": "12345",
        "target_price": Decimal("29.99"),
        "cost": Decimal("12.00"),
        "shipping_cost": Decimal("3.50"),
        "lead_time_days": 5,
        "required_item_specifics": {"Brand": "Acme", "Color": "Black", "Size": "M"},
        "base_title_keywords": ["Acme", "Wireless", "Mouse", "Black"],
    }
    defaults.update(overrides)
    return ListingDraftInput(**defaults)


def test_publishes_when_specifics_filled_and_copy_is_clean():
    draft_input = _draft_input()

    proposal = generate_draft(draft_input, fee_pct=FEE_PCT)

    # 数値・判断は完全一致(research側と同じ price/cost/shipping/feeなので同じ検算結果 10.5913)
    assert proposal.proposal_type == ProposalType.PUBLISH
    assert proposal.requires_human_approval is True
    assert proposal.estimated_profit == Decimal("10.5913")
    assert proposal.payload["list_price"] == Decimal("29.99")
    assert proposal.payload["handling_time_days"] == 5
    assert proposal.payload["item_specifics"] == draft_input.required_item_specifics

    # 自由文は性質で検証
    title = proposal.payload["title"]
    description = proposal.payload["description"]
    assert "Acme" in title
    assert len(title) <= 80
    assert "5営業日" in description  # 納期がサプライヤー納期どおり正直に記載されている
    for word in FORBIDDEN_WORDS:
        assert word not in title
        assert word not in description


def test_holds_when_required_item_specifics_missing():
    draft_input = _draft_input(required_item_specifics={"Brand": "Acme", "Color": None, "Size": "M"})

    proposal = generate_draft(draft_input, fee_pct=FEE_PCT)

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.priority == Priority.NEEDS_REVIEW
    assert proposal.payload["missing_item_specifics"] == ["Color"]
    assert proposal.payload["title"] is None
    assert proposal.estimated_profit is None


def test_holds_when_generated_copy_contains_forbidden_claim():
    draft_input = _draft_input(base_title_keywords=["Acme", "絶対品質保証"])

    proposal = generate_draft(draft_input, fee_pct=FEE_PCT)

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.priority == Priority.NEEDS_REVIEW
    assert "絶対" in proposal.payload["forbidden_claims"]
