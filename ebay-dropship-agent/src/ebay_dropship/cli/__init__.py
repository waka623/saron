"""承認 UI(CLI)。approval/ の状態遷移を store.SqlProposalRepository 経由で操作する薄い層。

使い方:
    ebay-dropship proposals list
    ebay-dropship proposals approve <id> --by <name>
    ebay-dropship proposals reject <id> --by <name> --reason "..."
"""

from __future__ import annotations

from contextlib import contextmanager

import click

from ebay_dropship.config import settings
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


if __name__ == "__main__":
    cli()
