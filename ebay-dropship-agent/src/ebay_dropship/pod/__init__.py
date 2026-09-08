"""Print-on-demand(POD)サプライヤーへの発注を抽象化する`SupplierProvider`(S2)。

既存の`supplier/`(`SupplierAdapter`)とは別の関心事: あちらは卸サプライヤーの在庫・原価の
定期同期(CSV/API)、こちらは「1件の受注についてPOD印刷会社へ実際に発注し、発送状況
(追跡番号)を取得する」ための最小インターフェース。`channels/base.py::SalesChannel`と同じ
設計方針(実装差し替え可能、実ネットワークを使わないフェイクでテストする)。

インターフェースはユーザー指定どおり2メソッドのみ(`submit_order`/`get_fulfillment`)。
「現在の原価を問い合わせる」ようなメソッドは無いため、`orders.py::evaluate_supplier_purchase`は
呼び出し側が渡す原価情報のみで判断する(実行時に原価を再取得して再検査する、というeBayの
`execute_purchase`と同じ仕組みはここでは持てない。DECISIONS.md参照)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


class SupplierProviderError(Exception):
    """POD発注・履行取得に失敗したときの基底例外。個々のプロバイダはこれを継承する。"""


@dataclass(frozen=True)
class SupplierOrderItem:
    sku: str
    quantity: int


@dataclass(frozen=True)
class SupplierOrder:
    """POD発注1件分の配送先情報。`order_id`は呼び出し側(Shopify等)の注文識別子(監査用)。"""

    order_id: str
    ship_to_name: str
    ship_to_address1: str
    ship_to_city: str
    ship_to_region: str
    ship_to_country: str
    ship_to_zip: str
    ship_to_email: str = ""


@dataclass(frozen=True)
class FulfillmentInfo:
    status: str  # プロバイダごとの生の状態文字列(例: "pending" | "fulfilled")。正規化はしない
    tracking_number: str | None
    tracking_url: str | None
    carrier: str | None


class SupplierProvider(ABC):
    @abstractmethod
    def submit_order(self, order: SupplierOrder, item: SupplierOrderItem) -> str:
        """POD印刷会社へ発注する(実際にお金が動く外部副作用)。戻り値: supplier_order_id。"""
        ...

    @abstractmethod
    def get_fulfillment(self, supplier_order_id: str) -> FulfillmentInfo:
        """発送状況を取得する(読み取り専用)。まだ未発送ならtracking_numberはNone。"""
        ...


@dataclass(frozen=True)
class SupplierPurchaseLineItem:
    """`evaluate_supplier_purchase`の入力。原価はこの時点で呼び出し側が把握している値を渡す

    (SupplierProviderに原価問い合わせ手段が無いため。DECISIONS.md参照)。
    """

    sku: str
    quantity: int
    unit_cost: Decimal
