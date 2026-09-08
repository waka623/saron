"""Shopify販路(S1)。`adapters/shopify/client.py::ShopifyClient`への薄い委譲だが、

`SalesChannel`のシグネチャがeBayのInventory API形状に合わせて設計されている(S0のまま。
DECISIONS.mdの「S1へ引き継ぐ論点」参照)ため、以下の橋渡しが必要になる:

1. `payload`引数はdo.py側で常にeBayのInventory API形状(`_inventory_item_payload`/
   `_offer_payload`)のまま構築される。ShopifyChannelはこの中から必要な値
   (`payload["product"]["title"]`等)を取り出す。Shopify専用の判断ロジック(利益ガード等)は
   一切ここに置かない(単なる形状変換)。
2. `create_or_update_inventory_item(sku, payload)`と`create_offer(sku, payload)`は別々の
   呼び出しで、do.py側は前者の戻り値を保存しない(`payload["ebay_item_id"] = sku`を直接代入する
   だけ)。そのためShopify側では商品をSKUで検索し直す必要がある(`ShopifyClient.find_by_sku`)。
   eBayのようにSKUをキーに直接offerを作れるわけではない(Shopifyの商品IDは作成時にShopifyが
   発行する opaque な GID のため)。
3. 公開(customer-visible)は`publish_offer`(=`productUpdate(status: ACTIVE)`)を呼んだ時点で
   初めて発生する。それまで(`create_or_update_inventory_item`/`create_offer`)は`DRAFT`のまま
   なので、eBayと同じく「承認→実行の最終ステップまでは非公開」という安全性は保たれている。
4. `get_item_aspects_for_category`はeBay Taxonomy固有の概念(カテゴリ必須アスペクト)であり、
   Shopifyには存在しない。空リストを返す(補完対象なし、というのが正しい振る舞い)。
"""

from __future__ import annotations

from ebay_dropship.adapters.shopify.client import ShopifyApiError, ShopifyClient
from ebay_dropship.channels.base import SalesChannel


class ShopifyChannel(SalesChannel):
    def __init__(self, client: ShopifyClient):
        self._client = client

    def create_or_update_inventory_item(self, sku: str, payload: dict) -> dict:
        """DRAFT状態(非公開)のShopify商品を作成する。価格は未確定のため"0.00"で仮作成し、

        `create_offer`で確定価格に更新する(それまでDRAFTなので外部には見えない)。
        """
        product = payload.get("product") or {}
        title = product.get("title") or sku
        description_html = product.get("description") or ""
        return self._client.create_draft_product(
            title=title, description_html=description_html, sku=sku, price="0.00"
        )

    def create_offer(self, sku: str, payload: dict) -> dict:
        """SKUでShopify商品を検索し、確定価格を設定する。戻り値の"offerId"はShopifyの商品GID

        (do.pyが`payload["ebay_offer_id"] = offer["offerId"]`として次のpublish_offerに渡すため)。
        """
        price = payload.get("pricingSummary", {}).get("price", {}).get("value")
        location = self._client.find_by_sku(sku)
        if location is None:
            raise ShopifyApiError(
                f"SKU={sku} に対応するShopify商品が見つかりません"
                "(create_or_update_inventory_itemが先に成功している必要があります)。"
            )
        self._client.set_variant_price(location["product_id"], location["variant_id"], str(price))
        return {"offerId": location["product_id"]}

    def publish_offer(self, offer_id: str) -> dict:
        """`offer_id`はcreate_offerが返したShopify商品GID。ここで初めて外部公開(ACTIVE)にする。"""
        self._client.publish_product(offer_id)
        return {"listingId": offer_id}

    def update_offer(self, offer_id: str, payload: dict) -> dict:
        """`offer_id`は商品GID。価格改定(price_change)提案の実行に使う。"""
        price = payload.get("pricingSummary", {}).get("price", {}).get("value")
        variant_id = self._client.get_default_variant_id(offer_id)
        self._client.set_variant_price(offer_id, variant_id, str(price))
        return {}

    def get_item_aspects_for_category(self, category_id: str) -> list[dict]:
        """Shopifyにこの概念(eBay Taxonomy固有)は無いため、常に空(補完対象なし)を返す。"""
        return []

    def get_orders(self, since: str | None = None) -> list[dict]:
        """Shopifyの注文をeBay版`get_orders()`と同じ内部表現(dict shape)にマッピングする。

        eBay版: {"orderId", "orderFulfillmentStatus", "pricingSummary": {"total": {"value", "currency"}}}。
        `orderFulfillmentStatus`の実際の値(eBay: NOT_STARTED等、Shopify: UNFULFILLED等)は
        プラットフォームごとに異なる語彙のため、Shopify側の文字列をそのまま渡す(呼び出し側が
        両プラットフォーム共通の意味を必要とする場合は別途正規化が必要。DECISIONS.md参照)。
        """
        raw_orders = self._client.get_orders(since=since)
        mapped = []
        for order in raw_orders:
            money = order.get("currentTotalPriceSet", {}).get("shopMoney", {})
            mapped.append(
                {
                    "orderId": order.get("name") or order.get("id"),
                    "orderFulfillmentStatus": order.get("displayFulfillmentStatus"),
                    "pricingSummary": {
                        "total": {
                            "value": money.get("amount"),
                            "currency": money.get("currencyCode"),
                        }
                    },
                }
            )
        return mapped
