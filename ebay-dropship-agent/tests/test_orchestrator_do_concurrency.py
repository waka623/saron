"""F4の回帰テスト: publish/price_changeの並行実行による重複実行防止(F3と同型)。

adversarial security review(2026-08-29)のF4: `execute_publish`/`execute_price_change` も
`execute_purchase`(F3で修正済み)と同じ構造的欠陥を持つ ── 承認済みproposalの状態遷移が
get-then-set(DBロック無し)で、実行時の`APPROVED`チェックが呼び出し元スナップショットに対する
判定でしかない。並行呼び出し(手動実行の重複・cronとAPIトリガーの重なり等)で、同一proposalに対し
outbound API呼び出し(publish_offer/update_offer)が二重に発行されうる。

このファイルは2スレッド・独立DBセッションでの並行実行を再現し、実際の外部呼び出し
(publish_offer / update_offer)がちょうど1回だけになること、敗者側はクラッシュではなく
`AlreadyClaimedError`というクリーンな拒否になることを検証する。
"""

from __future__ import annotations

import threading
from decimal import Decimal
from queue import Queue

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.orchestrator.do import execute_price_change, execute_publish
from ebay_dropship.store import AlreadyClaimedError, Base, SqlProposalRepository
from tests.fakes.ebay_inventory_fake import FakeInventoryBackend

SETTINGS = Settings(min_net_profit=Decimal("5.0"))
PUBLISH_PROPOSAL_ID = "race-publish-0001"
PRICE_PROPOSAL_ID = "race-price-0001"


class BarrierRepository(SqlProposalRepository):
    """`claimed_execution` の直前で全参加者を待ち合わせ、同時到達を強制するテスト専用ラッパー。"""

    def __init__(self, session, barrier: threading.Barrier):
        super().__init__(session)
        self._barrier = barrier

    def claimed_execution(self, proposal_id: str, decided_by: str):
        self._barrier.wait(timeout=10)
        return super().claimed_execution(proposal_id, decided_by)


def _ebay_client(backend: FakeInventoryBackend) -> EbayClient:
    http_client = httpx.Client(transport=backend.transport())
    return EbayClient("id", "secret", "refresh", http_client=http_client, retry_sleep=lambda _s: None)


def _seed_publish(db_path) -> None:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    repo = SqlProposalRepository(session)
    proposal = Proposal(
        id=PUBLISH_PROPOSAL_ID,
        proposal_type=ProposalType.PUBLISH,
        priority=Priority.MEDIUM,
        summary="出品ドラフト(並行実行テスト)",
        rationale="卸サプライヤーから直送。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("10.5913"),
        requires_human_approval=True,
        # item/offerは作成済みとして種を蒔み、競合させたい最後の1手(publish_offer)だけを両者に踏ませる。
        payload={
            "sku": "X1",
            "title": "Acme ワイヤレスマウス Black",
            "description": "発送目安: ご注文から5営業日以内に発送します。",
            "category_id": "12345",
            "item_specifics": {"Brand": "Acme", "Color": "Black"},
            "list_price": Decimal("29.99"),
            "handling_time_days": 5,
            "ebay_item_id": "X1",
            "ebay_offer_id": "offer-X1",
        },
    )
    repo.enqueue(proposal)
    repo.approve(PUBLISH_PROPOSAL_ID, decided_by="alice")
    session.commit()
    session.close()
    engine.dispose()


def _seed_price_change(db_path) -> None:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    repo = SqlProposalRepository(session)
    proposal = Proposal(
        id=PRICE_PROPOSAL_ID,
        proposal_type=ProposalType.PRICE_CHANGE,
        priority=Priority.MEDIUM,
        summary="値下げ提案(並行実行テスト)",
        rationale="卸サプライヤー在庫を確認済み。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("8.0"),
        requires_human_approval=True,
        payload={"listing_id": "A123", "ebay_offer_id": "offer-A123", "proposed_price": "27.99"},
    )
    repo.enqueue(proposal)
    repo.approve(PRICE_PROPOSAL_ID, decided_by="alice")
    session.commit()
    session.close()
    engine.dispose()


def _run_publish_once(db_path, backend: FakeInventoryBackend, barrier: threading.Barrier) -> tuple[str, str]:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    repo = BarrierRepository(session, barrier)
    try:
        proposal = repo.get(PUBLISH_PROPOSAL_ID)
        result = execute_publish(
            proposal, repository=repo, ebay_client=_ebay_client(backend), settings=SETTINGS, calls_remaining=10
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


def _run_price_change_once(db_path, backend: FakeInventoryBackend, barrier: threading.Barrier) -> tuple[str, str]:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    repo = BarrierRepository(session, barrier)
    try:
        proposal = repo.get(PRICE_PROPOSAL_ID)
        result = execute_price_change(
            proposal, repository=repo, ebay_client=_ebay_client(backend), settings=SETTINGS, calls_remaining=10
        )
        session.commit()
        return ("ok", result.status.value)
    except AlreadyClaimedError as exc:
        session.rollback()
        return ("already_claimed", str(exc))
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return (f"error:{type(exc).__name__}", str(exc))
    finally:
        session.close()
        engine.dispose()


def test_concurrent_execute_publish_from_two_threads_only_one_actually_publishes(tmp_path):
    db_path = tmp_path / "race_publish.db"
    _seed_publish(db_path)
    backend = FakeInventoryBackend()
    barrier = threading.Barrier(2)
    results: Queue[tuple[str, tuple[str, str]]] = Queue()

    def worker(label: str) -> None:
        results.put((label, _run_publish_once(db_path, backend, barrier)))

    threads = [threading.Thread(target=worker, args=(label,)) for label in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = dict(results.queue)
    assert set(outcomes) == {"A", "B"}
    categories = [category for category, _ in outcomes.values()]
    assert sorted(categories) == ["already_claimed", "ok"], outcomes

    publish_calls = [c for c in backend.calls if c[0] == "POST" and c[1].endswith("/publish")]
    assert len(publish_calls) == 1, f"publish_offerが{len(publish_calls)}回呼ばれた(2回なら重複実行): {backend.calls}"


def test_concurrent_execute_price_change_from_two_threads_only_one_actually_applies(tmp_path):
    db_path = tmp_path / "race_price.db"
    _seed_price_change(db_path)
    backend = FakeInventoryBackend()
    barrier = threading.Barrier(2)
    results: Queue[tuple[str, tuple[str, str]]] = Queue()

    def worker(label: str) -> None:
        results.put((label, _run_price_change_once(db_path, backend, barrier)))

    threads = [threading.Thread(target=worker, args=(label,)) for label in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = dict(results.queue)
    assert set(outcomes) == {"A", "B"}
    categories = [category for category, _ in outcomes.values()]
    assert sorted(categories) == ["already_claimed", "ok"], outcomes

    update_calls = [c for c in backend.calls if c[0] == "PUT" and "/offer/" in c[1]]
    assert len(update_calls) == 1, f"update_offerが{len(update_calls)}回呼ばれた(2回なら重複実行): {backend.calls}"
