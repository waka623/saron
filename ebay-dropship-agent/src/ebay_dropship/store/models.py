"""SQLAlchemy モデル。PROMPT.md 第7章のテーブルのうち、Phase 2 は `proposals` のみ実装する。

DB非依存を保つため、SQLite固有機能(AUTOINCREMENT の暗黙依存等)には頼らない。
金額は Numeric(Decimal) 固定(float禁止)。payload は JSON 型。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ebay_dropship.approval import Priority, ProposalStatus, ProposalType, RiskLevel


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


_DECIMAL_TAG = "__decimal__"


def _tag_decimals(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {_DECIMAL_TAG: str(value)}
    if isinstance(value, dict):
        return {key: _tag_decimals(v) for key, v in value.items()}
    if isinstance(value, list):
        return [_tag_decimals(v) for v in value]
    return value


def _untag_decimals(value: Any) -> Any:
    if isinstance(value, dict):
        if value.keys() == {_DECIMAL_TAG}:
            return Decimal(value[_DECIMAL_TAG])
        return {key: _untag_decimals(v) for key, v in value.items()}
    if isinstance(value, list):
        return [_untag_decimals(v) for v in value]
    return value


class DecimalSafeJSON(TypeDecorator):
    """payload(JSON)内に Decimal が混じっていても float 化せず型を保って永続化する。

    DB上のDDLはJSONのまま(Alembicのマイグレーション変更は不要)。タグ付き表現
    ({"__decimal__": "29.99"}) で往復させるのはアプリ層(ORM)の変換のみ。
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return _tag_decimals(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return _untag_decimals(value)


def _enum_column(enum_cls, name: str, length: int):
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
    )


class ProposalRecord(Base):
    """AGENT_PROMPTS.md 第0章の共通エンベロープ全フィールド + 承認状態(status/decided_by/decided_at)。"""

    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    proposal_type: Mapped[ProposalType] = mapped_column(
        _enum_column(ProposalType, "proposal_type", 32), nullable=False
    )
    priority: Mapped[Priority] = mapped_column(_enum_column(Priority, "priority", 32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(
        _enum_column(RiskLevel, "risk_level", 16), nullable=False
    )
    estimated_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict] = mapped_column(DecimalSafeJSON, nullable=False, default=dict)
    status: Mapped[ProposalStatus] = mapped_column(
        _enum_column(ProposalStatus, "proposal_status", 16),
        nullable=False,
        default=ProposalStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
