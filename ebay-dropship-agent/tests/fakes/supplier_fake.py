"""テスト用の簡易 SupplierAdapter 実装。"""

from __future__ import annotations

from ebay_dropship.supplier import SupplierAdapter, SupplierStock


class FakeSupplierAdapter(SupplierAdapter):
    def __init__(self, stocks: dict[str, SupplierStock]):
        self._stocks = stocks

    def fetch_stock(self, sku: str) -> SupplierStock:
        if sku not in self._stocks:
            raise KeyError(sku)
        return self._stocks[sku]

    def fetch_all_stock(self) -> list[SupplierStock]:
        return list(self._stocks.values())
