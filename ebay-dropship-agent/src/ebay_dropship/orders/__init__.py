"""AGENT_PROMPTS.md 4章「受注処理判断エージェント」(Plan的判断)。

主目的: 在庫消失・原価上昇・発送不可地域・サプライヤーデータの陳腐化(同期ラグ)・重複受注/不正データ
といった乖離を検知して purchase せず hold にすること。判断は決定論的(ルールベース)のみ、LLMは使わない。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel
from ebay_dropship.config import Settings
from ebay_dropship.config import settings as default_settings
from ebay_dropship.guardrails import check_supplier_data_freshness
from ebay_dropship.orders.models import IncomingOrder, OrderIngestResult, OrderParseError
from ebay_dropship.pod import SupplierPurchaseLineItem
from ebay_dropship.pricing import calculate_net_profit
from ebay_dropship.supplier import SupplierAdapter

# S2(2026-09-06、DECISIONS.md参照): evaluate_supplier_purchaseがPOD発注の配送先として必須とする項目。
REQUIRED_SHIPPING_ADDRESS_FIELDS: tuple[str, ...] = (
    "ship_to_name",
    "ship_to_address1",
    "ship_to_city",
    "ship_to_region",
    "ship_to_country",
    "ship_to_zip",
)

# eBay Account API 導入(将来フェーズ)までの暫定値。research/listingと同じ既定値。
DEFAULT_EBAY_FEE_PCT = Decimal(13)

# 発送不可地域(輸出規制等の理由で除外)。設定ファイル化は将来必要になれば行う。
NON_SHIPPABLE_DESTINATIONS: frozenset[str] = frozenset({"KP", "IR", "CU", "SY"})

REQUIRED_ORDER_FIELDS: tuple[str, ...] = (
    "order_id",
    "sku",
    "quantity",
    "customer_paid",
    "ship_to_country",
    "due_date",
    "assumed_supplier_cost",
)


def _parse_order(raw: dict) -> IncomingOrder:
    missing = [field for field in REQUIRED_ORDER_FIELDS if raw.get(field) in (None, "")]
    if missing:
        raise ValueError(f"必須フィールドが空です: {missing}")
    return IncomingOrder(
        order_id=raw["order_id"],
        sku=raw["sku"],
        quantity=int(raw["quantity"]),
        customer_paid=Decimal(str(raw["customer_paid"])),
        ship_to_country=raw["ship_to_country"],
        due_date=datetime.fromisoformat(raw["due_date"]),
        assumed_supplier_cost=Decimal(str(raw["assumed_supplier_cost"])),
    )


def ingest_orders(raw_orders: list[dict]) -> OrderIngestResult:
    """Fulfillment APIの生レスポンスをパースする。

    不正なレコード(必須フィールド欠落・型不正)はsync全体を落とさず隔離し、重複order_id
    (ページネーション境界や再送によるもの)は2件目以降を別枠に記録して二重処理を防ぐ。
    """
    orders: list[IncomingOrder] = []
    duplicate_order_ids: list[str] = []
    errors: list[OrderParseError] = []
    seen: set[str] = set()

    for raw in raw_orders:
        try:
            order = _parse_order(raw)
        except (KeyError, ValueError, InvalidOperation) as exc:
            errors.append(OrderParseError(raw_order=raw, reason=str(exc)))
            continue
        if order.order_id in seen:
            duplicate_order_ids.append(order.order_id)
            continue
        seen.add(order.order_id)
        orders.append(order)

    return OrderIngestResult(orders=orders, duplicate_order_ids=duplicate_order_ids, errors=errors)


def _hold(
    order: IncomingOrder,
    issue: str,
    risk: RiskLevel,
    *,
    profit: Decimal | None = None,
    supplier_cost: Decimal | None = None,
) -> Proposal:
    return Proposal(
        proposal_type=ProposalType.HOLD,
        priority=Priority.NEEDS_REVIEW,
        summary=f"注文{order.order_id}: 発注保留(要確認)。",
        rationale=issue,
        risk_level=risk,
        estimated_profit=profit,
        requires_human_approval=True,
        payload={
            "order_id": order.order_id,
            "sku": order.sku,
            "supplier_cost": supplier_cost,
            "recalculated_profit": profit,
            "eta_days": None,
            "issue": issue,
        },
    )


def evaluate_purchase(
    order: IncomingOrder,
    supplier: SupplierAdapter,
    *,
    settings: Settings = default_settings,
    fee_pct: Decimal = DEFAULT_EBAY_FEE_PCT,
    shipping_cost: Decimal = Decimal(0),
    now: datetime | None = None,
) -> Proposal:
    """新規受注1件について、サプライヤーへ発注してよいか判断する。proposal_type は purchase/hold のみ。"""
    now = now or datetime.now(UTC)

    try:
        stock = supplier.fetch_stock(order.sku)
    except KeyError:
        return _hold(order, "サプライヤーにSKUが見つかりません(在庫消失の可能性)。", RiskLevel.HIGH)

    freshness = check_supplier_data_freshness(stock.as_of, settings.supplier_data_max_age_minutes, now)
    if not freshness.passed:
        return _hold(order, f"サプライヤーデータの同期ラグを検出: {freshness.reason}", RiskLevel.MEDIUM)

    if order.ship_to_country in NON_SHIPPABLE_DESTINATIONS:
        return _hold(
            order, f"発送不可地域('{order.ship_to_country}')のため発注できません。", RiskLevel.HIGH
        )

    if stock.quantity < order.quantity:
        return _hold(
            order,
            f"サプライヤー在庫不足(在庫{stock.quantity} < 要求{order.quantity})。在庫消失の可能性。",
            RiskLevel.HIGH,
        )

    if now + timedelta(days=stock.lead_time_days) > order.due_date:
        return _hold(
            order,
            f"サプライヤー納期({stock.lead_time_days}日)が約束納期({order.due_date.isoformat()})を超過します。",
            RiskLevel.HIGH,
        )

    recalculated_profit = calculate_net_profit(order.customer_paid, stock.cost, fee_pct, shipping_cost)
    if recalculated_profit < settings.min_net_profit:
        return _hold(
            order,
            (
                f"現在原価{stock.cost}で純利益を再計算すると{recalculated_profit}"
                f"(最低純利益{settings.min_net_profit}未満)。"
                f"受注時想定原価{order.assumed_supplier_cost}から上昇している可能性。"
            ),
            RiskLevel.HIGH,
            profit=recalculated_profit,
            supplier_cost=stock.cost,
        )

    return Proposal(
        proposal_type=ProposalType.PURCHASE,
        priority=Priority.HIGH,
        summary=f"注文{order.order_id}: サプライヤーへ発注してよいと判断。",
        rationale=(
            f"在庫{stock.quantity}(要求{order.quantity})・納期{stock.lead_time_days}日で間に合う。"
            f"現在原価{stock.cost}で純利益{recalculated_profit}を確認"
            f"(受注時想定原価{order.assumed_supplier_cost}から再計算)。"
        ),
        risk_level=RiskLevel.LOW,
        estimated_profit=recalculated_profit,
        requires_human_approval=True,
        payload={
            "order_id": order.order_id,
            "sku": order.sku,
            "supplier_cost": stock.cost,
            "recalculated_profit": recalculated_profit,
            "eta_days": stock.lead_time_days,
            "issue": "",
            # 実行フェーズ(orchestrator/do.py::execute_purchase)が使う追加情報
            "quantity": order.quantity,
            "customer_paid": order.customer_paid,
            "ship_to_country": order.ship_to_country,
            "due_date": order.due_date.isoformat(),
        },
    )


# --- S2: Shopify注文 → POD(Printify等)サプライヤー発注の判断(受注処理判断エージェント、レベルB) ---
#
# 既存のevaluate_purchase(上記)とは別関数(既存のeBay/CSVサプライヤー向けロジックは変更しない)。
# pod.SupplierProviderはsubmit_order/get_fulfillmentの2メソッドのみで「現在原価を問い合わせる」
# 手段が無いため、evaluate_purchaseのような実行時の原価再検査は行えない。この関数はPlan時点で
# 判断材料(原価・配送先情報)が揃っているかだけを検査する(deny-by-default)。
#
# 1つのShopify注文が複数明細(SKU)を持つ場合、本関数は明細1件ずつ呼び出す想定
# (pod.SupplierProvider.submit_orderがorder+item=1件単位のため、粒度を合わせている)。


def _supplier_purchase_hold(shopify_order_id: str, item: SupplierPurchaseLineItem, issue: str) -> Proposal:
    return Proposal(
        proposal_type=ProposalType.HOLD,
        priority=Priority.NEEDS_REVIEW,
        summary=f"Shopify注文{shopify_order_id}: {item.sku}のPOD発注を保留(要確認)。",
        rationale=issue,
        risk_level=RiskLevel.HIGH,
        estimated_profit=None,
        requires_human_approval=True,
        payload={
            "shopify_order_id": shopify_order_id,
            "sku": item.sku,
            "quantity": item.quantity,
            "unit_cost": item.unit_cost,
            "issue": issue,
        },
    )


def evaluate_supplier_purchase(
    shopify_order_id: str,
    item: SupplierPurchaseLineItem,
    shipping_address: dict | None,
    *,
    settings: Settings = default_settings,
) -> Proposal:
    """Shopify注文の明細1件について、POD(Printify等)へ発注してよいか判断する(レベルB=承認必須)。

    proposal_type は supplier_purchase/hold のみ。deny-by-default: 配送先情報の欠落・原価上限
    (`settings.max_supplier_order_cost`)超過はhold(自動発注しない)。`enable_automated_supplier_
    purchase`フラグの値に関わらず、ここで生成した提案は`requires_human_approval=True`固定であり、
    実際の発注(`orchestrator/do.py::execute_supplier_purchase`)は人間の承認後にしか呼ばれない。
    """
    if shipping_address is None:
        return _supplier_purchase_hold(shopify_order_id, item, "配送先情報が取得できません(欠落のためhold)。")

    missing = [f for f in REQUIRED_SHIPPING_ADDRESS_FIELDS if not shipping_address.get(f)]
    if missing:
        return _supplier_purchase_hold(
            shopify_order_id, item, f"配送先情報が不足しています: {missing}(欠落のためhold)。"
        )

    total_cost = item.unit_cost * item.quantity
    if total_cost > settings.max_supplier_order_cost:
        return _supplier_purchase_hold(
            shopify_order_id,
            item,
            f"発注原価合計{total_cost}が上限{settings.max_supplier_order_cost}を超過しています。",
        )

    return Proposal(
        proposal_type=ProposalType.SUPPLIER_PURCHASE,
        priority=Priority.HIGH,
        summary=f"Shopify注文{shopify_order_id}: {item.sku}をPODへ発注してよいと判断。",
        rationale=(
            f"PODサプライヤーへの直送発注。配送先情報を確認済み。発注原価合計{total_cost}"
            f"(単価{item.unit_cost}×数量{item.quantity})は上限{settings.max_supplier_order_cost}以内。"
        ),
        risk_level=RiskLevel.LOW,
        estimated_profit=None,  # 利益判断は出品時(research.evaluate_shopify_listing_candidate)の役割
        requires_human_approval=True,
        payload={
            "shopify_order_id": shopify_order_id,
            "sku": item.sku,
            "quantity": item.quantity,
            "unit_cost": item.unit_cost,
            "total_cost": total_cost,
            "shipping_address": shipping_address,
            "issue": "",
        },
    )
