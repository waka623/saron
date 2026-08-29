"""承認 UI(CLI)。approval/ の状態遷移を store.SqlProposalRepository 経由で操作する薄い層。

使い方:
    ebay-dropship proposals list
    ebay-dropship proposals approve <id> --by <name>
    ebay-dropship proposals reject <id> --by <name> --reason "..."
    ebay-dropship cycle run-once
"""

from __future__ import annotations

from contextlib import contextmanager

import click

from ebay_dropship.config import settings
from ebay_dropship.orchestrator.cycle import run_cycle
from ebay_dropship.store import (
    InvalidTransitionError,
    ProposalNotFoundError,
    SqlProposalRepository,
    create_engine_from_settings,
    create_session_factory,
)


@contextmanager
def _session():
    engine = create_engine_from_settings(settings)
    factory = create_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@click.group()
def cli() -> None:
    pass


@cli.group()
def proposals() -> None:
    pass


@proposals.command("list")
def list_proposals() -> None:
    with _session() as session:
        repo = SqlProposalRepository(session)
        for proposal in repo.list_pending():
            click.echo(
                f"[{proposal.id}] {proposal.proposal_type.value} priority={proposal.priority.value} "
                f"risk={proposal.risk_level.value} profit={proposal.estimated_profit} — {proposal.summary}"
            )


@proposals.command("approve")
@click.argument("proposal_id")
@click.option("--by", "decided_by", required=True, help="承認者")
def approve_proposal(proposal_id: str, decided_by: str) -> None:
    try:
        with _session() as session:
            proposal = SqlProposalRepository(session).approve(proposal_id, decided_by)
    except (InvalidTransitionError, ProposalNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"approved: {proposal.id} (status={proposal.status.value})")


@proposals.command("reject")
@click.argument("proposal_id")
@click.option("--by", "decided_by", required=True, help="却下者")
@click.option("--reason", required=True)
def reject_proposal(proposal_id: str, decided_by: str, reason: str) -> None:
    try:
        with _session() as session:
            proposal = SqlProposalRepository(session).reject(proposal_id, decided_by, reason)
    except (InvalidTransitionError, ProposalNotFoundError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"rejected: {proposal.id} (status={proposal.status.value})")


@cli.group()
def cycle() -> None:
    pass


@cycle.command("run-once")
def run_cycle_once() -> None:
    """Plan→Check→Actを1回実行し、提案を承認キューに積む(手動「今すぐ1回実行」)。

    重要: publish/price_change/purchase の実行は行わない。積まれた提案は
    `ebay-dropship proposals approve` で人間が承認した後、別途Doフェーズが実行する。

    現時点ではPlan/Actの対象(どのSKU/listingを評価するか)の自動列挙は未統合(将来の統合ポイント。
    DECISIONS.md参照)。このコマンドは空のタスクリストでサイクル機構自体の動作を確認できる。
    """
    with _session() as session:
        repo = SqlProposalRepository(session)
        result = run_cycle(repository=repo, plan_tasks=[], act_tasks=[])
    click.echo(
        f"plan: enqueued={len(result.plan_enqueued)} skipped={len(result.plan_skipped)} | "
        f"act: enqueued={len(result.act_enqueued)} skipped={len(result.act_skipped)} | "
        f"errors={len(result.errors)}"
    )
    for exc in result.errors:
        click.echo(f"  error: {exc}", err=True)


if __name__ == "__main__":
    cli()
