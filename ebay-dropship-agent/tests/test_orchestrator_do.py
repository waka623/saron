"""Phase 4(Do): 承認済みproposalの実行。実キー未着のため Inventory API はフェイクで代替する。

フェイクは成功専用ではなく、publish拒否(item specifics不足/ポリシー違反)・レート制限・
部分成功・重複の4failureモードを明示的に再現し、executorがエラー処理まで通ることを検証する。
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.adapters.ebay import EbayApiError, EbayClient
from ebay_dropship.approval import Priority, Proposal, ProposalStatus, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.guardrails.gateway import GuardrailDenied
from ebay_dropship.orchestrator.do import execute_price_change, execute_publish, run_do
from ebay_dropship.store import Base, SqlProposalRepository
from tests.fakes.ebay_inventory_fake import FakeInventoryBackend

SETTINGS = Settings(min_net_profit=Decimal("5.0"))


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return SqlProposalRepository(session)


@pytest.fixture()
def backend():
    return FakeInventoryBackend()


def _ebay_client(backend: FakeInventoryBackend) -> EbayClient:
    http_client = httpx.Client(transport=backend.transport())
    # sleep=lambda _s: None でリトライの実待機を無くし、レート制限テストを高速化する。
    return EbayClient("id", "secret", "refresh", http_client=http_client, retry_sleep=lambda _s: None)


def _publish_payload(**overrides) -> dict:
    defaults = {
        "sku": "X1",
        "title": "Acme ワイヤレスマウス Black",
        "description": "発送目安: ご注文から5営業日以内に発送します。",
        "category_id": "12345",
        "item_specifics": {"Brand": "Acme", "Color": "Black"},
        "list_price": Decimal("29.99"),
        "handling_time_days": 5,
    }
    defaults.update(overrides)
    return defaults


def _seed_approved_publish(repo, **payload_overrides) -> Proposal:
    proposal = Proposal(
        proposal_type=ProposalType.PUBLISH,
        priority=Priority.MEDIUM,
        summary="出品ドラフト(テスト)",
        rationale="卸サプライヤーから直送。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("10.5913"),
        requires_human_approval=True,
        payload=_publish_payload(**payload_overrides),
    )
    saved = repo.enqueue(proposal)
    return repo.approve(saved.id, decided_by="alice")


def _seed_approved_price_change(repo, **payload_overrides) -> Proposal:
    payload = {"listing_id": "A123", "ebay_offer_id": "offer-A123", "proposed_price": "27.99"}
    payload.update(payload_overrides)
    proposal = Proposal(
        proposal_type=ProposalType.PRICE_CHANGE,
        priority=Priority.MEDIUM,
        summary="値下げ提案(テスト)",
        rationale="卸サプライヤー在庫を確認済み。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("8.0"),
        requires_human_approval=True,
        payload=payload,
    )
    saved = repo.enqueue(proposal)
    return repo.approve(saved.id, decided_by="alice")


# --- publish: 成功 ---


def test_publish_success_creates_item_offer_and_publishes(repo, backend):
    proposal = _seed_approved_publish(repo)
    client = _ebay_client(backend)

    result = execute_publish(proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10)

    assert result.status == ProposalStatus.EXECUTED
    stored = repo.get(proposal.id)
    assert stored.payload["ebay_item_id"] == "X1"
    assert stored.payload["ebay_offer_id"] == "offer-X1"
    assert stored.payload["ebay_listing_id"] == "listing-offer-X1"
    assert "X1" in backend.inventory_items
    assert "offer-X1" in backend.published_offer_ids


# --- publish: 失敗モード1 — item specifics不足/ポリシー違反によるpublish拒否 ---


def test_publish_rejected_for_missing_item_specifics_marks_failed(repo, backend):
    backend.reject_publish_missing_specifics = True
    proposal = _seed_approved_publish(repo)
    client = _ebay_client(backend)

    with pytest.raises(EbayApiError, match="25007|Color"):
        execute_publish(proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10)

    stored = repo.get(proposal.id)
    assert stored.status == ProposalStatus.FAILED
    assert "publish失敗" in stored.payload["failure_reason"]
    # 手前のステップ(item/offer)は完了済みとして記録されている(中途半端な状態にしない)
    assert stored.payload["ebay_item_id"] == "X1"
    assert stored.payload["ebay_offer_id"] == "offer-X1"
    assert "ebay_listing_id" not in stored.payload


# --- publish: 失敗モード2 — レート制限 ---


def test_publish_rate_limited_on_offer_creation_marks_failed(repo, backend):
    backend.rate_limit_offer_creation = True
    proposal = _seed_approved_publish(repo)
    client = _ebay_client(backend)

    with pytest.raises(EbayApiError, match="429|失敗"):
        execute_publish(proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10)

    stored = repo.get(proposal.id)
    assert stored.status == ProposalStatus.FAILED
    assert stored.payload["ebay_item_id"] == "X1"
    assert "ebay_offer_id" not in stored.payload


# --- publish: 失敗モード3 — 部分成功(item/offerは成功、publishだけ失敗) ---


def test_publish_partial_success_preserves_created_ids_and_marks_failed(repo, backend):
    backend.fail_publish_with_status = 500
    proposal = _seed_approved_publish(repo)
    client = _ebay_client(backend)

    with pytest.raises(EbayApiError):
        execute_publish(proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10)

    stored = repo.get(proposal.id)
    assert stored.status == ProposalStatus.FAILED
    # eBay側にはinventory item・offerが実在する(部分成功) — 中途半端に EXECUTED 扱いにはしない
    assert "X1" in backend.inventory_items
    assert backend.offers.get("X1") == "offer-X1"
    assert stored.payload["ebay_item_id"] == "X1"
    assert stored.payload["ebay_offer_id"] == "offer-X1"
    assert "ebay_listing_id" not in stored.payload


# --- publish: 失敗モード4 — 重複(offer既存) ---


def test_publish_duplicate_offer_reuses_existing_and_still_publishes(repo, backend):
    backend.duplicate_offer_sku = "X1"
    proposal = _seed_approved_publish(repo)
    client = _ebay_client(backend)

    result = execute_publish(proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10)

    assert result.status == ProposalStatus.EXECUTED
    stored = repo.get(proposal.id)
    assert stored.payload["ebay_offer_id"] == "existing-offer-1"
    assert stored.payload["ebay_offer_reused"] is True
    assert "X1" not in backend.offers  # 新規offerは作られていない(冪等)
    assert "existing-offer-1" in backend.published_offer_ids


# --- publish: 冪等な再実行(中断後の再試行が完了済みステップを飛ばす) ---


def test_publish_retry_after_interrupted_attempt_skips_completed_steps(repo, backend):
    """inventory_item/offer作成後にプロセスが落ちた想定(statusはAPPROVEDのまま、payloadだけ記録済み)。"""
    proposal = _seed_approved_publish(repo, ebay_item_id="X1", ebay_offer_id="offer-X1")
    client = _ebay_client(backend)

    result = execute_publish(proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10)

    assert result.status == ProposalStatus.EXECUTED
    put_inventory_calls = [c for c in backend.calls if c == ("PUT", "/sell/inventory/v1/inventory_item/X1")]
    post_offer_calls = [c for c in backend.calls if c == ("POST", "/sell/inventory/v1/offer")]
    assert put_inventory_calls == []  # 既に完了済みなので再実行していない
    assert post_offer_calls == []


# --- publish: guardrails再検査(必須項目欠落を実行直前にも検出) ---


def test_publish_blocked_when_payload_missing_required_field_at_execution_time(repo, backend):
    proposal = _seed_approved_publish(repo, list_price=None)
    client = _ebay_client(backend)

    with pytest.raises(GuardrailDenied):
        execute_publish(proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10)

    assert backend.calls == []  # guardrailsで止まりネットワークには一切到達していない


# --- dry-run ---


def test_publish_dry_run_sends_nothing_and_leaves_status_approved(repo, backend):
    proposal = _seed_approved_publish(repo)
    client = _ebay_client(backend)

    result = execute_publish(
        proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10, dry_run=True
    )

    assert result.status == ProposalStatus.APPROVED
    assert backend.calls == []  # 認証すら行わず何も送信していない
    stored = repo.get(proposal.id)
    assert "offer_request" in stored.payload["dry_run_preview"]


# --- price_change: 成功 ---


def test_price_change_success_calls_update_offer_and_marks_executed(repo, backend):
    proposal = _seed_approved_price_change(repo)
    client = _ebay_client(backend)

    result = execute_price_change(
        proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10
    )

    assert result.status == ProposalStatus.EXECUTED
    stored = repo.get(proposal.id)
    assert stored.payload["applied_price"] == "27.99"
    assert "offer-A123" in backend.updated_offers


# --- price_change: 実行時再検査(利益ガードをもう一度通す) ---


def test_price_change_blocked_by_profit_guard_reverification_at_execution_time(repo, backend):
    proposal = _seed_approved_price_change(repo)
    # 承認後に状況が変わった想定(利益がしきい値を下回る)。gatewayが実行直前に再検査してブロックする。
    strict_settings = Settings(min_net_profit=Decimal("100.0"))
    client = _ebay_client(backend)

    with pytest.raises(GuardrailDenied):
        execute_price_change(
            proposal, repository=repo, ebay_client=client, settings=strict_settings, calls_remaining=10
        )

    assert backend.calls == []  # 利益ガードで止まり update_offer には到達していない
    assert repo.get(proposal.id).status == ProposalStatus.APPROVED  # 実行されず、状態も変わらない


# --- price_change: offer_id欠落 ---


def test_price_change_without_offer_id_fails_gracefully(repo, backend):
    proposal = _seed_approved_price_change(repo, ebay_offer_id=None)
    client = _ebay_client(backend)

    with pytest.raises(ValueError, match="ebay_offer_id"):
        execute_price_change(
            proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10
        )

    assert repo.get(proposal.id).status == ProposalStatus.FAILED


# --- price_change: dry-run ---


def test_price_change_dry_run_sends_nothing(repo, backend):
    proposal = _seed_approved_price_change(repo)
    client = _ebay_client(backend)

    result = execute_price_change(
        proposal, repository=repo, ebay_client=client, settings=SETTINGS, calls_remaining=10, dry_run=True
    )

    assert result.status == ProposalStatus.APPROVED
    assert backend.calls == []


# --- run_do: バッチ実行(publish/price_changeが混在) ---


def test_run_do_processes_all_approved_proposals(repo, backend):
    _seed_approved_publish(repo, sku="X1")
    _seed_approved_price_change(repo)

    results = run_do(repository=repo, ebay_client=_ebay_client(backend), settings=SETTINGS, calls_remaining=100)

    assert len(results) == 2
    assert all(isinstance(r, Proposal) and r.status == ProposalStatus.EXECUTED for r in results)
    assert repo.list_approved() == []  # 両方とも実行済みで承認待ちからは消える


def test_run_do_continues_after_one_failure(repo, backend):
    backend.reject_publish_missing_specifics = True
    _seed_approved_publish(repo, sku="X1")
    _seed_approved_price_change(repo)

    results = run_do(repository=repo, ebay_client=_ebay_client(backend), settings=SETTINGS, calls_remaining=100)

    assert len(results) == 2
    exceptions = [r for r in results if isinstance(r, Exception)]
    successes = [r for r in results if isinstance(r, Proposal)]
    assert len(exceptions) == 1
    assert len(successes) == 1
    assert successes[0].status == ProposalStatus.EXECUTED
