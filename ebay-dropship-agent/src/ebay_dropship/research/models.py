from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SupplierProduct:
    sku: str
    cost: Decimal
    stock: int
    lead_time_days: int
    category: str


@dataclass(frozen=True)
class MarketSnapshot:
    median_price: Decimal | None
    competitor_count: int | None
    recent_sales_30d: int | None
    shipping_cost: Decimal
