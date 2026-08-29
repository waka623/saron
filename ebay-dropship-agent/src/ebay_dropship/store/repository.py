"""proposals の承認キュー実装(SQLAlchemy)。status は _ALLOWED_TRANSITIONS 以外への遷移を必ず弾く。"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from ebay_dropship.approval import ApprovalQueue, Proposal, ProposalStatus
from ebay_dropship.store.models import ProposalRecord

# F5(adversarial security review, 2026-08-29): eBay APIの上流エラー本文(response.text)が
# EbayApiError/EbayAuthError のメッセージにそのまま埋め込まれ、mark_failed経由で
# payload.failure_reason としてDB保存され、認証済みAPIから閲覧可能になる。トークン等の
# 秘密情報らしきパターンが将来紛れ込んでも保存前に伏せられるよう、汎用的なサニタイズを行う。
_SECRET_LIKE_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+/-]{8,}=*"
    r"|(?:access_token|refresh_token|client_secret)[\"']?\s*[:=]\s*[\"']?[a-z0-9._~+/-]{6,}=*)"
)


def _redact_secret_like_values(text: str) -> str:
    return _SECRET_LIKE_PATTERN.sub("[REDACTED]", text)


class InvalidTransitionError(Exception):
    pass


class ProposalNotFoundError(Exception):
    pass


class AlreadyClaimedError(InvalidTransitionError):
    """claim_for_execution/claimed_execution で実行権を獲得できなかった(既に他の実行者が処理済み)。

    二重発注防止の主保証(F3): 呼び出し元はこの例外を受け取った時点で副作用(発注等)を
    一切呼んでおらず、mark_failed 等の追加の状態遷移も行ってはならない
    (勝者側が既に executed/failed のいずれかへ確定させているため)。
    """


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
        record.payload = {**record.payload, "failure_reason": _redact_secret_like_values(reason)}
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

    def claim_for_execution(self, proposal_id: str, decided_by: str) -> bool:
        """DBレベルの原子的な条件付き更新(compare-and-set)で実行権を獲得する(F3の主保証)。

        `UPDATE proposals SET status='executed' WHERE id=? AND status='approved'` を発行し、
        影響行数が1のときだけ実行権を獲得できたとみなして True を返す。0のときは既に他の
        実行者が実行権を獲得済み(または approved 以外の状態)であり False を返す ――
        呼び出し元はこの場合、実際の副作用(発注・出品等)を絶対に呼んではならない。

        `_transition`(get-then-set)と異なり、この一文のUPDATEはDBのロックで直列化されるため、
        複数プロセス/複数スレッドから同時に呼ばれても「影響行数1」を得るのはちょうど1者だけになる。
        """
        stmt = (
            sa_update(ProposalRecord)
            .where(ProposalRecord.id == proposal_id, ProposalRecord.status == ProposalStatus.APPROVED)
            .values(status=ProposalStatus.EXECUTED, decided_by=decided_by, decided_at=datetime.now(UTC))
        )
        result = self._session.execute(stmt)
        return result.rowcount == 1

    @contextmanager
    def claimed_execution(self, proposal_id: str, decided_by: str) -> Iterator[None]:
        """`claim_for_execution` と実際の副作用を1つのSAVEPOINTとして直列化する(F3)。

        実行権を獲得できなければ `AlreadyClaimedError` を送出し、withブロックの中身
        (実際の発注呼び出し等)は一切実行しない。実行権を獲得できた場合、withブロック内で
        例外が送出されると、この呼び出しによる status='executed' への変更を含めてSAVEPOINT
        全体がロールバックされる(status は 'approved' に戻る)。ロールバック後に 'failed' へ
        遷移させ理由を記録するかどうかは、事情を一番よく知る呼び出し側の責務とする。
        """
        with self._session.begin_nested():
            if not self.claim_for_execution(proposal_id, decided_by):
                raise AlreadyClaimedError(
                    f"proposal {proposal_id} は既に他の実行者が実行権を獲得済みです"
                    "(二重発注防止のため、この実行者は副作用を呼ばずに処理を中断しました)。"
                )
            yield
