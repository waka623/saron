"""承認 UI(CLI)。approval/ の ApprovalQueue を呼び出す薄い click コマンド群(Phase 2 で最初の実装)。

使い方(Phase 2 実装後):
    ebay-dropship proposals list
    ebay-dropship proposals approve <id>
    ebay-dropship proposals reject <id> --reason "..."
"""

import click


@click.group()
def cli() -> None:
    pass


@cli.group()
def proposals() -> None:
    pass


@proposals.command("list")
def list_proposals() -> None:
    raise NotImplementedError("Phase 2 で実装")


@proposals.command("approve")
@click.argument("proposal_id")
def approve_proposal(proposal_id: str) -> None:
    raise NotImplementedError("Phase 2 で実装")


@proposals.command("reject")
@click.argument("proposal_id")
@click.option("--reason", required=True)
def reject_proposal(proposal_id: str, reason: str) -> None:
    raise NotImplementedError("Phase 2 で実装")


if __name__ == "__main__":
    cli()
