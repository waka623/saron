"""`ebay-dropship demo seed` / `ebay-dropship cycle run-once --demo` のE2Eテスト。

実キー・実発注を使わないデモ経路であることを、CLIを通しで叩いて確認する。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from ebay_dropship.cli import cli
from ebay_dropship.config import settings
from ebay_dropship.store import Base, create_engine_from_settings


@pytest.fixture()
def cli_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'cli_demo_test.db'}")
    monkeypatch.setattr(settings, "supplier_csv_path", str(tmp_path / "supplier_feed.csv"))
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    return engine


def test_demo_seed_writes_supplier_csv(cli_db):
    runner = CliRunner()

    result = runner.invoke(cli, ["demo", "seed"])

    assert result.exit_code == 0
    assert "seeded demo supplier CSV" in result.output


def test_cycle_run_once_demo_enqueues_three_proposals(cli_db):
    runner = CliRunner()
    runner.invoke(cli, ["demo", "seed"])

    result = runner.invoke(cli, ["cycle", "run-once", "--demo"])

    assert result.exit_code == 0
    assert "plan: enqueued=2 skipped=0" in result.output
    assert "act: enqueued=1 skipped=0" in result.output
    assert "errors=0" in result.output

    list_result = runner.invoke(cli, ["proposals", "list"])
    assert "hold" in list_result.output
    assert "publish" in list_result.output
    assert "price_change" in list_result.output


def test_cycle_run_once_without_demo_flag_still_reports_zero(cli_db):
    """既存の既定動作(--demo無し)が壊れていないことの回帰防止。"""
    runner = CliRunner()

    result = runner.invoke(cli, ["cycle", "run-once"])

    assert result.exit_code == 0
    assert "plan: enqueued=0 skipped=0" in result.output
    assert "act: enqueued=0 skipped=0" in result.output
