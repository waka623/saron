"""承認 UI(CLI)。approval/ の状態遷移を store.SqlProposalRepository 経由で操作する薄い層。

使い方:
    ebay-dropship proposals list
    ebay-dropship proposals approve <id> --by <name>
    ebay-dropship proposals reject <id> --by <name> --reason "..."
    ebay-dropship cycle run-once [--demo]
    ebay-dropship demo seed
    ebay-dropship api serve

`--demo`/`demo seed` は実キー・実発注を一切使わないデモ専用の経路(README「Quickstart(デモ)」参照)。
"""

from __future__ import annotations

from contextlib import contextmanager

import click

from ebay_dropship.alerts import LoggingNotifier
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
@click.option(
    "--demo",
    is_flag=True,
    default=False,
    help="demo.pyのフィクスチャ(架空SKU/listing)でPlan/Actを実行する。実キー・実発注は使わない。",
)
def run_cycle_once(demo: bool) -> None:
    """Plan→Check→Actを1回実行し、提案を承認キューに積む(手動「今すぐ1回実行」)。

    重要: publish/price_change/purchase の実行は行わない。積まれた提案は
    `ebay-dropship proposals approve` で人間が承認した後、別途Doフェーズが実行する。

    現時点ではPlan/Actの対象(どのSKU/listingを評価するか)の自動列挙は未統合(将来の統合ポイント。
    DECISIONS.md参照)。`--demo` を付けない既定動作は空のタスクリストのままで、サイクル機構自体の
    動作確認のみ行う(従来通り)。`--demo` を付けると `demo.py` の架空SKU/listingフィクスチャで
    実際にproposalsが生成される様子を確認できる(README「Quickstart(デモ)」参照。事前に
    `ebay-dropship demo seed` でサプライヤーCSVを用意しておくこと)。
    """
    with _session() as session:
        repo = SqlProposalRepository(session)
        if demo:
            from ebay_dropship.demo import (
                build_demo_act_tasks,
                build_demo_plan_tasks,
                build_demo_supplier,
            )

            supplier = build_demo_supplier(settings)
            plan_tasks = build_demo_plan_tasks(settings)
            act_tasks = build_demo_act_tasks(settings, supplier)
        else:
            plan_tasks, act_tasks = [], []
        result = run_cycle(repository=repo, plan_tasks=plan_tasks, act_tasks=act_tasks, notifier=LoggingNotifier())
    click.echo(
        f"plan: enqueued={len(result.plan_enqueued)} skipped={len(result.plan_skipped)} | "
        f"act: enqueued={len(result.act_enqueued)} skipped={len(result.act_skipped)} | "
        f"errors={len(result.errors)}"
    )
    for proposal in [*result.plan_enqueued, *result.act_enqueued]:
        click.echo(
            f"  [{proposal.id}] {proposal.proposal_type.value} priority={proposal.priority.value} "
            f"profit={proposal.estimated_profit} — {proposal.summary}"
        )
    for exc in result.errors:
        click.echo(f"  error: {exc}", err=True)


@cli.group()
def demo() -> None:
    """実キー・実発注を使わない安全なデモ用コマンド(README「Quickstart(デモ)」参照)。"""


@demo.command("seed")
def demo_seed() -> None:
    """デモ用サプライヤーCSVを`settings.supplier_csv_path`に書く(冪等、何度でも再実行可)。"""
    from ebay_dropship.demo import seed_demo_supplier_csv

    path = seed_demo_supplier_csv(settings.supplier_csv_path)
    click.echo(f"seeded demo supplier CSV: {path}")


@cli.group()
def api() -> None:
    pass


@api.command("serve")
@click.option("--host", default=None, help="既定は settings.approval_api_host(127.0.0.1)")
@click.option("--port", default=None, type=int, help="既定は settings.approval_api_port(8000)")
def serve_api(host: str | None, port: int | None) -> None:
    """承認Web UI(FastAPI)を起動する。既定でlocalhostのみにバインドする。"""
    from ebay_dropship.api import run_api

    run_api(host=host, port=port)


if __name__ == "__main__":
    cli()
