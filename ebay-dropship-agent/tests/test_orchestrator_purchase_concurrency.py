"""F3の回帰テスト: 承認済みpurchase提案の並行実行による二重発注の防止。

adversarial security review(2026-08-29)で、`execute_purchase` を独立したDBセッションを持つ
2スレッドから同時実行すると、`purchase_channel.submit_purchase` が同一 order_id に対して
2回とも成功してしまうことを実証した(state machine の InvalidTransitionError は2回目の
`mark_executed` でしか衝突を検知せず、その時点で既に外部副作用は2回発行済みだった)。

このファイルは、その反例をそのまま自動テストとして固定する。修正前は次の2点が壊れる:
  1. `purchase_channel.submit_purchase` が2回とも成功してしまう(二重発注)。
  2. 敗者側が「クラッシュ/生の例外」ではなく「実行権を獲得できなかった、クリーンな拒否」に
     ならない(修正前は両者ともsubmit_purchaseまで到達してしまうため、この区別自体が無い)。

修正後は、DBレベルの原子的な条件付き更新(`SqlProposalRepository.claimed_execution`)により、
ちょうど1つのスレッド/プロセスだけが発注権を獲得して実際に発注し、もう一方は
`AlreadyClaimedError`(`InvalidTransitionError`のサブクラス)で副作用を一切呼ばずに
クリーンに拒否されることを検証する。
"""

from __future__ import annotations

import multiprocessing
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from queue import Queue

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.approval import Priority, Proposal, ProposalStatus, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.orchestrator.do import execute_purchase
from ebay_dropship.orders.purchase_channel import (
    ManualOrderPurchaseChannel,
    PurchaseChannel,
    PurchaseOrderPacket,
    PurchaseResult,
)
from ebay_dropship.store import AlreadyClaimedError, Base, SqlProposalRepository
from ebay_dropship.supplier import SupplierAdapter, SupplierStock

SETTINGS = Settings(min_net_profit=Decimal("5.0"))
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
PROPOSAL_ID = "race-test-proposal-0001"
ORDER_ID = "ORD-RACE-1"


def _stock() -> SupplierStock:
    return SupplierStock(
        sku="X1", cost=Decimal("12.00"), quantity=5, lead_time_days=3, as_of=NOW - timedelta(minutes=30)
    )


class BarrierSupplierAdapter(SupplierAdapter):
    """発注実行時再検査(fetch_stock)の直前で全参加者を待ち合わせ、同時到達を強制する。"""

    def __init__(self, barrier: threading.Barrier | multiprocessing.synchronize.Barrier, stock: SupplierStock):
        self._barrier = barrier
        self._stock = stock

    def fetch_stock(self, sku: str) -> SupplierStock:
        self._barrier.wait(timeout=10)
        if sku != self._stock.sku:
            raise KeyError(sku)
        return self._stock

    def fetch_all_stock(self) -> list[SupplierStock]:
        return [self._stock]


@dataclass
class LoggingPurchaseChannel(PurchaseChannel):
    """実際の発注呼び出し回数を、プロセス境界を越えて数えられるようファイルにも記録する。"""

    log_path: Path

    def __post_init__(self) -> None:
        self._inner = ManualOrderPurchaseChannel()

    def submit_purchase(self, packet: PurchaseOrderPacket) -> PurchaseResult:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(packet.order_id + "\n")
        return self._inner.submit_purchase(packet)


def _seed_proposal(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    repo = SqlProposalRepository(session)
    proposal = Proposal(
        id=PROPOSAL_ID,
        proposal_type=ProposalType.PURCHASE,
        priority=Priority.HIGH,
        summary="発注提案(並行実行テスト)",
        rationale="卸サプライヤーへ発注する。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("14.10"),
        requires_human_approval=True,
        payload={
            "order_id": ORDER_ID,
            "sku": "X1",
            "supplier_cost": Decimal("12.00"),
            "recalculated_profit": Decimal("14.10"),
            "eta_days": 3,
            "issue": "",
            "quantity": 1,
            "customer_paid": Decimal("29.99"),
            "ship_to_country": "US",
            "due_date": (NOW + timedelta(days=10)).isoformat(),
        },
    )
    repo.enqueue(proposal)
    repo.approve(PROPOSAL_ID, decided_by="alice")
    session.commit()
    session.close()
    engine.dispose()


def _run_once(db_path: Path, log_path: Path, barrier) -> tuple[str, str]:
    """1参加者ぶんの execute_purchase 実行。(結果カテゴリ, 詳細) を返す(例外は握りつぶさない)。"""
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    repo = SqlProposalRepository(session)
    try:
        proposal = repo.get(PROPOSAL_ID)
        supplier = BarrierSupplierAdapter(barrier, _stock())
        channel = LoggingPurchaseChannel(log_path)
        result = execute_purchase(
            proposal,
            repository=repo,
            supplier=supplier,
            purchase_channel=channel,
            settings=SETTINGS,
            calls_remaining=10,
            now=NOW,
        )
        session.commit()
        return ("ok", result.status.value)
    except AlreadyClaimedError as exc:
        session.rollback()
        return ("already_claimed", str(exc))
    except Exception as exc:  # noqa: BLE001 - 反例で何が起きたかをそのまま報告するため
        session.rollback()
        return (f"error:{type(exc).__name__}", str(exc))
    finally:
        session.close()
        engine.dispose()


def test_concurrent_execute_purchase_from_two_threads_only_one_actually_purchases(tmp_path):
    """2スレッド・独立DBセッションでの同時 execute_purchase: 発注は必ずちょうど1回。"""
    db_path = tmp_path / "race.db"
    log_path = tmp_path / "submitted_orders.log"
    _seed_proposal(db_path)

    barrier = threading.Barrier(2)
    results: Queue[tuple[str, tuple[str, str]]] = Queue()

    def worker(label: str) -> None:
        results.put((label, _run_once(db_path, log_path, barrier)))

    threads = [threading.Thread(target=worker, args=(label,)) for label in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = dict(results.queue)
    assert set(outcomes) == {"A", "B"}

    categories = [category for category, _ in outcomes.values()]
    # ちょうど1者だけが実際に成功し(status=executed)、もう1者はクラッシュではなく
    # AlreadyClaimedError というクリーンな拒否になる。
    assert sorted(categories) == ["already_claimed", "ok"], outcomes

    submitted_orders = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    assert submitted_orders == [ORDER_ID], (
        f"submit_purchase が{len(submitted_orders)}回呼ばれた(2回なら二重発注): {submitted_orders}"
    )

    engine = create_engine(f"sqlite:///{db_path}")
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    final = SqlProposalRepository(session).get(PROPOSAL_ID)
    assert final.status == ProposalStatus.EXECUTED
    assert final.payload["purchase_reference_id"] == ORDER_ID


def _process_worker(db_path: str, log_path: str, barrier, queue: multiprocessing.Queue, label: str) -> None:
    queue.put((label, _run_once(Path(db_path), Path(log_path), barrier)))


def test_concurrent_execute_purchase_from_two_processes_only_one_actually_purchases(tmp_path):
    """2プロセス(真の並行、インプロセスロックが効かない)での同時 execute_purchase。"""
    db_path = tmp_path / "race_mp.db"
    log_path = tmp_path / "submitted_orders_mp.log"
    _seed_proposal(db_path)

    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(2)
    result_queue: multiprocessing.Queue = ctx.Queue()

    procs = [
        ctx.Process(target=_process_worker, args=(str(db_path), str(log_path), barrier, result_queue, label))
        for label in ("A", "B")
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=20)

    outcomes = {}
    while not result_queue.empty():
        label, outcome = result_queue.get()
        outcomes[label] = outcome

    assert set(outcomes) == {"A", "B"}, outcomes
    categories = [category for category, _ in outcomes.values()]
    assert sorted(categories) == ["already_claimed", "ok"], outcomes

    submitted_orders = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    assert submitted_orders == [ORDER_ID], (
        f"submit_purchase が{len(submitted_orders)}回呼ばれた(2回なら二重発注): {submitted_orders}"
    )
