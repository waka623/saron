"""発注実行チャネル。

CSV仕入れ先には通常、自動発注APIが無い。既定実装 `ManualOrderPurchaseChannel` は、
どこにも自動送信せず「発注パケット」を生成・記録するだけで、実際の発注は人間が手動で行う。
実際の金銭移動を伴う自動発注はこのモジュールには実装しない
(`config.Settings.enable_automated_supplier_purchase` は常にFalseで、実サプライヤー統合と
明示的なgo-liveまで自動発注チャネルは追加しない。DECISIONS.md参照)。

将来、真の自動発注APIを持つサプライヤーと統合する場合は、この `PurchaseChannel` と同じ
インターフェースを実装した新しいクラスに差し替えるだけでよい。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PurchaseOrderPacket:
    order_id: str
    sku: str
    quantity: int
    unit_cost: Decimal
    supplier_name: str
    ship_to_country: str


@dataclass(frozen=True)
class PurchaseResult:
    status: str  # "recorded_for_manual_order" | "duplicate" | "failed"
    reference_id: str | None
    detail: str = ""


class PurchaseChannel(ABC):
    @abstractmethod
    def submit_purchase(self, packet: PurchaseOrderPacket) -> PurchaseResult: ...


class ManualOrderPurchaseChannel(PurchaseChannel):
    """既定実装。発注パケットを記録するだけ(自動送信しない)。同じorder_idの再送は冪等に扱う。"""

    def __init__(self) -> None:
        self._recorded: dict[str, PurchaseOrderPacket] = {}

    def submit_purchase(self, packet: PurchaseOrderPacket) -> PurchaseResult:
        if packet.order_id in self._recorded:
            return PurchaseResult(
                status="duplicate",
                reference_id=packet.order_id,
                detail="既に発注パケットを記録済み(冪等。二重発注はしない)。",
            )
        self._recorded[packet.order_id] = packet
        return PurchaseResult(status="recorded_for_manual_order", reference_id=packet.order_id)

    @property
    def recorded_packets(self) -> dict[str, PurchaseOrderPacket]:
        return dict(self._recorded)
