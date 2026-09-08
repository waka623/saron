"""Shopify Admin API(GraphQL)クライアント。`channels/shopify.py::ShopifyChannel`が使う操作のみ実装する。

要確認(このセッションから実Shopifyストアへ接続して検証できないため、実装前に必ずShopify公式
ドキュメントで最新化すること):
- 使用するAPIバージョン(`SHOPIFY_API_VERSION`。仮定の既定値は置いていない。設定必須)。
- 商品作成時にvariant(価格・SKU)を`productCreate`にインラインで渡せるか、あるいは
  `productVariantsBulkCreate`/`productVariantsBulkUpdate`を別途呼ぶ必要があるかは、Shopifyの
  APIバージョンにより異なりうる(近年のバージョンでvariant関連の操作が`productCreate`から
  分離される方向の変更が入っている)。本実装は`productCreate`にインラインで`variants`を渡す
  前提で書いているため、実際に使うAPIバージョンのスキーマ(GraphiQL/Admin API reference)で
  必ず確認すること。動かない場合は`productVariantsBulkCreate`/`productVariantsBulkUpdate`への
  差し替えが必要。
- 出品公開(`publish_product`)は`productUpdate(status: ACTIVE)`のみで実装している。
  ストアの販売チャネル設定によっては、別途`publishablePublish`で対象チャネル
  (例: オンラインストア)への公開が必要な場合がある。要確認。
"""

from __future__ import annotations

from ebay_dropship.adapters.shopify.transport import ShopifyTransport


class ShopifyApiError(Exception):
    pass


def _raise_on_user_errors(payload: dict, mutation_name: str) -> None:
    user_errors = payload.get(mutation_name, {}).get("userErrors") or []
    if user_errors:
        raise ShopifyApiError(f"{mutation_name}に失敗: {user_errors}")


class ShopifyClient:
    def __init__(self, transport: ShopifyTransport):
        self._transport = transport

    def _execute(self, query: str, variables: dict, mutation_name: str | None = None) -> dict:
        response = self._transport.execute(query, variables)
        if response.get("errors"):
            raise ShopifyApiError(f"GraphQLエラー: {response['errors']}")
        data = response.get("data") or {}
        if mutation_name:
            _raise_on_user_errors(data, mutation_name)
        return data

    # --- 商品作成(publish_listingの前段。まだ非公開のDRAFT状態で作る) ---
    def create_draft_product(self, title: str, description_html: str, sku: str, price: str) -> dict:
        """DRAFT状態(非公開)の商品を作成する。戻り値: {"product_id": GID, "variant_id": GID}。"""
        query = """
        mutation productCreate($input: ProductInput!) {
          productCreate(input: $input) {
            product {
              id
              variants(first: 1) { edges { node { id } } }
            }
            userErrors { field message }
          }
        }
        """
        variables = {
            "input": {
                "title": title,
                "descriptionHtml": description_html,
                "status": "DRAFT",
                "variants": [{"sku": sku, "price": price}],
            }
        }
        data = self._execute(query, variables, "productCreate")
        product = data["productCreate"]["product"]
        variant_id = product["variants"]["edges"][0]["node"]["id"]
        return {"product_id": product["id"], "variant_id": variant_id}

    # --- SKUから商品・variantを引く(create_offerがcreate_or_update_inventory_itemの結果を
    #     直接受け取れない=SalesChannelの制約[SKUだけを引数に取る]への対応) ---
    def find_by_sku(self, sku: str) -> dict | None:
        """戻り値: {"product_id": GID, "variant_id": GID} または見つからなければ None。"""
        query = """
        query findVariantBySku($query: String!) {
          productVariants(first: 1, query: $query) {
            edges { node { id product { id } } }
          }
        }
        """
        data = self._execute(query, {"query": f"sku:{sku}"})
        edges = data["productVariants"]["edges"]
        if not edges:
            return None
        node = edges[0]["node"]
        return {"product_id": node["product"]["id"], "variant_id": node["id"]}

    def get_default_variant_id(self, product_id: str) -> str:
        query = """
        query getDefaultVariant($id: ID!) {
          product(id: $id) {
            variants(first: 1) { edges { node { id } } }
          }
        }
        """
        data = self._execute(query, {"id": product_id})
        product = data.get("product")
        if not product or not product["variants"]["edges"]:
            raise ShopifyApiError(f"product_id={product_id} のvariantが見つかりません。")
        return product["variants"]["edges"][0]["node"]["id"]

    def set_variant_price(self, product_id: str, variant_id: str, price: str) -> None:
        query = """
        mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            userErrors { field message }
          }
        }
        """
        variables = {"productId": product_id, "variants": [{"id": variant_id, "price": price}]}
        self._execute(query, variables, "productVariantsBulkUpdate")

    def publish_product(self, product_id: str) -> None:
        """`status: ACTIVE`に更新する(公開)。ストア設定によっては別途チャネル公開が必要な場合がある
        (モジュールdocstring参照)。"""
        query = """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id status }
            userErrors { field message }
          }
        }
        """
        self._execute(query, {"input": {"id": product_id, "status": "ACTIVE"}}, "productUpdate")

    def get_orders(self, since: str | None = None) -> list[dict]:
        """注文一覧を取得する。呼び出し側(`ShopifyChannel`)がeBayと同じ内部表現へマッピングする。"""
        query = """
        query listOrders($query: String) {
          orders(first: 50, query: $query) {
            edges {
              node {
                id
                name
                displayFulfillmentStatus
                currentTotalPriceSet { shopMoney { amount currencyCode } }
              }
            }
          }
        }
        """
        search_query = f"created_at:>={since}" if since else None
        data = self._execute(query, {"query": search_query})
        return [edge["node"] for edge in data["orders"]["edges"]]
