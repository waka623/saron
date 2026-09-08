"""S2: 受注(Shopify)→発注提案→承認→submit_order→tracking→Shopify書き戻し のend-to-endテスト。

実Shopify/実Printifyへは接続しない(FakeShopifyTransport/FakePrintifyBackend使用)。
安全設計(提案→承認→実行、deny-by-default)がSUPPLIER_PURCHASEでも保たれることを直接検証する。
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebay_dropship.adapters.printify.client import PrintifyApiError, PrintifyClient
from ebay_dropship.adapters.printify.provider import PrintifyProvider
from ebay_dropship.adapters.shopify.client import ShopifyClient
from ebay_dropship.channels.shopify import ShopifyChannel
from ebay_dropship.config import Settings
from ebay_dropship.guardrails import ComplianceError
from ebay_dropship.orchestrator.do import execute_supplier_purchase, sync_supplier_fulfillment
from ebay_dropship.orders import evaluate_supplier_purchase
from ebay_dropship.pod import SupplierPurchaseLineItem
from ebay_dropship.store import Base, SqlProposalRepository
from tests.fakes.printify_fake import FakePrintifyBackend
from tests.fakes.shopify_transport_fake import FakeShopifyTransport

SETTINGS = Settings(max_supplier_order_cost=Decimal("50.00"))
SHOPIFY_ORDER_GID = "gid://shopify/Order/1"
FULFILLMENT_ORDER_GID = "gid://shopify/FulfillmentOrder/1"

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


@pytest.fixture()
def printify_backend():
    return FakePrintifyBackend()


@pytest.fixture()
def printify_provider(printify_backend):
    return PrintifyProvider(PrintifyClient("token", "shop-1", http_client=httpx.Client(transport=printify_backend.transport())))


def _shopify_handler(query: str, variables: dict) -> dict:
    if "getFulfillmentOrder" in query:
        return {"data": {"order": {"fulfillmentOrders": {"edges": [{"node": {"id": FULFILLMENT_ORDER_GID}}]}}}}
    if "fulfillmentCreate" in query:
        return {"data": {"fulfillmentCreate": {"fulfillment": {"id": "gid://shopify/Fulfillment/1", "status": "SUCCESS"}, "userErrors": []}}}
    raise AssertionError(f"unexpected shopify query: {query}")


@pytest.fixture()
def shopify_channel():
    return ShopifyChannel(ShopifyClient(FakeShopifyTransport(_shopify_handler)))


def _seed_approved_supplier_purchase(repo, unit_cost=Decimal("12.50"), quantity=1):
    item = SupplierPurchaseLineItem(sku="MUG-1", quantity=quantity, unit_cost=unit_cost)
    proposal = evaluate_supplier_purchase(SHOPIFY_ORDER_GID, item, VALID_ADDRESS, settings=SETTINGS)
    assert proposal.proposal_type.value == "supplier_purchase"
    saved = repo.enqueue(proposal)
    return repo.approve(saved.id, decided_by="alice")


# --- 提案生成(deny-by-default) ---


def test_evaluate_supplier_purchase_denies_when_cost_exceeds_ceiling():
    item = SupplierPurchaseLineItem(sku="MUG-1", quantity=10, unit_cost=Decimal("10.00"))  # total=100 > 50

    proposal = evaluate_supplier_purchase(SHOPIFY_ORDER_GID, item, VALID_ADDRESS, settings=SETTINGS)

    assert proposal.proposal_type.value == "hold"


# --- execute_supplier_purchase ---


def test_execute_supplier_purchase_requires_approval(repo, printify_provider, shopify_channel):
    item = SupplierPurchaseLineItem(sku="MUG-1", quantity=1, unit_cost=Decimal("12.50"))
    proposal = evaluate_supplier_purchase(SHOPIFY_ORDER_GID, item, VALID_ADDRESS, settings=SETTINGS)
    unapproved = repo.enqueue(proposal)  # 承認していない

    with pytest.raises(ComplianceError):
        execute_supplier_purchase(
            unapproved, repository=repo, channel=shopify_channel, supplier_provider=printify_provider,
            settings=SETTINGS, calls_remaining=10,
        )


def test_execute_supplier_purchase_dry_run_does_not_call_printify(repo, printify_provider, printify_backend, shopify_channel):
    approved = _seed_approved_supplier_purchase(repo)

    result = execute_supplier_purchase(
        approved, repository=repo, channel=shopify_channel, supplier_provider=printify_provider,
        settings=SETTINGS, calls_remaining=10, dry_run=True,
    )

    assert result.status.value == "approved"
    assert printify_backend.calls == []
    assert "submit_order_request" in result.payload["dry_run_preview"]


def test_execute_supplier_purchase_live_submits_order_and_records_id(repo, printify_provider, printify_backend, shopify_channel):
    approved = _seed_approved_supplier_purchase(repo)

    result = execute_supplier_purchase(
        approved, repository=repo, channel=shopify_channel, supplier_provider=printify_provider,
        settings=SETTINGS, calls_remaining=10,
    )

    assert result.status.value == "executed"
    assert result.payload["supplier_order_id"] == "1"
    assert printify_backend.created_orders[0]["line_items"] == [{"sku": "MUG-1", "quantity": 1}]
    assert printify_backend.created_orders[0]["address_to"]["city"] == "Springfield"


def test_execute_supplier_purchase_failure_marks_proposal_failed(repo, shopify_channel):
    approved = _seed_approved_supplier_purchase(repo)

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text="invalid address")

    failing_client = PrintifyClient("token", "shop-1", http_client=httpx.Client(transport=httpx.MockTransport(failing_handler)))
    failing_provider = PrintifyProvider(failing_client)

    with pytest.raises(PrintifyApiError):
        execute_supplier_purchase(
            approved, repository=repo, channel=shopify_channel, supplier_provider=failing_provider,
            settings=SETTINGS, calls_remaining=10,
        )

    stored = repo.get(approved.id)
    assert stored.status.value == "failed"
    assert "POD発注失敗" in stored.payload["failure_reason"]


# --- sync_supplier_fulfillment ---


def test_sync_supplier_fulfillment_rejects_unexecuted_proposal(repo, printify_provider, shopify_channel):
    approved = _seed_approved_supplier_purchase(repo)  # まだexecuteしていない(status=approved)

    with pytest.raises(ComplianceError):
        sync_supplier_fulfillment(approved, repository=repo, channel=shopify_channel, supplier_provider=printify_provider)


def test_sync_supplier_fulfillment_does_nothing_when_not_yet_shipped(repo, printify_provider, printify_backend, shopify_channel):
    approved = _seed_approved_supplier_purchase(repo)
    executed = execute_supplier_purchase(
        approved, repository=repo, channel=shopify_channel, supplier_provider=printify_provider,
        settings=SETTINGS, calls_remaining=10,
    )

    result = sync_supplier_fulfillment(executed, repository=repo, channel=shopify_channel, supplier_provider=printify_provider)

    assert result.payload.get("tracking_synced") is not True
    assert result.payload.get("tracking_number") is None


def test_sync_supplier_fulfillment_writes_tracking_back_to_shopify_once_shipped(
    repo, printify_provider, printify_backend, shopify_channel
):
    approved = _seed_approved_supplier_purchase(repo)
    executed = execute_supplier_purchase(
        approved, repository=repo, channel=shopify_channel, supplier_provider=printify_provider,
        settings=SETTINGS, calls_remaining=10,
    )
    supplier_order_id = executed.payload["supplier_order_id"]
    printify_backend.fulfillments[supplier_order_id] = {
        "status": "fulfilled",
        "shipments": [{"carrier": "USPS", "number": "9400111", "url": "https://tools.usps.com/9400111"}],
    }

    result = sync_supplier_fulfillment(executed, repository=repo, channel=shopify_channel, supplier_provider=printify_provider)

    assert result.payload["tracking_synced"] is True
    assert result.payload["tracking_number"] == "9400111"


def test_sync_supplier_fulfillment_is_idempotent(repo, printify_provider, printify_backend, shopify_channel):
    approved = _seed_approved_supplier_purchase(repo)
    executed = execute_supplier_purchase(
        approved, repository=repo, channel=shopify_channel, supplier_provider=printify_provider,
        settings=SETTINGS, calls_remaining=10,
    )
    supplier_order_id = executed.payload["supplier_order_id"]
    printify_backend.fulfillments[supplier_order_id] = {
        "status": "fulfilled",
        "shipments": [{"carrier": "USPS", "number": "9400111", "url": "https://tools.usps.com/9400111"}],
    }
    first = sync_supplier_fulfillment(executed, repository=repo, channel=shopify_channel, supplier_provider=printify_provider)

    # Shopify側のトラッキング書き込みが2回発生しないことを確認するため、2回目はshopify_channelを
    # 呼んだら例外を送出するフェイクに差し替える(呼ばれたら壊れるようにして、冪等性を検証する)。
    def unreachable(query, variables):
        raise AssertionError("2回目はShopifyへ書き込まれないはず(冪等)")

    unreachable_channel = ShopifyChannel(ShopifyClient(FakeShopifyTransport(unreachable)))

    second = sync_supplier_fulfillment(first, repository=repo, channel=unreachable_channel, supplier_provider=printify_provider)

    assert second.payload["tracking_synced"] is True
    assert second.payload["tracking_number"] == "9400111"
