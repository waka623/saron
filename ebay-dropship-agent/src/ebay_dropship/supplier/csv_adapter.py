"""CSV経由のサプライヤー在庫連携。

内部モデル(SupplierStock)は供給元非依存にしてある。連携方式をAPIへ差し替える場合は
api_adapter.py 側で同じ SupplierAdapter インターフェースを実装するだけでよく、
呼び出し側(orders/等)のコードは一切変更不要。

不正行は sync 全体を落とさず隔離する(1行のエラーで在庫同期そのものが止まらないように)。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ebay_dropship.supplier import SupplierAdapter, SupplierStock

REQUIRED_COLUMNS: tuple[str, ...] = ("sku", "cost", "quantity", "lead_time_days", "as_of")


@dataclass(frozen=True)
class CsvRowError:
    line_number: int
    raw_row: dict
    reason: str


@dataclass
class SupplierSyncResult:
    stocks: list[SupplierStock]
    errors: list[CsvRowError] = field(default_factory=list)


def _parse_row(row: dict) -> SupplierStock:
    missing = [column for column in REQUIRED_COLUMNS if not (row.get(column) or "").strip()]
    if missing:
        raise ValueError(f"必須列が空です: {missing}")

    try:
        cost = Decimal(row["cost"])
    except InvalidOperation as exc:
        raise ValueError(f"cost が数値として不正です: {row['cost']!r}") from exc
    if cost < 0:
        raise ValueError(f"cost が負数です: {cost}")

    try:
        quantity = int(row["quantity"])
    except ValueError as exc:
        raise ValueError(f"quantity が整数として不正です: {row['quantity']!r}") from exc
    if quantity < 0:
        raise ValueError(f"quantity が負数です: {quantity}")

    try:
        lead_time_days = int(row["lead_time_days"])
    except ValueError as exc:
        raise ValueError(f"lead_time_days が整数として不正です: {row['lead_time_days']!r}") from exc
    if lead_time_days < 0:
        raise ValueError(f"lead_time_days が負数です: {lead_time_days}")

    try:
        as_of = datetime.fromisoformat(row["as_of"])
    except ValueError as exc:
        raise ValueError(f"as_of がISO 8601日時として不正です: {row['as_of']!r}") from exc

    return SupplierStock(
        sku=row["sku"], cost=cost, quantity=quantity, lead_time_days=lead_time_days, as_of=as_of
    )


class CsvSupplierAdapter(SupplierAdapter):
    """SUPPLIER_CSV_PATH を読み取ってサプライヤー在庫を取得する。

    CSVの必須列: sku, cost, quantity, lead_time_days, as_of(ISO 8601日時)。
    """

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)

    def sync(self) -> SupplierSyncResult:
        """CSV全行を読み、正常行は SupplierStock に、不正行は CsvRowError に隔離する(syncは落とさない)。"""
        stocks: list[SupplierStock] = []
        errors: list[CsvRowError] = []
        with self.csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for line_number, row in enumerate(reader, start=2):  # 1行目はヘッダー
                try:
                    stocks.append(_parse_row(row))
                except ValueError as exc:
                    errors.append(CsvRowError(line_number=line_number, raw_row=row, reason=str(exc)))
        return SupplierSyncResult(stocks=stocks, errors=errors)

    def fetch_stock(self, sku: str) -> SupplierStock:
        for stock in self.sync().stocks:
            if stock.sku == sku:
                return stock
        raise KeyError(f"サプライヤーCSVにSKU={sku}が見つかりません")

    def fetch_all_stock(self) -> list[SupplierStock]:
        return self.sync().stocks
