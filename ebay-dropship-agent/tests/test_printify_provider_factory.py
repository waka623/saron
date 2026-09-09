"""S3: `adapters/printify/create_supplier_provider`(設定からのSupplierProvider組み立て)のテスト。

`channels.create_channel`と同じ方針(設定に応じて実装を選ぶ・fail-safe)。
"""

from __future__ import annotations

from ebay_dropship.adapters.printify import PrintifyProvider, create_supplier_provider
from ebay_dropship.config import Settings


def test_returns_none_when_credentials_missing():
    assert create_supplier_provider(Settings()) is None
    assert create_supplier_provider(Settings(printify_api_token="tok")) is None
    assert create_supplier_provider(Settings(printify_shop_id="shop-1")) is None


def test_returns_printify_provider_when_credentials_present():
    provider = create_supplier_provider(Settings(printify_api_token="tok", printify_shop_id="shop-1"))
    assert isinstance(provider, PrintifyProvider)
