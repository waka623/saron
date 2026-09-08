"""S2: `orders.py::evaluate_supplier_purchase`(Shopify注文→PODサプライヤー発注の判断)のテスト。

既存の`evaluate_purchase`(eBay/CSVサプライヤー向け)のテストとは独立(あちらは無変更)。
"""

from __future__ import annotations

from decimal import Decimal

from ebay_dropship.approval import ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.orders import evaluate_supplier_purchase
from ebay_dropship.pod import SupplierPurchaseLineItem

SETTINGS = Settings(max_supplier_order_cost=Decimal("50.00"))

VALID_ADDRESS = {
    "ship_to_name": "Jane Doe",
    "ship_to_address1": "123 Main St",
    "ship_to_city": "Springfield",
    "ship_to_region": "IL",
    "ship_to_country": "US",
    "ship_to_zip": "62701",
}


def _item(**overrides) -> SupplierPurchaseLineItem:
    defaults = {"sku": "MUG-1", "quantity": 1, "unit_cost": Decimal("12.50")}
    defaults.update(overrides)
    return SupplierPurchaseLineItem(**defaults)


def test_recommends_supplier_purchase_when_cost_within_limit_and_address_complete():
    proposal = evaluate_supplier_purchase("shop-order-1", _item(), VALID_ADDRESS, settings=SETTINGS)

    assert proposal.proposal_type == ProposalType.SUPPLIER_PURCHASE
    assert proposal.requires_human_approval is True
    assert proposal.payload["total_cost"] == Decimal("12.50")
    assert proposal.payload["shipping_address"] == VALID_ADDRESS


def test_holds_when_shipping_address_missing():
    proposal = evaluate_supplier_purchase("shop-order-1", _item(), None, settings=SETTINGS)

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.requires_human_approval is True
    assert "配送先情報" in proposal.rationale


def test_holds_when_shipping_address_incomplete():
    incomplete = {**VALID_ADDRESS, "ship_to_zip": ""}

    proposal = evaluate_supplier_purchase("shop-order-1", _item(), incomplete, settings=SETTINGS)

    assert proposal.proposal_type == ProposalType.HOLD
    assert "ship_to_zip" in proposal.rationale


def test_holds_when_total_cost_exceeds_max_supplier_order_cost():
    """deny-by-default: 原価上限超過は自動発注しない。"""
    expensive_item = _item(unit_cost=Decimal("30.00"), quantity=2)  # total=60.00 > 上限50.00

    proposal = evaluate_supplier_purchase("shop-order-1", expensive_item, VALID_ADDRESS, settings=SETTINGS)

    assert proposal.proposal_type == ProposalType.HOLD
    assert "上限" in proposal.rationale


def test_recommends_exactly_at_cost_limit():
    """境界値: ちょうど上限と同額なら通す(超過にはあたらない)。"""
    exact_item = _item(unit_cost=Decimal("25.00"), quantity=2)  # total=50.00 == 上限

    proposal = evaluate_supplier_purchase("shop-order-1", exact_item, VALID_ADDRESS, settings=SETTINGS)

    assert proposal.proposal_type == ProposalType.SUPPLIER_PURCHASE


def test_holds_one_cent_over_cost_limit():
    over_item = _item(unit_cost=Decimal("50.01"), quantity=1)

    proposal = evaluate_supplier_purchase("shop-order-1", over_item, VALID_ADDRESS, settings=SETTINGS)

    assert proposal.proposal_type == ProposalType.HOLD


def test_supplier_purchase_proposal_always_requires_human_approval_regardless_of_automation_flag():
    """レベルB方針: enable_automated_supplier_purchaseの値に関わらずrequires_human_approval=True固定。"""
    automated_settings = Settings(
        max_supplier_order_cost=Decimal("50.00"), enable_automated_supplier_purchase=True
    )

    proposal = evaluate_supplier_purchase("shop-order-1", _item(), VALID_ADDRESS, settings=automated_settings)

    assert proposal.requires_human_approval is True
