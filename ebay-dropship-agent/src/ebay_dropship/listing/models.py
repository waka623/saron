from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class ListingDraftInput:
    sku: str
    product_name: str
    category_id: str
    target_price: Decimal
    cost: Decimal
    shipping_cost: Decimal
    lead_time_days: int
    required_item_specifics: dict[str, str | None]
    base_title_keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ListingCopy:
    title: str
    description: str
