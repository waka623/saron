from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class IncomingOrder:
    order_id: str
    sku: str
    quantity: int
    customer_paid: Decimal
    ship_to_country: str
    due_date: datetime
    assumed_supplier_cost: Decimal  # 出品/受注時点の想定原価。判断時は信用せず現在原価で再計算する。


@dataclass(frozen=True)
class OrderParseError:
    raw_order: dict
    reason: str


@dataclass(frozen=True)
class OrderIngestResult:
    orders: list[IncomingOrder]
    duplicate_order_ids: list[str]
    errors: list[OrderParseError]
