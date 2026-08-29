"""サプライヤー在庫・価格の抽象インターフェース。連携方式(API/CSV)未定のため両対応で設計する。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SupplierStock:
    sku: str
    cost: float
    quantity: int
    lead_time_days: int


class SupplierAdapter(ABC):
    """MVP は CsvSupplierAdapter から実装する(Phase 5)。ApiSupplierAdapter は同インターフェースで後日追加。"""

    @abstractmethod
    def fetch_stock(self, sku: str) -> SupplierStock: ...

    @abstractmethod
    def fetch_all_stock(self) -> list[SupplierStock]: ...
