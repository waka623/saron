"""Shopify販路の未実装スタブ(S0)。

S0ではShopifyの実装は行わない(DECISIONS.md参照)。`CHANNEL=shopify`が明示的に選ばれない限り
既定では選ばれず(`channels/__init__.py::create_channel`)、どのメソッドも呼ばれない。

S1で実装予定: Shopify Admin API(REST/GraphQL)を使い、`SalesChannel`の各メソッドに対応する
Shopify側の操作(product/variant作成、注文取得等)へ差し替える。Shopifyには市場相場を取得できる
公式APIが無いため、利益ガードは(eBayのようなBrowse APIベースの相場推定ではなく)自己設定価格
ベースに簡素化する想定(DECISIONS.md参照)。需要・競合の自動判定や集客はコード外(別途広告・SNS
運用等で対応)とする想定。
"""

from __future__ import annotations

from ebay_dropship.channels.base import SalesChannel

_NOT_IMPLEMENTED = "ShopifyChannel は未実装です(S1で実装予定。DECISIONS.md参照)。"


class ShopifyChannel(SalesChannel):
    def create_or_update_inventory_item(self, sku: str, payload: dict) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def create_offer(self, sku: str, payload: dict) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def publish_offer(self, offer_id: str) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def update_offer(self, offer_id: str, payload: dict) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def get_item_aspects_for_category(self, category_id: str) -> list[dict]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    def get_orders(self, since: str | None = None) -> list[dict]:
        raise NotImplementedError(_NOT_IMPLEMENTED)
