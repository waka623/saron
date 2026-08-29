"""実キー無し・実発注OFFのデモ用フィクスチャ(demo.py)のテスト。

このモジュールは判断ロジックを一切持たず、research/listing/pricingの既存ロジックへ
固定フィクスチャを渡すだけであることを確認する(数値そのものの正しさはresearch/listing/pricing側の
既存テストで別途検証済み)。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.approval import ProposalStatus, ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.demo import (
    DEMO_LISTING_ID,
    DEMO_SKU,
    build_demo_act_tasks,
    build_demo_plan_tasks,
    seed_demo_supplier_csv,
)
from ebay_dropship.orchestrator.cycle import run_cycle
from ebay_dropship.store import Base, SqlProposalRepository

SETTINGS = Settings(min_net_profit=Decimal("5.0"))


def test_seed_demo_supplier_csv_writes_expected_row(tmp_path):
    csv_path = tmp_path / "supplier_feed.csv"

    seed_demo_supplier_csv(csv_path)

    text = csv_path.read_text(encoding="utf-8")
    assert "sku,cost,quantity,lead_time_days,as_of" in text
    assert DEMO_SKU in text


def test_seed_demo_supplier_csv_is_idempotent(tmp_path):
    csv_path = tmp_path / "nested" / "supplier_feed.csv"

    seed_demo_supplier_csv(csv_path)
    seed_demo_supplier_csv(csv_path)  # 再実行してもエラーにならず、1行のまま上書きされる

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # ヘッダー + データ1行


def test_plan_tasks_produce_hold_then_publish():
    tasks = build_demo_plan_tasks(SETTINGS)

    proposals = [task() for task in tasks]

    assert [p.proposal_type for p in proposals] == [ProposalType.HOLD, ProposalType.PUBLISH]
    assert proposals[1].payload["sku"] == DEMO_SKU
    assert proposals[1].requires_human_approval is True


def test_act_tasks_produce_price_change(tmp_path):
    csv_path = tmp_path / "supplier_feed.csv"
    seed_demo_supplier_csv(csv_path)
    from ebay_dropship.supplier.csv_adapter import CsvSupplierAdapter

    tasks = build_demo_act_tasks(SETTINGS, CsvSupplierAdapter(csv_path))

    proposals = [task() for task in tasks]

    assert len(proposals) == 1
    assert proposals[0].proposal_type == ProposalType.PRICE_CHANGE
    assert proposals[0].payload["listing_id"] == DEMO_LISTING_ID


def test_demo_tasks_wired_through_run_cycle_enqueue_three_proposals(tmp_path):
    """demo.pyのタスクをrun_cycleにそのまま渡すと、承認待ちが3件(hold/publish/price_change)積まれる。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    repo = SqlProposalRepository(sessionmaker(bind=engine, expire_on_commit=False)())
    csv_path = tmp_path / "supplier_feed.csv"
    seed_demo_supplier_csv(csv_path)
    from ebay_dropship.supplier.csv_adapter import CsvSupplierAdapter

    plan_tasks = build_demo_plan_tasks(SETTINGS)
    act_tasks = build_demo_act_tasks(SETTINGS, CsvSupplierAdapter(csv_path))

    result = run_cycle(repository=repo, plan_tasks=plan_tasks, act_tasks=act_tasks)

    assert result.errors == []
    assert len(result.plan_enqueued) == 2
    assert len(result.act_enqueued) == 1
    pending = repo.list_pending()
    assert len(pending) == 3
    assert all(p.status == ProposalStatus.PENDING for p in pending)
