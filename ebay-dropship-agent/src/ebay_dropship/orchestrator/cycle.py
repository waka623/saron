"""Phase 6: Plan→Check→Actを1回回す run_cycle。

最重要の境界: run_cycle は判断結果(Proposal)を承認キュー(proposals テーブル)に積むところまでしか
行わない。publish/price_change/purchase の実行(外部副作用)は、人間の承認を経て
orchestrator/do.py 側の実行関数群が別途行う。
run_cycle はそれらを一切呼ばない・参照しない(このファイルは orchestrator/do.py を import しない)ことで
構造的に保証する
(`tests/test_orchestrator_cycle.py::test_cycle_module_never_references_do_phase_execution` で静的に検査)。

スケジュール自動化(このモジュール・orchestrator/scheduler.py)は承認の自動化ではない。

Check(analytics による KPI 集計)は plan_tasks/act_tasks を組み立てる呼び出し側の責務とする。
run_cycle 自体は KPI 取得や外部 I/O を持たず、渡された判断関数(research/listing/pricing の
evaluate_* 呼び出しを包んだ callable)を順に実行するだけの薄いランナーにする。

proposal_type=none(アクション不要)の結果は承認キューに積まない。これにより、同じ対象への
重複した「何もしない」提案で承認キューを汚さず、pricing側の重複排除・クールダウン判定とあわせて
承認待ちリストが実際にアクションを要するものだけになるようにしている。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ebay_dropship.approval import Proposal, ProposalType
from ebay_dropship.store.repository import SqlProposalRepository

TaskFn = Callable[[], Proposal]


@dataclass
class CycleResult:
    plan_enqueued: list[Proposal] = field(default_factory=list)
    plan_skipped: list[Proposal] = field(default_factory=list)
    act_enqueued: list[Proposal] = field(default_factory=list)
    act_skipped: list[Proposal] = field(default_factory=list)
    errors: list[Exception] = field(default_factory=list)


def _run_tasks(
    tasks: list[TaskFn], repository: SqlProposalRepository, errors: list[Exception]
) -> tuple[list[Proposal], list[Proposal]]:
    enqueued: list[Proposal] = []
    skipped: list[Proposal] = []
    for task in tasks:
        try:
            proposal = task()
        except Exception as exc:  # noqa: BLE001 - 1タスクの失敗でサイクル全体を止めない
            errors.append(exc)
            continue
        if proposal.proposal_type is ProposalType.NONE:
            skipped.append(proposal)
            continue
        enqueued.append(repository.enqueue(proposal))
    return enqueued, skipped


def run_cycle(
    *,
    repository: SqlProposalRepository,
    plan_tasks: list[TaskFn] | None = None,
    act_tasks: list[TaskFn] | None = None,
) -> CycleResult:
    """plan_tasks(research/listing相当)→act_tasks(pricing相当)の順に実行し、承認キューに積む。"""
    errors: list[Exception] = []
    plan_enqueued, plan_skipped = _run_tasks(plan_tasks or [], repository, errors)
    act_enqueued, act_skipped = _run_tasks(act_tasks or [], repository, errors)
    return CycleResult(
        plan_enqueued=plan_enqueued,
        plan_skipped=plan_skipped,
        act_enqueued=act_enqueued,
        act_skipped=act_skipped,
        errors=errors,
    )
