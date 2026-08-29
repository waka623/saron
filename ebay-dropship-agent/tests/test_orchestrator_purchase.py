"""Phase 5(Do拡張): 承認済みpurchase提案の実行。

実発注は常に ManualOrderPurchaseChannel(発注パケットの記録のみ、実送信なし)に対してのみ行う。
実行の瞬間にサプライヤーへ再問い合わせし、受注時点の数字を信用しない(deny by default)ことを検証する。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.approval import Priority, Proposal, ProposalStatus, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.guardrails.gateway import GuardrailDenied
from ebay_dropship.orchestrator.do import execute_purchase
from ebay_dropship.orders.purchase_channel import ManualOrderPurchaseChannel
from ebay_dropship.store import Base, SqlProposalRepository
from ebay_dropship.supplier import SupplierStock
from tests.fakes.supplier_fake import FakeSupplierAdapter

SETTINGS = Settings(min_net_profit=Decimal("5.0"))
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return SqlProposalRepository(session)


def _stock(**overrides) -> SupplierStock:
    defaults = {
        "sku": "X1",
        "cost": Decimal("12.00"),
        "quantity": 5,
        "lead_time_days": 3,
        "as_of": NOW - timedelta(minutes=30),
    }
    defaults.update(overrides)
    return SupplierStock(**defaults)


def _seed_approved_purchase(repo, **payload_overrides) -> Proposal:
    payload = {
        "order_id": "ORD-1",
        "sku": "X1",
        "supplier_cost": Decimal("12.00"),
        "recalculated_profit": Decimal("14.10"),
        "eta_days": 3,
        "issue": "",
        "quantity": 1,
        "customer_paid": Decimal("29.99"),
        "ship_to_country": "US",
        "due_date": (NOW + timedelta(days=10)).isoformat(),
    }
    payload.update(payload_overrides)
    proposal = Proposal(
        proposal_type=ProposalType.PURCHASE,
        priority=Priority.HIGH,
        summary="発注提案(テスト)",
        rationale="卸サプライヤーへ発注する。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("14.10"),
        requires_human_approval=True,
        payload=payload,
    )
    saved = repo.enqueue(proposal)
    return repo.approve(saved.id, decided_by="alice")


# --- 成功 ---


def test_purchase_success_records_packet_and_marks_executed(repo):
    supplier = FakeSupplierAdapter({"X1": _stock()})
    channel = ManualOrderPurchaseChannel()
    proposal = _seed_approved_purchase(repo)

    result = execute_purchase(
        proposal,
        repository=repo,
        supplier=supplier,
        purchase_channel=channel,
        settings=SETTINGS,
        calls_remaining=10,
        now=NOW,
    )

    assert result.status == ProposalStatus.EXECUTED
    assert "ORD-1" in channel.recorded_packets
    assert channel.recorded_packets["ORD-1"].unit_cost == Decimal("12.00")
    stored = repo.get(proposal.id)
    assert stored.payload["purchase_reference_id"] == "ORD-1"


# --- 冪等性: 同一order_idの再実行で二重発注しない ---


def test_purchase_retry_after_interrupted_attempt_does_not_resubmit(repo):
    """発注パケット記録後にプロセスが落ちた想定(statusはAPPROVEDのまま、payloadだけ記録済み)。"""
    supplier = FakeSupplierAdapter({"X1": _stock()})
    channel = ManualOrderPurchaseChannel()
    proposal = _seed_approved_purchase(repo, purchase_reference_id="ORD-1")

    result = execute_purchase(
        proposal,
        repository=repo,
        supplier=supplier,
        purchase_channel=channel,
        settings=SETTINGS,
        calls_remaining=10,
        now=NOW,
    )

    assert result.status == ProposalStatus.EXECUTED
    assert channel.recorded_packets == {}  # submit_purchase は一度も呼ばれていない(冪等)


def test_purchase_channel_itself_treats_duplicate_submission_idempotently():
    channel = ManualOrderPurchaseChannel()
    from ebay_dropship.orders.purchase_channel import PurchaseOrderPacket

    packet = PurchaseOrderPacket(
        order_id="ORD-1", sku="X1", quantity=1, unit_cost=Decimal("12.00"),
        supplier_name="csv_supplier", ship_to_country="US",
    )

    first = channel.submit_purchase(packet)
    second = channel.submit_purchase(packet)

    assert first.status == "recorded_for_manual_order"
    assert second.status == "duplicate"
    assert len(channel.recorded_packets) == 1  # 二重発注していない


# --- 実行時再検査(deny by default): 受注時点の数字を信用しない ---


def test_purchase_blocked_when_stock_lost_at_execution_time(repo):
    supplier = FakeSupplierAdapter({})  # 承認後にSKUが消えた想定
    channel = ManualOrderPurchaseChannel()
    proposal = _seed_approved_purchase(repo)

    with pytest.raises(GuardrailDenied):
        execute_purchase(
            proposal, repository=repo, supplier=supplier, purchase_channel=channel,
            settings=SETTINGS, calls_remaining=10, now=NOW,
        )

    assert channel.recorded_packets == {}
    assert repo.get(proposal.id).status == ProposalStatus.FAILED


def test_purchase_blocked_when_current_cost_exceeds_margin_at_execution_time(repo):
    """承認時点では利益が出ていたが、実行の瞬間に現在原価で再計算するとガード割れ。"""
    supplier = FakeSupplierAdapter({"X1": _stock(cost=Decimal("28.00"))})
    channel = ManualOrderPurchaseChannel()
    proposal = _seed_approved_purchase(repo)  # payload上のsupplier_costは12.00のまま(古い)

    with pytest.raises(GuardrailDenied):
        execute_purchase(
            proposal, repository=repo, supplier=supplier, purchase_channel=channel,
            settings=SETTINGS, calls_remaining=10, now=NOW,
        )

    assert channel.recorded_packets == {}


def test_purchase_blocked_when_supplier_data_stale_at_execution_time(repo):
    strict_settings = Settings(min_net_profit=Decimal("5.0"), supplier_data_max_age_minutes=10)
    supplier = FakeSupplierAdapter({"X1": _stock(as_of=NOW - timedelta(hours=2))})
    channel = ManualOrderPurchaseChannel()
    proposal = _seed_approved_purchase(repo)

    with pytest.raises(GuardrailDenied):
        execute_purchase(
            proposal, repository=repo, supplier=supplier, purchase_channel=channel,
            settings=strict_settings, calls_remaining=10, now=NOW,
        )

    assert channel.recorded_packets == {}
    assert repo.get(proposal.id).status == ProposalStatus.FAILED


def test_purchase_blocked_when_stock_insufficient_at_execution_time(repo):
    supplier = FakeSupplierAdapter({"X1": _stock(quantity=0)})
    channel = ManualOrderPurchaseChannel()
    proposal = _seed_approved_purchase(repo, quantity=1)

    with pytest.raises(GuardrailDenied):
        execute_purchase(
            proposal, repository=repo, supplier=supplier, purchase_channel=channel,
            settings=SETTINGS, calls_remaining=10, now=NOW,
        )

    assert channel.recorded_packets == {}


# --- dry-run ---


def test_purchase_dry_run_does_not_submit_and_leaves_status_approved(repo):
    supplier = FakeSupplierAdapter({"X1": _stock()})
    channel = ManualOrderPurchaseChannel()
    proposal = _seed_approved_purchase(repo)

    result = execute_purchase(
        proposal, repository=repo, supplier=supplier, purchase_channel=channel,
        settings=SETTINGS, calls_remaining=10, dry_run=True, now=NOW,
    )

    assert result.status == ProposalStatus.APPROVED
    assert channel.recorded_packets == {}
    stored = repo.get(proposal.id)
    assert "purchase_packet" in stored.payload["dry_run_preview"]


# --- feature flag: 自動実発注はデフォルトOFF固定 ---


def test_automated_supplier_purchase_is_disabled_by_default():
    assert Settings().enable_automated_supplier_purchase is False
