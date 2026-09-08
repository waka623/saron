"""販路(sales channel)を抽象化するインターフェース(S0で新規導入)。

背景(DECISIONS.md参照): 完成済みのeBayエージェント(利益ガード/承認ゲート/PDCA/orchestrator)は
そのまま保全し、将来Shopify等の別販路を追加できるように「orchestratorがeBayに対して呼んでいる
操作」だけを抽出したインターフェース。

**S0の方針(挙動を一切変えない)**:
- メソッド名・シグネチャ・例外は、既存の `adapters/ebay/client.py::EbayClient` の対応メソッドに
  そのまま合わせてある(`create_or_update_inventory_item` 等)。より販路中立な名前
  (例: `publish_listing`)へ抽象化することも考えられるが、Shopify側の実際のデータ形状が
  まだ分からない(S1未着手)段階でシグネチャを変えるのは「発明」にあたるため、S0では行わない。
- ここに定義するのは、`orchestrator/do.py`(Do実行)と`cli/__init__.py`の`sandbox`コマンド群が
  実際に呼んでいる操作のみ。eBay固有の診断コマンド(check-auth/rate-limits/setup-selling/
  get-refresh-token)が使うAccount API・OAuth・Taxonomy(setup-selling用)のような、Sandbox
  環境そのものの検証にしか使わない操作はここに含めない(全販路に共通する概念ではないため)。
- 例外(`EbayApiError`/`EbayOfferAlreadyExistsError`)も既存のまま呼び出し側に伝播させる。
  販路非依存の例外階層への統一はS1でShopifyの実装を見てから判断する。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SalesChannel(ABC):
    @abstractmethod
    def create_or_update_inventory_item(self, sku: str, payload: dict) -> dict: ...

    @abstractmethod
    def create_offer(self, sku: str, payload: dict) -> dict: ...

    @abstractmethod
    def publish_offer(self, offer_id: str) -> dict: ...

    @abstractmethod
    def update_offer(self, offer_id: str, payload: dict) -> dict: ...

    @abstractmethod
    def get_item_aspects_for_category(self, category_id: str) -> list[dict]: ...

    @abstractmethod
    def get_orders(self, since: str | None = None) -> list[dict]: ...
