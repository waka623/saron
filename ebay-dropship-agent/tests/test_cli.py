"""承認CLI(proposals list/approve/reject)のE2Eテスト。"""

from decimal import Decimal

import pytest
from click.testing import CliRunner

from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.cli import cli
from ebay_dropship.config import settings
from ebay_dropship.store import (
    Base,
    SqlProposalRepository,
    create_engine_from_settings,
    create_session_factory,
)


@pytest.fixture()
def cli_db(tmp_path, monkeypatch):
    db_path = tmp_path / "cli_test.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    return engine


def _seed_proposal(engine) -> str:
    session = create_session_factory(engine)()
    proposal = Proposal(
        proposal_type=ProposalType.PRICE_CHANGE,
        priority=Priority.MEDIUM,
        summary="CLIテスト用の値下げ提案",
        rationale="卸サプライヤーから直送",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("8.0"),
        requires_human_approval=True,
    )
    saved = SqlProposalRepository(session).enqueue(proposal)
    session.commit()
    session.close()
    return saved.id


def test_list_shows_pending_proposal(cli_db):
    proposal_id = _seed_proposal(cli_db)
    runner = CliRunner()

    result = runner.invoke(cli, ["proposals", "list"])

    assert result.exit_code == 0
    assert proposal_id in result.output


def test_approve_records_decided_by(cli_db):
    proposal_id = _seed_proposal(cli_db)
    runner = CliRunner()

    result = runner.invoke(cli, ["proposals", "approve", proposal_id, "--by", "alice"])

    assert result.exit_code == 0
    assert "approved" in result.output
    assert "status=approved" in result.output


def test_reject_requires_reason(cli_db):
    proposal_id = _seed_proposal(cli_db)
    runner = CliRunner()

    result = runner.invoke(cli, ["proposals", "reject", proposal_id, "--by", "bob"])

    assert result.exit_code != 0  # --reason が必須


def test_approve_then_approve_again_fails_invalid_transition(cli_db):
    proposal_id = _seed_proposal(cli_db)
    runner = CliRunner()
    runner.invoke(cli, ["proposals", "approve", proposal_id, "--by", "alice"])

    result = runner.invoke(cli, ["proposals", "approve", proposal_id, "--by", "alice"])

    assert result.exit_code != 0


def test_cycle_run_once_reports_zero_when_no_tasks_wired(cli_db):
    """現時点ではPlan/Actの自動タスク列挙は未統合のため、空実行でsingle-flight機構の疎通のみ確認する。"""
    runner = CliRunner()

    result = runner.invoke(cli, ["cycle", "run-once"])

    assert result.exit_code == 0
    assert "plan: enqueued=0 skipped=0" in result.output
    assert "act: enqueued=0 skipped=0" in result.output
