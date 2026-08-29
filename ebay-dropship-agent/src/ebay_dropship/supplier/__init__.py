"""サプライヤー在庫・価格の抽象インターフェース。連携方式(API/CSV)未定のため両対応で設計する。

すべての読み取りは `as_of`(データがいつ時点のものか)を必須で持つ。呼び出し側(orders/)は
これを鮮度チェック(`guardrails.check_supplier_data_freshness`)に使い、古いデータでの発注を防ぐ。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class SupplierStock:
    sku: str
    cost: Decimal
    quantity: int
    lead_time_days: int
    as_of: datetime


class SupplierAdapter(ABC):
    """MVP は CsvSupplierAdapter(Phase 5)。ApiSupplierAdapter は同インターフェースで後日追加。"""

    @abstractmethod
    def fetch_stock(self, sku: str) -> SupplierStock: ...

    @abstractmethod
    def fetch_all_stock(self) -> list[SupplierStock]: ...
