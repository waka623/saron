"""proposals の承認キュー実装(SQLAlchemy)。status は _ALLOWED_TRANSITIONS 以外への遷移を必ず弾く。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ebay_dropship.approval import ApprovalQueue, Proposal, ProposalStatus
from ebay_dropship.store.models import ProposalRecord


class InvalidTransitionError(Exception):
    pass


class ProposalNotFoundError(Exception):
    pass


# pending → approved/rejected → executed/failed。それ以外の遷移(逆行・終端状態からの変更等)は禁止。
_ALLOWED_TRANSITIONS: dict[ProposalStatus, frozenset[ProposalStatus]] = {
    ProposalStatus.PENDING: frozenset({ProposalStatus.APPROVED, ProposalStatus.REJECTED}),
    ProposalStatus.APPROVED: frozenset({ProposalStatus.EXECUTED, ProposalStatus.FAILED}),
    ProposalStatus.REJECTED: frozenset(),
    ProposalStatus.EXECUTED: frozenset(),
    ProposalStatus.FAILED: frozenset(),
}


def _to_domain(record: ProposalRecord) -> Proposal:
    return Proposal(
        id=record.id,
        proposal_type=record.proposal_type,
        priority=record.priority,
        summary=record.summary,
        rationale=record.rationale,
        risk_level=record.risk_level,
        estimated_profit=record.estimated_profit,
        requires_human_approval=record.requires_human_approval,
        payload=record.payload,
        status=record.status,
        created_at=record.created_at,
        decided_by=record.decided_by,
        decided_at=record.decided_at,
    )


class SqlProposalRepository(ApprovalQueue):
    def __init__(self, session: Session):
        self._session = session

    def enqueue(self, proposal: Proposal) -> Proposal:
        record = ProposalRecord(
            proposal_type=proposal.proposal_type,
            priority=proposal.priority,
            summary=proposal.summary,
            rationale=proposal.rationale,
            risk_level=proposal.risk_level,
            estimated_profit=proposal.estimated_profit,
            requires_human_approval=proposal.requires_human_approval,
            payload=proposal.payload,
            status=ProposalStatus.PENDING,
        )
        if proposal.id:  # 未指定なら ProposalRecord.id の default(new_id)に任せる
            record.id = proposal.id
        self._session.add(record)
        self._session.flush()
        return _to_domain(record)

    def list_pending(self) -> list[Proposal]:
        stmt = select(ProposalRecord).where(ProposalRecord.status == ProposalStatus.PENDING)
        return [_to_domain(r) for r in self._session.scalars(stmt)]

    def list_approved(self) -> list[Proposal]:
        stmt = select(ProposalRecord).where(ProposalRecord.status == ProposalStatus.APPROVED)
        return [_to_domain(r) for r in self._session.scalars(stmt)]

    def get(self, proposal_id: str) -> Proposal:
        return _to_domain(self._get_record(proposal_id))

    def _get_record(self, proposal_id: str) -> ProposalRecord:
        record = self._session.get(ProposalRecord, proposal_id)
        if record is None:
            raise ProposalNotFoundError(f"proposal not found: {proposal_id}")
        return record

    def _transition(self, proposal_id: str, new_status: ProposalStatus, decided_by: str) -> ProposalRecord:
        record = self._get_record(proposal_id)
        allowed = _ALLOWED_TRANSITIONS.get(record.status, frozenset())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"{record.status} から {new_status} への遷移は許可されていません"
                f"(proposal_id={proposal_id})。"
            )
        record.status = new_status
        record.decided_by = decided_by
        record.decided_at = datetime.now(UTC)
        self._session.flush()
        return record

    def approve(self, proposal_id: str, decided_by: str) -> Proposal:
        return _to_domain(self._transition(proposal_id, ProposalStatus.APPROVED, decided_by))

    def reject(self, proposal_id: str, decided_by: str, reason: str) -> Proposal:
        record = self._transition(proposal_id, ProposalStatus.REJECTED, decided_by)
        record.payload = {**record.payload, "rejection_reason": reason}
        self._session.flush()
        return _to_domain(record)

    def mark_executed(self, proposal_id: str, decided_by: str) -> Proposal:
        """guardrails.gateway.execute_side_effect が成功した後にのみ呼ぶこと(Phase 4 で接続)。"""
        return _to_domain(self._transition(proposal_id, ProposalStatus.EXECUTED, decided_by))

    def mark_failed(self, proposal_id: str, decided_by: str, reason: str) -> Proposal:
        record = self._transition(proposal_id, ProposalStatus.FAILED, decided_by)
        record.payload = {**record.payload, "failure_reason": reason}
        self._session.flush()
        return _to_domain(record)

    def update_payload(self, proposal_id: str, payload: dict) -> Proposal:
        """status は変更せず payload だけを更新する。実行途中の進捗(生成済みitem/offer id等)を、

        原子性を壊さずに記録するために使う(中断・再試行時に完了済みステップを再実行しないようにする)。
        """
        record = self._get_record(proposal_id)
        record.payload = payload
        self._session.flush()
        return _to_domain(record)
