"""proposals テーブル・状態遷移(pending→approved/rejected→executed/failed)のテスト。SQLite in-memory を使用。"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.approval import Priority, Proposal, ProposalStatus, ProposalType, RiskLevel
from ebay_dropship.store import (
    Base,
    InvalidTransitionError,
    ProposalNotFoundError,
    SqlProposalRepository,
)


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield SqlProposalRepository(session)
    session.close()


def _sample_proposal(**overrides) -> Proposal:
    defaults = {
        "proposal_type": ProposalType.PRICE_CHANGE,
        "priority": Priority.MEDIUM,
        "summary": "値下げ提案",
        "rationale": "卸サプライヤー在庫と価格を確認済み",
        "risk_level": RiskLevel.LOW,
        "estimated_profit": Decimal("4.66"),
        "requires_human_approval": True,
        "payload": {"listing_id": "A123", "proposed_price": "38.0"},
    }
    defaults.update(overrides)
    return Proposal(**defaults)


def test_enqueue_then_list_pending(repo):
    repo.enqueue(_sample_proposal())

    pending = repo.list_pending()

    assert len(pending) == 1
    assert pending[0].status == ProposalStatus.PENDING


def test_estimated_profit_round_trips_as_decimal_not_float(repo):
    saved = repo.enqueue(_sample_proposal(estimated_profit=Decimal("4.66")))

    fetched = repo.get(saved.id)

    assert isinstance(fetched.estimated_profit, Decimal)
    assert fetched.estimated_profit == Decimal("4.66")


def test_payload_round_trips_as_json(repo):
    saved = repo.enqueue(_sample_proposal(payload={"listing_id": "A123", "nested": {"x": 1}}))

    fetched = repo.get(saved.id)

    assert fetched.payload == {"listing_id": "A123", "nested": {"x": 1}}


def test_approve_records_decided_by_and_decided_at(repo):
    saved = repo.enqueue(_sample_proposal())

    approved = repo.approve(saved.id, decided_by="alice")

    assert approved.status == ProposalStatus.APPROVED
    assert approved.decided_by == "alice"
    assert approved.decided_at is not None


def test_reject_records_reason_in_payload(repo):
    saved = repo.enqueue(_sample_proposal())

    rejected = repo.reject(saved.id, decided_by="bob", reason="利益率が低すぎる")

    assert rejected.status == ProposalStatus.REJECTED
    assert rejected.payload["rejection_reason"] == "利益率が低すぎる"


def test_approved_can_transition_to_executed(repo):
    saved = repo.enqueue(_sample_proposal())
    repo.approve(saved.id, decided_by="alice")

    executed = repo.mark_executed(saved.id, decided_by="orchestrator")

    assert executed.status == ProposalStatus.EXECUTED


def test_approved_can_transition_to_failed(repo):
    saved = repo.enqueue(_sample_proposal())
    repo.approve(saved.id, decided_by="alice")

    failed = repo.mark_failed(saved.id, decided_by="orchestrator", reason="eBay API error")

    assert failed.status == ProposalStatus.FAILED
    assert failed.payload["failure_reason"] == "eBay API error"


@pytest.mark.parametrize(
    "transition",
    [
        "mark_executed",  # pending -> executed は禁止(承認を飛ばせない)
        "mark_failed",
    ],
)
def test_pending_cannot_skip_straight_to_terminal_status(repo, transition):
    saved = repo.enqueue(_sample_proposal())

    with pytest.raises(InvalidTransitionError):
        if transition == "mark_executed":
            repo.mark_executed(saved.id, decided_by="x")
        else:
            repo.mark_failed(saved.id, decided_by="x", reason="test")


def test_rejected_cannot_be_approved_afterwards(repo):
    saved = repo.enqueue(_sample_proposal())
    repo.reject(saved.id, decided_by="bob", reason="no")

    with pytest.raises(InvalidTransitionError):
        repo.approve(saved.id, decided_by="alice")


def test_executed_is_a_terminal_state(repo):
    saved = repo.enqueue(_sample_proposal())
    repo.approve(saved.id, decided_by="alice")
    repo.mark_executed(saved.id, decided_by="orchestrator")

    with pytest.raises(InvalidTransitionError):
        repo.mark_failed(saved.id, decided_by="orchestrator", reason="retry")


def test_unknown_proposal_id_raises_not_found(repo):
    with pytest.raises(ProposalNotFoundError):
        repo.approve("does-not-exist", decided_by="alice")
