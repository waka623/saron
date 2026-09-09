"""Printify(POD)アダプタ(S2)。`pod/__init__.py::SupplierProvider`の実装。"""

from __future__ import annotations

from ebay_dropship.adapters.printify.client import PrintifyApiError, PrintifyClient
from ebay_dropship.adapters.printify.provider import PrintifyProvider
from ebay_dropship.config import Settings
from ebay_dropship.pod import SupplierProvider

__all__ = ["PrintifyApiError", "PrintifyClient", "PrintifyProvider", "create_supplier_provider"]


def create_supplier_provider(settings: Settings) -> SupplierProvider | None:
    """S3: 設定からPrintifyProviderを組み立てる(`channels.create_channel`と同じ方針)。

    認証情報(`printify_api_token`/`printify_shop_id`)が未設定ならNoneを返す
    (fail-safe: 未設定のまま自走ループがPOD発注を試みて実行時エラーになるより、呼び出し側
    〈orchestrator/autopilot.py〉がNoneを見てsupplier_purchase関連の処理を丸ごとスキップする
    方が安全。`orchestrator/do.py::run_do`が`supplier_provider=None`のときsupplier_purchaseを
    スキップする既存の挙動と揃えている)。
    """
    if not settings.printify_api_token or not settings.printify_shop_id:
        return None
    return PrintifyProvider(PrintifyClient(settings.printify_api_token, settings.printify_shop_id))
