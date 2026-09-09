"""S3: スケジュール自走ループ(`orchestrator/autopilot.py::run_autopilot_cycle`)のend-to-endテスト。

実Shopify/実Printifyへは接続しない(FakeShopifyTransport/FakePrintifyBackend使用)。

レベルB方針が本当に守られていることを直接検証する主目的のテスト群:
  - publish(お金が動かない)は自走が有効なら自動承認され、そのまま実行(EXECUTED)まで進む。
  - supplier_purchase(お金が動く)は、自走の設定に関わらず常に承認待ち(PENDING)で止まる。
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.adapters.printify.client import PrintifyClient
from ebay_dropship.adapters.printify.provider import PrintifyProvider
from ebay_dropship.adapters.shopify.client import ShopifyClient
from ebay_dropship.alerts import Alert, Notifier
from ebay_dropship.approval import Priority, Proposal, ProposalStatus, ProposalType, RiskLevel
from ebay_dropship.channels.shopify import ShopifyChannel
from ebay_dropship.config import Settings
from ebay_dropship.orchestrator.autopilot import make_order_to_supplier_items, run_autopilot_cycle
from ebay_dropship.orders import evaluate_supplier_purchase
from ebay_dropship.pod import SupplierPurchaseLineItem
from ebay_dropship.store import Base, SqlProposalRepository
from tests.fakes.printify_fake import FakePrintifyBackend
from tests.fakes.shopify_transport_fake import FakeShopifyTransport

PRODUCT_GID = "gid://shopify/Product/1"
VARIANT_GID = "gid://shopify/ProductVariant/1"
ORDER_GID = "gid://shopify/Order/1"
FULFILLMENT_ORDER_GID = "gid://shopify/FulfillmentOrder/1"

RAW_SHOPIFY_ADDRESS = {
    "name": "Jane Doe",
    "address1": "123 Main St",
    "city": "Springfield",
    "provinceCode": "IL",
    "countryCodeV2": "US",
    "zip": "62701",
}

VALID_ADDRESS = {
    "ship_to_name": "Jane Doe",
    "ship_to_address1": "123 Main St",
    "ship_to_city": "Springfield",
    "ship_to_region": "IL",
    "ship_to_country": "US",
    "ship_to_zip": "62701",
}


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return SqlProposalRepository(session)


class RecordingNotifier(Notifier):
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def notify(self, alert: Alert) -> None:
        self.alerts.append(alert)

    def categories(self) -> list[str]:
        return [a.category for a in self.alerts]


def _shopify_handler(*, order_line_items: list[dict] | None = None):
    def handler(query: str, variables: dict) -> dict:
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
            return {
                "data": {
                    "productVariants": {
                        "edges": [{"node": {"id": VARIANT_GID, "product": {"id": PRODUCT_GID}}}]
                    }
                }
            }
        if "productVariantsBulkUpdate" in query:
            return {"data": {"productVariantsBulkUpdate": {"userErrors": []}}}
        if "productUpdate" in query:
            return {"data": {"productUpdate": {"product": {"id": PRODUCT_GID, "status": "ACTIVE"}, "userErrors": []}}}
        if "getDefaultVariant" in query:
            return {"data": {"product": {"variants": {"edges": [{"node": {"id": VARIANT_GID}}]}}}}
        if "listOrders" in query:
            edges = []
            if order_line_items is not None:
                edges = [
                    {
                        "node": {
                            "id": ORDER_GID,
                            "name": "#1001",
                            "displayFulfillmentStatus": "UNFULFILLED",
                            "currentTotalPriceSet": {"shopMoney": {"amount": "25.00", "currencyCode": "USD"}},
                            "shippingAddress": RAW_SHOPIFY_ADDRESS,
                            "lineItems": {"edges": [{"node": item} for item in order_line_items]},
                        }
                    }
                ]
            return {"data": {"orders": {"edges": edges}}}
        if "getFulfillmentOrder" in query:
            return {"data": {"order": {"fulfillmentOrders": {"edges": [{"node": {"id": FULFILLMENT_ORDER_GID}}]}}}}
        if "fulfillmentCreate" in query:
            return {
                "data": {
                    "fulfillmentCreate": {
                        "fulfillment": {"id": "gid://shopify/Fulfillment/1", "status": "SUCCESS"},
                        "userErrors": [],
                    }
                }
            }
        raise AssertionError(f"unexpected query: {query}")

    return handler


def _channel(order_line_items: list[dict] | None = None) -> ShopifyChannel:
    return ShopifyChannel(ShopifyClient(FakeShopifyTransport(_shopify_handler(order_line_items=order_line_items))))


def _publish_payload(sku: str = "SHOP-SKU-1", **overrides) -> dict:
    defaults = {
        "sku": sku,
        "title": "Acme Widget",
        "description": "説明文",
        "category_id": "n/a",
        "item_specifics": {"Brand": "Acme"},
        "list_price": Decimal("19.99"),
        "handling_time_days": 3,
    }
    defaults.update(overrides)
    return defaults


def _seed_pending_publish(repo, sku: str = "SHOP-SKU-1", **payload_overrides) -> Proposal:
    proposal = Proposal(
        proposal_type=ProposalType.PUBLISH,
        priority=Priority.MEDIUM,
        summary=f"{sku}を出品",
        rationale="卸サプライヤーから直送。",
        risk_level=RiskLevel.LOW,
        estimated_profit=Decimal("10.0"),
        requires_human_approval=True,
        payload=_publish_payload(sku=sku, **payload_overrides),
    )
    return repo.enqueue(proposal)


def _printify_provider(backend: FakePrintifyBackend) -> PrintifyProvider:
    return PrintifyProvider(PrintifyClient("token", "shop-1", http_client=httpx.Client(transport=backend.transport())))


# --- レベルBの核心: publishは自動承認され得るが、supplier_purchaseは絶対に自動承認され得ない ---


def test_autonomy_enabled_auto_approves_and_executes_publish_but_not_supplier_purchase(repo):
    """1サイクル: publish自動承認は走るが supplier_purchase は承認待ちで止まる、を明示検証する。"""
    settings = Settings(autonomy_enabled=True, auto_approve_publish=True, max_supplier_order_cost=Decimal("50.00"))
    _seed_pending_publish(repo)
    channel = _channel(order_line_items=[{"sku": "MUG-1", "quantity": 1}])
    notifier = RecordingNotifier()

    result = run_autopilot_cycle(
        repository=repo,
        channel=channel,
        settings=settings,
        calls_remaining=10,
        order_to_items=make_order_to_supplier_items(lambda sku: Decimal("12.50")),
        dry_run=False,
        notifier=notifier,
    )

    # publishは自動承認され、そのまま実行(EXECUTED)まで進む。
    assert len(result.auto_approved) == 1
    assert result.auto_approved[0].proposal_type is ProposalType.PUBLISH
    assert len(result.do_results) == 1
    assert isinstance(result.do_results[0], Proposal)
    assert result.do_results[0].status is ProposalStatus.EXECUTED

    # supplier_purchaseは新規に積まれるが、絶対に自動承認されない(PENDINGのまま)。
    assert len(result.supplier_purchase_enqueued) == 1
    sp = result.supplier_purchase_enqueued[0]
    assert sp.proposal_type is ProposalType.SUPPLIER_PURCHASE
    assert sp.status is ProposalStatus.PENDING
    assert repo.get(sp.id).status is ProposalStatus.PENDING  # DB上でも再確認
    assert result.pending_supplier_purchase_count == 1

    assert "auto_approved" in notifier.categories()
    assert "supplier_purchase_pending_approval" in notifier.categories()


def test_autonomy_disabled_by_default_does_not_auto_approve_anything(repo):
    """既定(autonomy_enabled=False)では自動承認が一切行われない(S3以前と同じ挙動)。"""
    settings = Settings()  # 既定値のまま
    pending = _seed_pending_publish(repo)

    result = run_autopilot_cycle(repository=repo, channel=_channel(), settings=settings, calls_remaining=10)

    assert result.auto_approved == []
    assert result.do_results == []
    assert repo.get(pending.id).status is ProposalStatus.PENDING


def test_kill_switch_overrides_autonomy_enabled(repo):
    """kill-switchはautonomy_enabled/auto_approve_publishの値に関わらず自動承認を止める。"""
    settings = Settings(autonomy_enabled=True, auto_approve_publish=True, autonomy_kill_switch=True)
    pending = _seed_pending_publish(repo)

    result = run_autopilot_cycle(repository=repo, channel=_channel(), settings=settings, calls_remaining=10)

    assert result.auto_approved == []
    assert repo.get(pending.id).status is ProposalStatus.PENDING


def test_auto_approve_publish_flag_off_does_not_auto_approve_even_if_autonomy_enabled(repo):
    """autonomy_enabled=Trueでもauto_approve_publish=False(既定)なら自動承認しない。"""
    settings = Settings(autonomy_enabled=True, auto_approve_publish=False)
    pending = _seed_pending_publish(repo)

    result = run_autopilot_cycle(repository=repo, channel=_channel(), settings=settings, calls_remaining=10)

    assert result.auto_approved == []
    assert repo.get(pending.id).status is ProposalStatus.PENDING


def test_max_auto_actions_per_run_caps_auto_approval(repo):
    """1回のrunで自動承認してよい件数の上限を超えない。"""
    settings = Settings(autonomy_enabled=True, auto_approve_publish=True, max_auto_actions_per_run=1)
    _seed_pending_publish(repo, sku="SHOP-SKU-1")
    _seed_pending_publish(repo, sku="SHOP-SKU-2")

    result = run_autopilot_cycle(repository=repo, channel=_channel(), settings=settings, calls_remaining=10, dry_run=True)

    assert len(result.auto_approved) == 1
    statuses = {p.status for p in repo.list_pending()} | {p.status for p in repo.list_approved()}
    pending_count = len(repo.list_pending())
    approved_count = len(repo.list_approved())
    assert pending_count == 1  # 上限を超えた分はPENDINGのまま
    assert approved_count == 1  # dry_run=Trueなのでexecuteはされずapprovedのまま
    assert statuses == {ProposalStatus.PENDING, ProposalStatus.APPROVED}


def test_order_ingestion_is_idempotent_across_cycles(repo):
    """同じ注文明細に対して複数サイクル回しても重複したsupplier_purchase提案を作らない(冪等)。"""
    settings = Settings(max_supplier_order_cost=Decimal("50.00"))
    channel = _channel(order_line_items=[{"sku": "MUG-1", "quantity": 1}])
    order_to_items = make_order_to_supplier_items(lambda sku: Decimal("12.50"))

    first = run_autopilot_cycle(
        repository=repo, channel=channel, settings=settings, calls_remaining=10, order_to_items=order_to_items
    )
    second = run_autopilot_cycle(
        repository=repo, channel=channel, settings=settings, calls_remaining=10, order_to_items=order_to_items
    )

    assert len(first.supplier_purchase_enqueued) == 1
    assert first.supplier_purchase_skipped_duplicate == 0
    assert len(second.supplier_purchase_enqueued) == 0
    assert second.supplier_purchase_skipped_duplicate == 1
    assert len(repo.list_by_type(ProposalType.SUPPLIER_PURCHASE)) == 1


def test_deny_by_default_holds_when_cost_exceeds_ceiling(repo):
    """原価が上限を超える注文はsupplier_purchaseではなくholdになる(deny-by-default)。"""
    settings = Settings(max_supplier_order_cost=Decimal("5.00"))
    channel = _channel(order_line_items=[{"sku": "MUG-1", "quantity": 1}])

    result = run_autopilot_cycle(
        repository=repo,
        channel=channel,
        settings=settings,
        calls_remaining=10,
        order_to_items=make_order_to_supplier_items(lambda sku: Decimal("12.50")),
    )

    assert len(result.supplier_purchase_enqueued) == 1
    assert result.supplier_purchase_enqueued[0].proposal_type is ProposalType.HOLD


def test_previously_human_approved_supplier_purchase_executes_and_tracking_syncs(repo):
    """人間が既に承認済みのsupplier_purchaseは自走サイクルのDoフェーズで実行され、

    発送後のtrackingもShopifyへ同期される(「承認済みがあれば発注」「tracking同期」の検証)。
    """
    settings = Settings(max_supplier_order_cost=Decimal("50.00"))
    channel = _channel()  # このサイクルでは新規受注は取得しない
    backend = FakePrintifyBackend()
    provider = _printify_provider(backend)

    item = SupplierPurchaseLineItem(sku="MUG-1", quantity=1, unit_cost=Decimal("12.50"))
    proposal = evaluate_supplier_purchase(ORDER_GID, item, VALID_ADDRESS, settings=settings)
    assert proposal.proposal_type is ProposalType.SUPPLIER_PURCHASE
    saved = repo.enqueue(proposal)
    repo.approve(saved.id, decided_by="human-alice")  # 人間が事前に承認済み、という想定

    result = run_autopilot_cycle(
        repository=repo,
        channel=channel,
        settings=settings,
        calls_remaining=10,
        supplier_provider=provider,
        dry_run=False,
    )

    assert len(result.do_results) == 1
    executed = result.do_results[0]
    assert isinstance(executed, Proposal)
    assert executed.status is ProposalStatus.EXECUTED
    supplier_order_id = executed.payload["supplier_order_id"]

    # まだ未発送なのでtracking同期は「何もしない」。
    assert result.tracking_sync_results[0].payload.get("tracking_synced") is not True

    # サプライヤーが発送し、trackingが得られるようになった後の次サイクルでtrackingが同期される。
    backend.fulfillments[supplier_order_id] = {
        "status": "fulfilled",
        "shipments": [{"carrier": "USPS", "number": "9400111", "url": "https://tools.usps.com/9400111"}],
    }
    second = run_autopilot_cycle(
        repository=repo,
        channel=channel,
        settings=settings,
        calls_remaining=10,
        supplier_provider=provider,
        dry_run=False,
    )

    assert len(second.tracking_sync_results) == 1
    synced = second.tracking_sync_results[0]
    assert isinstance(synced, Proposal)
    assert synced.payload["tracking_synced"] is True
    assert synced.payload["tracking_number"] == "9400111"


def test_supplier_purchase_never_auto_approved_even_with_automation_flag_enabled(repo):
    """レベルB核心の再確認: enable_automated_supplier_purchase=Trueかつautonomy全開でも

    supplier_purchaseは自動承認されない(コード固定の許可リストがpublishのみのため)。
    """
    settings = Settings(
        autonomy_enabled=True,
        auto_approve_publish=True,
        max_auto_actions_per_run=10,
        enable_automated_supplier_purchase=True,  # 誤解を招きやすい既存フラグもTrueにしてみる
        max_supplier_order_cost=Decimal("50.00"),
    )
    channel = _channel(order_line_items=[{"sku": "MUG-1", "quantity": 1}])

    result = run_autopilot_cycle(
        repository=repo,
        channel=channel,
        settings=settings,
        calls_remaining=10,
        order_to_items=make_order_to_supplier_items(lambda sku: Decimal("12.50")),
    )

    sp = result.supplier_purchase_enqueued[0]
    assert sp.proposal_type is ProposalType.SUPPLIER_PURCHASE
    assert sp.status is ProposalStatus.PENDING
    assert sp.id not in [p.id for p in result.auto_approved]
    assert all(p.proposal_type is ProposalType.PUBLISH for p in result.auto_approved)
