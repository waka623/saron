"""Phase 6: run_cycle(Plan→Act)のテスト。承認キューに積むだけで、実行(Do)は一切行わないことを保証する。"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import ebay_dropship.orchestrator.cycle as cycle_module
from ebay_dropship.alerts import Alert, Notifier
from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.orchestrator.cycle import run_cycle
from ebay_dropship.store import Base, SqlProposalRepository


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return SqlProposalRepository(session)


def _proposal(proposal_type: ProposalType) -> Proposal:
    return Proposal(
        proposal_type=proposal_type,
        priority=Priority.MEDIUM,
        summary="s",
        rationale="卸サプライヤーからの直送",
        risk_level=RiskLevel.LOW,
        requires_human_approval=(proposal_type != ProposalType.NONE),
    )


def test_run_cycle_enqueues_actionable_proposals_from_plan_and_act(repo):
    plan_tasks = [lambda: _proposal(ProposalType.HOLD)]
    act_tasks = [lambda: _proposal(ProposalType.PRICE_CHANGE)]

    result = run_cycle(repository=repo, plan_tasks=plan_tasks, act_tasks=act_tasks)

    assert len(result.plan_enqueued) == 1
    assert len(result.act_enqueued) == 1
    assert len(repo.list_pending()) == 2


def test_run_cycle_does_not_enqueue_none_type_outcomes(repo):
    plan_tasks = [lambda: _proposal(ProposalType.NONE)]
    act_tasks = [lambda: _proposal(ProposalType.NONE)]

    result = run_cycle(repository=repo, plan_tasks=plan_tasks, act_tasks=act_tasks)

    assert result.plan_enqueued == []
    assert result.act_enqueued == []
    assert len(result.plan_skipped) == 1
    assert len(result.act_skipped) == 1
    assert repo.list_pending() == []


def test_run_cycle_continues_after_one_task_raises(repo):
    def boom():
        raise RuntimeError("research failure")

    plan_tasks = [boom, lambda: _proposal(ProposalType.HOLD)]

    result = run_cycle(repository=repo, plan_tasks=plan_tasks, act_tasks=[])

    assert len(result.errors) == 1
    assert len(result.plan_enqueued) == 1


def test_run_cycle_with_no_tasks_is_a_no_op(repo):
    result = run_cycle(repository=repo)

    assert result.plan_enqueued == []
    assert result.act_enqueued == []
    assert result.errors == []


class _SpyNotifier(Notifier):
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def notify(self, alert: Alert) -> None:
        self.alerts.append(alert)


def test_run_cycle_notifies_for_hold_proposals(repo):
    plan_tasks = [lambda: _proposal(ProposalType.HOLD)]
    spy = _SpyNotifier()

    run_cycle(repository=repo, plan_tasks=plan_tasks, act_tasks=[], notifier=spy)

    assert len(spy.alerts) == 1


def test_run_cycle_without_notifier_does_not_error(repo):
    plan_tasks = [lambda: _proposal(ProposalType.HOLD)]

    result = run_cycle(repository=repo, plan_tasks=plan_tasks, act_tasks=[])  # notifier省略

    assert len(result.plan_enqueued) == 1


def test_cycle_module_never_references_do_phase_execution():
    """run_cycleは承認キューに積むところまで。Doフェーズの実行関数を参照すらしないことを静的に検査する。

    (Phase2/4の静的バイパス検査と同じ方針: importすら無いことをソース走査で保証する)
    """
    source = pathlib.Path(cycle_module.__file__).read_text(encoding="utf-8")
    forbidden_terms = (
        "execute_publish",
        "execute_price_change",
        "execute_purchase",
        "orchestrator.do",
        "orchestrator import do",
    )
    for term in forbidden_terms:
        assert term not in source, f"run_cycle は Do フェーズの実行関数を参照してはいけない: {term}"
