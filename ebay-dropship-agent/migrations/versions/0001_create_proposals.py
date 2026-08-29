"""create proposals table

Revision ID: 0001
Revises:
Create Date: 2026-08-29

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "proposal_type",
            sa.Enum(
                "publish",
                "price_change",
                "withdraw",
                "purchase",
                "hold",
                "none",
                name="proposal_type",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "high", "medium", "low", "要確認", name="priority", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "risk_level",
            sa.Enum("low", "medium", "high", name="risk_level", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("estimated_profit", sa.Numeric(12, 2), nullable=True),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "executed",
                "failed",
                name="proposal_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("proposals")
