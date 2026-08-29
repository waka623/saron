"""F7の回帰テスト: 承認済みwithdraw提案が`run_do`から不可視のまま放置される問題。

adversarial security review(2026-08-29)で、`WITHDRAW`は`WRITE_PROPOSAL_TYPES`に含まれ
承認ゲートは通過するが、`run_do`にはpublish/price_change/purchaseの3分岐しかなく、
承認済みwithdraw提案を実行する経路がどこにも無いことを指摘した。実害は無い(何も実行されない)が、
`run_do`の戻り値(結果リスト)には一切現れず、承認済みのまま無期限に取り残されていることが
見えなかった(サイレントに忘れられる)。

このファイルは、承認済みwithdraw提案が`run_do`の結果に明示的に現れる(実行未実装であることが
可視化される)ことを検証する。実際のwithdraw実行(eBay側のAPI呼び出し)自体は依然として
未実装のままであり、この修正はそれを追加するものではない(実Sandbox統合まで見送り)。
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.approval import Priority, Proposal, ProposalStatus, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.orchestrator.do import WithdrawNotImplementedError, run_do
from ebay_dropship.store import Base, SqlProposalRepository
from tests.fakes.ebay_inventory_fake import FakeInventoryBackend

SETTINGS = Settings(min_net_profit=Decimal("5.0"))


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return SqlProposalRepository(session)


def _ebay_client(backend: FakeInventoryBackend) -> EbayClient:
    http_client = httpx.Client(transport=backend.transport())
    return EbayClient("id", "secret", "refresh", http_client=http_client, retry_sleep=lambda _s: None)


def _seed_approved_withdraw(repo) -> Proposal:
    proposal = Proposal(
        proposal_type=ProposalType.WITHDRAW,
        priority=Priority.MEDIUM,
        summary="出品取り下げ提案(テスト)",
        rationale="不採算のため取り下げ。",
        risk_level=RiskLevel.LOW,
        estimated_profit=None,
        requires_human_approval=True,
        payload={"ebay_offer_id": "offer-X1"},
    )
    saved = repo.enqueue(proposal)
    return repo.approve(saved.id, decided_by="alice")


def test_run_do_surfaces_approved_withdraw_as_not_implemented_instead_of_vanishing(repo):
    proposal = _seed_approved_withdraw(repo)
    backend = FakeInventoryBackend()

    results = run_do(repository=repo, ebay_client=_ebay_client(backend), settings=SETTINGS, calls_remaining=10)

    assert len(results) == 1, "承認済みwithdrawがrun_doの結果から消えている(サイレントに無視されている)"
    assert isinstance(results[0], WithdrawNotImplementedError)
    assert proposal.id in str(results[0])
    # 実行系ではないため何もeBayへ送っておらず、statusもapproved(未実行)のまま残る。
    assert backend.calls == []
    assert repo.get(proposal.id).status == ProposalStatus.APPROVED


def test_run_do_still_processes_other_proposals_alongside_pending_withdraw(repo):
    """withdrawの可視化がpublish/price_changeの通常処理を壊さないこと。"""
    from tests.test_orchestrator_do import _seed_approved_price_change

    _seed_approved_withdraw(repo)
    _seed_approved_price_change(repo)
    backend = FakeInventoryBackend()

    results = run_do(repository=repo, ebay_client=_ebay_client(backend), settings=SETTINGS, calls_remaining=10)

    assert len(results) == 2
    exceptions = [r for r in results if isinstance(r, Exception)]
    successes = [r for r in results if isinstance(r, Proposal)]
    assert len(exceptions) == 1
    assert isinstance(exceptions[0], WithdrawNotImplementedError)
    assert len(successes) == 1
    assert successes[0].status == ProposalStatus.EXECUTED
