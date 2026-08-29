"""受注処理判断(orders/)のテスト。

主目的は「乖離を検知してpurchaseせずholdにする」ことの検証。要求どおり5つの乖離モードを含む:
在庫消失・原価上昇(margin超え)・発送不可地域・部分成功/重複受注(ingest_orders側)・同期ラグ。
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ebay_dropship.approval import ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.orders import evaluate_purchase, ingest_orders
from ebay_dropship.orders.models import IncomingOrder
from ebay_dropship.supplier import SupplierStock
from tests.fakes.supplier_fake import FakeSupplierAdapter

SETTINGS = Settings(min_net_profit=Decimal("5.0"))
FEE_PCT = Decimal(13)
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


def _stock(**overrides) -> SupplierStock:
    defaults = {
        "sku": "X1",
        "cost": Decimal("12.00"),
        "quantity": 10,
        "lead_time_days": 3,
        "as_of": NOW - timedelta(minutes=30),
    }
    defaults.update(overrides)
    return SupplierStock(**defaults)


def _order(**overrides) -> IncomingOrder:
    defaults = {
        "order_id": "ORD-1",
        "sku": "X1",
        "quantity": 1,
        "customer_paid": Decimal("29.99"),
        "ship_to_country": "US",
        "due_date": NOW + timedelta(days=10),
        "assumed_supplier_cost": Decimal("12.00"),
    }
    defaults.update(overrides)
    return IncomingOrder(**defaults)


# --- ingest_orders: 部分成功(不正データの隔離)・重複受注 ---


def test_ingest_orders_isolates_malformed_records_without_failing():
    raw = [
        {
            "order_id": "ORD-1",
            "sku": "X1",
            "quantity": 1,
            "customer_paid": "29.99",
            "ship_to_country": "US",
            "due_date": "2026-09-05T00:00:00+00:00",
            "assumed_supplier_cost": "12.00",
        },
        {"order_id": "ORD-2", "sku": "X2"},  # 必須フィールド欠落(部分成功: これだけ隔離)
    ]

    result = ingest_orders(raw)

    assert [o.order_id for o in result.orders] == ["ORD-1"]
    assert len(result.errors) == 1
    assert result.errors[0].reason  # 理由が記録されている


def test_ingest_orders_deduplicates_repeated_order_id():
    raw_order = {
        "order_id": "ORD-1",
        "sku": "X1",
        "quantity": 1,
        "customer_paid": "29.99",
        "ship_to_country": "US",
        "due_date": "2026-09-05T00:00:00+00:00",
        "assumed_supplier_cost": "12.00",
    }

    result = ingest_orders([raw_order, dict(raw_order)])  # 同じorder_idが2回(重複受注)

    assert len(result.orders) == 1
    assert result.duplicate_order_ids == ["ORD-1"]


# --- evaluate_purchase: 5つの乖離モード ---


def test_purchases_when_everything_checks_out():
    supplier = FakeSupplierAdapter({"X1": _stock()})

    proposal = evaluate_purchase(_order(), supplier, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.PURCHASE
    assert proposal.payload["supplier_cost"] == Decimal("12.00")
    expected_profit = Decimal("29.99") - Decimal("12.00") - (Decimal("29.99") * Decimal(13) / Decimal(100))
    assert proposal.estimated_profit == expected_profit


def test_holds_when_stock_lost():
    """在庫消失: サプライヤーにSKUが見当たらない。"""
    supplier = FakeSupplierAdapter({})  # X1が無い

    proposal = evaluate_purchase(_order(), supplier, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.HOLD
    assert "在庫消失" in proposal.rationale


def test_holds_when_quantity_insufficient():
    """在庫消失(部分的): 数量が要求を満たさない。"""
    supplier = FakeSupplierAdapter({"X1": _stock(quantity=0)})

    proposal = evaluate_purchase(_order(quantity=1), supplier, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.HOLD
    assert "在庫不足" in proposal.rationale


def test_holds_when_cost_increased_beyond_margin():
    """原価上昇: 受注時想定原価より現在原価が上がり、利益ガードを割る。"""
    supplier = FakeSupplierAdapter({"X1": _stock(cost=Decimal("28.00"))})  # 受注時想定は12.00

    proposal = evaluate_purchase(_order(), supplier, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.HOLD
    assert proposal.payload["supplier_cost"] == Decimal("28.00")
    assert proposal.estimated_profit is not None
    assert proposal.estimated_profit < SETTINGS.min_net_profit


def test_holds_for_non_shippable_destination():
    """発送不可地域。"""
    supplier = FakeSupplierAdapter({"X1": _stock()})

    proposal = evaluate_purchase(
        _order(ship_to_country="KP"), supplier, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW
    )

    assert proposal.proposal_type == ProposalType.HOLD
    assert "発送不可地域" in proposal.rationale


def test_holds_when_supplier_data_is_stale():
    """同期ラグ: サプライヤーデータのas_ofが古すぎる。"""
    stale_settings = Settings(min_net_profit=Decimal("5.0"), supplier_data_max_age_minutes=60)
    supplier = FakeSupplierAdapter({"X1": _stock(as_of=NOW - timedelta(hours=2))})

    proposal = evaluate_purchase(_order(), supplier, settings=stale_settings, fee_pct=FEE_PCT, now=NOW)

    assert proposal.proposal_type == ProposalType.HOLD
    assert "同期ラグ" in proposal.rationale


def test_holds_when_lead_time_exceeds_due_date():
    supplier = FakeSupplierAdapter({"X1": _stock(lead_time_days=30)})

    proposal = evaluate_purchase(
        _order(due_date=NOW + timedelta(days=5)), supplier, settings=SETTINGS, fee_pct=FEE_PCT, now=NOW
    )

    assert proposal.proposal_type == ProposalType.HOLD
    assert "納期" in proposal.rationale
