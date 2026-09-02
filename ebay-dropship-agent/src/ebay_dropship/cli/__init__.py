"""承認 UI(CLI)。approval/ の状態遷移を store.SqlProposalRepository 経由で操作する薄い層。

使い方:
    ebay-dropship proposals list
    ebay-dropship proposals approve <id> --by <name>
    ebay-dropship proposals reject <id> --by <name> --reason "..."
    ebay-dropship cycle run-once [--demo]
    ebay-dropship demo seed
    ebay-dropship sandbox check-auth / get-orders / rate-limits / seed-test-item / execute-publish
    ebay-dropship api serve

`--demo`/`demo seed` は実キー・実発注を一切使わないデモ専用の経路(README「Quickstart(デモ)」参照)。
`sandbox` サブコマンドは.envに設定した実eBay Sandboxキーを使って実際に疎通する(EBAY_ENV=production
では実行を拒否する。Sandbox専用)。
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

import click

from ebay_dropship.alerts import LoggingNotifier
from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
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


def _require_sandbox_env() -> None:
    """`sandbox`サブコマンドはSandbox専用。EBAY_ENV=productionでは実行そのものを拒否する。"""
    if settings.ebay_env == "production":
        raise click.ClickException(
            "EBAY_ENV=production では `sandbox` サブコマンドを実行できません"
            "(実キー・実発注の誤操作防止のため、Sandbox専用のコマンドです)。"
        )


@cli.group()
def sandbox() -> None:
    """実eBay Sandboxへの疎通確認コマンド群(.envのSandboxキーを使用。EBAY_ENV=productionでは拒否)。

    どのコマンドもアクセストークンの値自体を出力しない(コピー&ペーストで意図せず流出しないため)。
    """


@sandbox.command("check-auth")
def sandbox_check_auth() -> None:
    """OAuth(refresh_tokenフロー)でアクセストークンが取得できるか確認する。トークン自体は出力しない。"""
    _require_sandbox_env()
    from ebay_dropship.adapters.ebay import EbayAuthError, EbayClient

    client = EbayClient.from_settings(settings)
    try:
        token = client.get_access_token()
    except EbayAuthError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"OK: Sandboxアクセストークンを取得(長さ={len(token)}文字。値自体は表示しません)。")


@sandbox.command("rate-limits")
def sandbox_rate_limits() -> None:
    """Developer Analytics API の getRateLimits(読み取り専用)で残コール数を確認する。"""
    _require_sandbox_env()
    from ebay_dropship.adapters.ebay import EbayApiError, EbayClient

    client = EbayClient.from_settings(settings)
    try:
        statuses = client.get_rate_limits()
    except EbayApiError as exc:
        raise click.ClickException(str(exc)) from exc
    if not statuses:
        click.echo("レート状況を取得しましたが、返却されたAPIはありませんでした。")
        return
    for status in statuses:
        click.echo(f"  {status.api_name}: 残り{status.calls_remaining}/{status.daily_limit}")


@sandbox.command("get-orders")
@click.option("--since", default=None, help="ISO 8601形式(例: 2026-08-01T00:00:00Z)。省略時は全件。")
def sandbox_get_orders(since: str | None) -> None:
    """Fulfillment API の getOrders(読み取り専用)。購入者の個人情報は表示せず件数と概要のみ出力する。"""
    _require_sandbox_env()
    from ebay_dropship.adapters.ebay import EbayApiError, EbayClient

    client = EbayClient.from_settings(settings)
    try:
        orders = client.get_orders(since=since)
    except EbayApiError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"orders件数: {len(orders)}")
    for order in orders[:20]:
        total = order.get("pricingSummary", {}).get("total", {})
        click.echo(
            f"  orderId={order.get('orderId')} status={order.get('orderFulfillmentStatus')} "
            f"total={total.get('value')} {total.get('currency', '')}"
        )


@sandbox.command("seed-test-item")
@click.option("--sku", default="SANDBOX-TEST-1", show_default=True)
@click.option("--title", default="ebay-dropship-agent Sandbox test item", show_default=True)
@click.option(
    "--description",
    default="Sandbox E2E verification listing created by ebay-dropship-agent. Not for sale.",
    show_default=True,
)
@click.option(
    "--category-id",
    required=True,
    help="有効なeBay SandboxカテゴリID(マーケットプレイスごとに異なる。eBayのTaxonomy API/開発者ドキュメントで確認)。",
)
@click.option("--list-price", default="9.99", show_default=True)
@click.option("--handling-time-days", default=3, show_default=True, type=int)
@click.option("--brand", default="Acme", show_default=True, help="item_specificsのBrand値。")
def sandbox_seed_test_item(
    sku: str,
    title: str,
    description: str,
    category_id: str,
    list_price: str,
    handling_time_days: int,
    brand: str,
) -> None:
    """Sandbox E2E検証用のpublish提案を承認キューに積む(まだ何もeBayへ送信しない)。

    積んだ後は通常通り `ebay-dropship proposals approve <id> --by <name>` で承認し、
    `ebay-dropship sandbox execute-publish <id>` で実行する(既定はdry_run、`--live`で実送信)。
    """
    try:
        price = Decimal(list_price)
    except InvalidOperation as exc:
        raise click.ClickException(f"--list-price が数値として不正です: {list_price!r}") from exc

    payload = {
        "sku": sku,
        "title": title,
        "description": description,
        "category_id": category_id,
        "list_price": price,
        "handling_time_days": handling_time_days,
        "item_specifics": {"Brand": brand},
    }
    proposal = Proposal(
        proposal_type=ProposalType.PUBLISH,
        priority=Priority.MEDIUM,
        summary=f"Sandbox E2E検証用テスト出品({sku})",
        rationale="卸サプライヤーからの直送を想定したSandbox E2E検証用のテスト出品(実商品ではない)。",
        risk_level=RiskLevel.LOW,
        estimated_profit=None,
        requires_human_approval=True,
        payload=payload,
    )
    with _session() as session:
        saved = SqlProposalRepository(session).enqueue(proposal)
    click.echo(f"seeded: {saved.id}")
    click.echo(f"next: ebay-dropship proposals approve {saved.id} --by <your-name>")


@sandbox.command("execute-publish")
@click.argument("proposal_id")
@click.option(
    "--live",
    is_flag=True,
    default=False,
    help="指定しない場合はdry_run(送信内容の確認のみ、何もeBayへ送らない)。指定すると実際にSandboxへ送信する。",
)
@click.option("--calls-remaining", default=100, show_default=True, type=int)
def sandbox_execute_publish(proposal_id: str, live: bool, calls_remaining: int) -> None:
    """承認済みのSandbox検証用publish提案を実行する(既定でdry_run。`--live`で実際にSandboxへ送信)。"""
    _require_sandbox_env()
    from ebay_dropship.adapters.ebay import EbayApiError, EbayClient
    from ebay_dropship.guardrails.gateway import GuardrailDenied
    from ebay_dropship.orchestrator.do import execute_publish

    client = EbayClient.from_settings(settings)
    with _session() as session:
        repo = SqlProposalRepository(session)
        try:
            proposal = repo.get(proposal_id)
        except ProposalNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc
        try:
            result = execute_publish(
                proposal,
                repository=repo,
                ebay_client=client,
                settings=settings,
                calls_remaining=calls_remaining,
                dry_run=not live,
            )
        except (EbayApiError, GuardrailDenied) as exc:
            raise click.ClickException(str(exc)) from exc

    if not live:
        click.echo(f"dry-run完了(何も送信していません)。status={result.status.value}")
        click.echo("送信予定の内容:")
        click.echo(f"  {result.payload.get('dry_run_preview')}")
        click.echo(f"実際にSandboxへ送信するには: ebay-dropship sandbox execute-publish {proposal_id} --live")
    else:
        click.echo(f"実行完了。status={result.status.value}")
        click.echo(f"  ebay_item_id={result.payload.get('ebay_item_id')}")
        click.echo(f"  ebay_offer_id={result.payload.get('ebay_offer_id')}")
        click.echo(f"  ebay_listing_id={result.payload.get('ebay_listing_id')}")


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
