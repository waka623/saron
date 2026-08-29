"""Alembic マイグレーションが実際に proposals テーブルを作ることを検証する(DB非依存性の実地確認)。"""

import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPECTED_COLUMNS = {
    "id",
    "proposal_type",
    "priority",
    "summary",
    "rationale",
    "risk_level",
    "estimated_profit",
    "requires_human_approval",
    "payload",
    "status",
    "created_at",
    "decided_by",
    "decided_at",
}


def test_alembic_upgrade_head_creates_proposals_table(tmp_path, monkeypatch):
    db_path = tmp_path / "alembic_test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))

    command.upgrade(cfg, "head")

    engine = sa.create_engine(db_url)
    inspector = sa.inspect(engine)

    assert "proposals" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("proposals")}
    assert columns == EXPECTED_COLUMNS


def test_alembic_downgrade_drops_proposals_table(tmp_path, monkeypatch):
    db_path = tmp_path / "alembic_downgrade_test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = sa.create_engine(db_url)
    inspector = sa.inspect(engine)
    assert "proposals" not in inspector.get_table_names()
