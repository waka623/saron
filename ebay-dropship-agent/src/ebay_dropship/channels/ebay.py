"""既存の `EbayClient` を `SalesChannel` インターフェースでラップするだけの実装(S0)。

ロジックは一切変更せず、`adapters/ebay/client.py::EbayClient` の対応メソッドへそのまま
委譲する(移動のみ)。例外(`EbayApiError`/`EbayOfferAlreadyExistsError`)もそのまま伝播する。
"""

from __future__ import annotations

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.channels.base import SalesChannel


class EbayChannel(SalesChannel):
    def __init__(self, client: EbayClient):
        self._client = client

    def create_or_update_inventory_item(self, sku: str, payload: dict) -> dict:
        return self._client.create_or_update_inventory_item(sku, payload)

    def create_offer(self, sku: str, payload: dict) -> dict:
        return self._client.create_offer(sku, payload)

    def publish_offer(self, offer_id: str) -> dict:
        return self._client.publish_offer(offer_id)

    def update_offer(self, offer_id: str, payload: dict) -> dict:
        return self._client.update_offer(offer_id, payload)

    def get_item_aspects_for_category(self, category_id: str) -> list[dict]:
        return self._client.get_item_aspects_for_category(category_id)

    def get_orders(self, since: str | None = None) -> list[dict]:
        return self._client.get_orders(since=since)

    def submit_fulfillment(self, order_id: str, tracking: dict) -> dict:
        """S2で`SalesChannel`に追加されたメソッド。このコードベースの`EbayClient`は

        Fulfillment APIの書き込み(発送情報の反映)に対応していない(読み取り専用の
        `get_orders`のみ実装済み)ため、明確な理由付きで未実装として送出する。
        eBayの既存挙動(get_orders等)はこの追加による影響を一切受けない。
        """
        raise NotImplementedError(
            "EbayChannel.submit_fulfillment: このコードベースのEbayClientはFulfillment APIの"
            "書き込み(発送情報の反映)に未対応です(読み取り専用のget_ordersのみ実装済み)。"
            "eBayへ追跡番号を反映する場合は、EbayClientにcreateShippingFulfillment相当の"
            "書き込みメソッドを追加したうえで、ここに委譲する実装が必要です。"
        )
