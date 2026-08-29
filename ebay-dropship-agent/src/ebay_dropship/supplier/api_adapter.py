from ebay_dropship.supplier import SupplierAdapter, SupplierStock


class ApiSupplierAdapter(SupplierAdapter):
    """SUPPLIER_API_BASE_URL 経由でサプライヤー在庫を取得する(将来追加。CsvSupplierAdapter と同じ契約)。"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def fetch_stock(self, sku: str) -> SupplierStock:
        raise NotImplementedError("サプライヤーAPI仕様確定後に実装")

    def fetch_all_stock(self) -> list[SupplierStock]:
        raise NotImplementedError("サプライヤーAPI仕様確定後に実装")
