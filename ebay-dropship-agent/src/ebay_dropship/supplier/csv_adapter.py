from ebay_dropship.supplier import SupplierAdapter, SupplierStock


class CsvSupplierAdapter(SupplierAdapter):
    """SUPPLIER_CSV_PATH を読み取ってサプライヤー在庫を取得する(Phase 5 で実装)。"""

    def __init__(self, csv_path: str):
        self.csv_path = csv_path

    def fetch_stock(self, sku: str) -> SupplierStock:
        raise NotImplementedError("Phase 5 で実装")

    def fetch_all_stock(self) -> list[SupplierStock]:
        raise NotImplementedError("Phase 5 で実装")
