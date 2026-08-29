"""実キー無し・実発注OFFで動かせる安全なデモ用のシードデータとPlan/Actタスク。

README「Quickstart(デモ)」の実体。ここで作る `plan_tasks`/`act_tasks` は
`orchestrator/cycle.py::run_cycle` にそのまま渡せる `Callable[[], Proposal]` のリストであり、
research/listing/pricing の既存ロジック(ルールベース、LLM不使用)をフィクスチャ入力で呼ぶだけで、
このモジュール自体は判断ロジックを一切持たない。

安全性: ここで作る proposal は publish/price_change のみで、いずれも
`requires_human_approval=True`(WRITE_PROPOSAL_TYPES)。承認キューに積むところまでで、
`guardrails.gateway.execute_side_effect` を経由する実行(Do)は別途 `orchestrator/do.py` の
実行関数を人間の承認後に呼ぶ場合のみ発生する ―― このモジュールはそれを一切呼ばない。
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ebay_dropship.analytics import (
    FixtureMetricsProvider,
    ListingMetricsSnapshot,
    summarize_listing_metrics,
)
from ebay_dropship.approval import Proposal
from ebay_dropship.config import Settings
from ebay_dropship.listing import generate_draft
from ebay_dropship.listing.models import ListingDraftInput
from ebay_dropship.pricing import evaluate_next_action
from ebay_dropship.pricing.models import ListingSnapshot
from ebay_dropship.research import evaluate_candidate
from ebay_dropship.research.models import MarketSnapshot, SupplierProduct
from ebay_dropship.supplier import SupplierAdapter
from ebay_dropship.supplier.csv_adapter import REQUIRED_COLUMNS, CsvSupplierAdapter

TaskFn = Callable[[], Proposal]

# デモ全体で使う架空のSKU/listing。実eBay・実サプライヤーとは無関係。
DEMO_SKU = "DEMO-SKU-1"
DEMO_LISTING_ID = "DEMO-LISTING-1"
DEMO_COST = Decimal("12.00")
DEMO_SHIPPING_COST = Decimal("4.00")


def seed_demo_supplier_csv(csv_path: str | Path, *, now: datetime | None = None) -> Path:
    """サプライヤーCSV(`CsvSupplierAdapter`が読む形式)にデモ用の1行を書く。

    `as_of` を実行時刻にすることで、いつ実行しても鮮度チェック(deny by default)に
    引っかからないようにする(固定の過去日時をコミットすると、時間が経つとデモが壊れるため)。
    実行のたびに上書きするため冪等(再実行してよい)。
    """
    now = now or datetime.now(UTC)
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerow(
            {
                "sku": DEMO_SKU,
                "cost": str(DEMO_COST),
                "quantity": 50,
                "lead_time_days": 3,
                "as_of": now.isoformat(),
            }
        )
    return path


def build_demo_plan_tasks(settings: Settings) -> list[TaskFn]:
    """Plan(research→listing)のデモタスク。相場データはMock相当の固定フィクスチャ。"""
    product = SupplierProduct(
        sku=DEMO_SKU, cost=DEMO_COST, stock=50, lead_time_days=3, category="electronics_accessories"
    )
    market = MarketSnapshot(
        median_price=Decimal("34.99"),
        competitor_count=8,
        recent_sales_30d=20,
        shipping_cost=DEMO_SHIPPING_COST,
    )
    draft_input = ListingDraftInput(
        sku=DEMO_SKU,
        product_name="Acme ワイヤレスマウス Black",
        category_id="12345",
        target_price=Decimal("34.99"),
        cost=DEMO_COST,
        shipping_cost=DEMO_SHIPPING_COST,
        lead_time_days=3,
        required_item_specifics={"Brand": "Acme", "Color": "Black"},
        base_title_keywords=["Acme", "Wireless", "Mouse"],
    )

    def research_task() -> Proposal:
        return evaluate_candidate(product, market, settings=settings)

    def listing_task() -> Proposal:
        return generate_draft(draft_input)

    return [research_task, listing_task]


def build_demo_act_tasks(settings: Settings, supplier: SupplierAdapter | None) -> list[TaskFn]:
    """Act(pricing)のデモタスク。KPIはFixtureMetricsProvider相当の固定フィクスチャ。"""
    metrics_provider = FixtureMetricsProvider(
        {
            DEMO_LISTING_ID: ListingMetricsSnapshot(
                listing_id=DEMO_LISTING_ID,
                period_days=30,
                impressions=800,
                views=60,
                watches=5,
                sold=0,
                returns=0,
            )
        }
    )

    def pricing_task() -> Proposal:
        kpi = summarize_listing_metrics(
            DEMO_LISTING_ID, metrics_provider, min_sample_views=settings.pricing_min_sample_views
        )
        snapshot = ListingSnapshot(
            listing_id=DEMO_LISTING_ID,
            current_price=Decimal("32.99"),
            cost=DEMO_COST,
            shipping_cost=DEMO_SHIPPING_COST,
            kpi=kpi,
            sku=DEMO_SKU,
        )
        return evaluate_next_action(snapshot, settings=settings, supplier=supplier)

    return [pricing_task]


def build_demo_supplier(settings: Settings) -> SupplierAdapter:
    return CsvSupplierAdapter(settings.supplier_csv_path)
