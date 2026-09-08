"""S1: `orchestrator/do.py`の実行フロー(提案→承認→実行)がShopifyChannel経由でも

そのまま動くことのエンドツーエンドテスト(実Shopifyへは接続しない、FakeShopifyTransport使用)。

eBay版の詳細な分岐網羅は test_orchestrator_do.py が既に担保しているため、ここでは
「同じdo.pyの関数(execute_publish/execute_price_change)がchannelを差し替えるだけで
Shopifyに対しても正しく完走すること」を確認する(SalesChannel抽象の本来の目的)。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.adapters.shopify.client import ShopifyApiError, ShopifyClient
from ebay_dropship.approval import Priority, Proposal, ProposalStatus, ProposalType, RiskLevel
from ebay_dropship.channels.shopify import ShopifyChannel
from ebay_dropship.config import Settings
from ebay_dropship.guardrails import ComplianceError
from ebay_dropship.orchestrator.do import execute_price_change, execute_publish
from ebay_dropship.store import Base, SqlProposalRepository
from tests.fakes.shopify_transport_fake import FakeShopifyTransport

SETTINGS = Settings(min_net_profit=Decimal("5.0"))
PRODUCT_GID = "gid://shopify/Product/1"
VARIANT_GID = "gid://shopify/ProductVariant/1"


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return SqlProposalRepository(session)


def _happy_path_handler(query: str, variables: dict) -> dict:
    if "productCreate" in query:
        return {
            "data": {
                "productCreate": {
                    "product": {"id": PRODUCT_GID, "variants": {"edges": [{"node": {"id": VARIANT_GID}}]}},
                    "userErrors": [],
                }
            }
        }
    if "findVariantBySku" in query:
        return {"data": {"productVariants": {"edges": [{"node": {"id": VARIANT_GID, "product": {"id": PRODUCT_GID}}}]}}}
    if "productVariantsBulkUpdate" in query:
        return {"data": {"productVariantsBulkUpdate": {"userErrors": []}}}
    if "productUpdate" in query:
        return {"data": {"productUpdate": {"product": {"id": PRODUCT_GID, "status": "ACTIVE"}, "userErrors": []}}}
    if "getDefaultVariant" in query:
        return {"data": {"product": {"variants": {"edges": [{"node": {"id": VARIANT_GID}}]}}}}
    raise AssertionError(f"unexpected query: {query}")


def _channel(handler=_happy_path_handler) -> ShopifyChannel:
    return ShopifyChannel(ShopifyClient(FakeShopifyTransport(handler)))


def _publish_payload(**overrides) -> dict:
    defaults = {
        "sku": "SHOP-SKU-1",
        "title": "Acme Widget",
        "description": "説明文",
        "category_id": "n/a",  # Shopifyには存在しない概念だが、do.py側でeBay形状として組み立てられる
        "item_specifics": {"Brand": "Acme"},
        "list_price": Decimal("19.99"),
        "handling_time_days": 3,
    }
    defaults.update(overrides)
    return defaults


def _seed_approved_publish(repo, **payload_overrides) -> Proposal:
    proposal = Proposal(
        proposal_type=ProposalType.PUBLISH,
        priority=Priority.MEDIUM,
        summary="Shopify出品ドラフト(テスト)",
        rationale="卸サプライヤーから直送。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("10.0"),
        requires_human_approval=True,
        payload=_publish_payload(**payload_overrides),
    )
    saved = repo.enqueue(proposal)
    return repo.approve(saved.id, decided_by="alice")


def test_publish_dry_run_does_not_touch_shopify(repo):
    """dry_runはchannelを一切呼ばない(eBayと同じ既存の不変条件)。"""
    proposal = _seed_approved_publish(repo)
    calls: list[str] = []
    channel = ShopifyChannel(ShopifyClient(FakeShopifyTransport(lambda q, v: calls.append(q) or {})))

    result = execute_publish(proposal, repository=repo, channel=channel, settings=SETTINGS, calls_remaining=10, dry_run=True)

    assert result.status == ProposalStatus.APPROVED
    assert calls == []
    assert "offer_request" in result.payload["dry_run_preview"]


def test_publish_live_completes_through_shopify_channel(repo):
    """提案→承認→実行(--live相当)がShopifyChannelでも完走し、監査に必要な情報が記録される。"""
    proposal = _seed_approved_publish(repo)
    channel = _channel()

    result = execute_publish(proposal, repository=repo, channel=channel, settings=SETTINGS, calls_remaining=10)

    assert result.status == ProposalStatus.EXECUTED
    stored = repo.get(proposal.id)
    assert stored.payload["ebay_item_id"] == "SHOP-SKU-1"  # do.py側の命名(SKUそのもの)。eBayと同じ
    assert stored.payload["ebay_offer_id"] == PRODUCT_GID
    assert stored.payload["ebay_listing_id"] == PRODUCT_GID


def test_publish_failure_marks_proposal_failed_with_reason(repo):
    """ShopifyApiErrorもEbayApiErrorと同様にmark_failedで理由が記録されること(F3/F4と同じ監査要件)。"""
    proposal = _seed_approved_publish(repo)

    def failing_handler(query: str, variables: dict) -> dict:
        if "productCreate" in query:
            return {"data": {"productCreate": {"product": None, "userErrors": [{"field": ["title"], "message": "boom"}]}}}
        raise AssertionError("productCreateで失敗するはずなので後続は呼ばれない")

    channel = _channel(failing_handler)

    with pytest.raises(ShopifyApiError):
        execute_publish(proposal, repository=repo, channel=channel, settings=SETTINGS, calls_remaining=10)

    stored = repo.get(proposal.id)
    assert stored.status == ProposalStatus.FAILED
    assert "boom" in stored.payload["failure_reason"]


def test_price_change_live_completes_through_shopify_channel(repo):
    proposal = Proposal(
        proposal_type=ProposalType.PRICE_CHANGE,
        priority=Priority.MEDIUM,
        summary="値下げ提案(テスト)",
        rationale="卸サプライヤー在庫を確認済み。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("8.0"),
        requires_human_approval=True,
        payload={"listing_id": "L1", "ebay_offer_id": PRODUCT_GID, "proposed_price": "14.99"},
    )
    saved = repo.enqueue(proposal)
    approved = repo.approve(saved.id, decided_by="alice")
    channel = _channel()

    result = execute_price_change(approved, repository=repo, channel=channel, settings=SETTINGS, calls_remaining=10)

    assert result.status == ProposalStatus.EXECUTED
    assert repo.get(approved.id).payload["applied_price"] == "14.99"


def test_guardrail_denied_still_blocks_shopify_execution(repo):
    """安全設計は不変: 未承認proposalはShopifyChannelでも実行されない(gatewayのdeny-by-default)。"""
    proposal = Proposal(
        proposal_type=ProposalType.PUBLISH,
        priority=Priority.MEDIUM,
        summary="未承認",
        rationale="卸サプライヤーから直送。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("10.0"),
        requires_human_approval=True,
        payload=_publish_payload(),
    )
    saved = repo.enqueue(proposal)  # 承認していない(status=pending)
    channel = _channel()

    with pytest.raises(ComplianceError):
        execute_publish(saved, repository=repo, channel=channel, settings=SETTINGS, calls_remaining=10)
