"""AGENT_PROMPTS.md 第0章の共通提案エンベロープと、承認キューの UI 非依存インターフェース。"""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ProposalType(StrEnum):
    PUBLISH = "publish"
    PRICE_CHANGE = "price_change"
    WITHDRAW = "withdraw"
    PURCHASE = "purchase"
    HOLD = "hold"
    NONE = "none"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NEEDS_REVIEW = "要確認"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


WRITE_PROPOSAL_TYPES = frozenset(
    {ProposalType.PUBLISH, ProposalType.PRICE_CHANGE, ProposalType.WITHDRAW, ProposalType.PURCHASE}
)


class Proposal(BaseModel):
    """4エージェント共通の出力契約(AGENT_PROMPTS.md 第0章)。orchestrator がこの形で proposals に積む。"""

    id: str | None = None
    proposal_type: ProposalType
    priority: Priority
    summary: str
    rationale: str
    risk_level: RiskLevel
    estimated_profit: Decimal | None = None  # 金額は Decimal 固定(float禁止)
    requires_human_approval: bool
    payload: dict[str, Any] = {}
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None


class ApprovalQueue(ABC):
    """CLI・Web(api/)双方から使う承認キュー。実体は Phase 2 で store/ に実装する。"""

    @abstractmethod
    def enqueue(self, proposal: Proposal) -> Proposal: ...

    @abstractmethod
    def list_pending(self) -> list[Proposal]: ...

    @abstractmethod
    def approve(self, proposal_id: str, decided_by: str) -> Proposal: ...

    @abstractmethod
    def reject(self, proposal_id: str, decided_by: str, reason: str) -> Proposal: ...
