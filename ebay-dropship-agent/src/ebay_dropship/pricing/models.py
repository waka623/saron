from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ebay_dropship.analytics import KpiSummary


@dataclass(frozen=True)
class ListingSnapshot:
    listing_id: str
    current_price: Decimal
    cost: Decimal
    shipping_cost: Decimal
    kpi: KpiSummary
    last_price_change_at: datetime | None = None  # クールダウン判定用
    has_pending_proposal: bool = False  # 重複排除用
    sku: str | None = None  # supplier併用時(在庫消失・データ陳腐化チェック用)
