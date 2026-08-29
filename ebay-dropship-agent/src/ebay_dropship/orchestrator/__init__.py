"""PDCA スケジューラ。PROMPT.md 第3章の4フェーズを起動し状態遷移を管理する(Phase 2〜6 で段階実装)。

書き込み系(Do フェーズの実行)は必ず guardrails を通してから実行すること。
"""

from enum import StrEnum

from ebay_dropship.adapters.ebay import EbayClient
from ebay_dropship.approval import Proposal
from ebay_dropship.config import Settings
from ebay_dropship.orchestrator.do import run_do as _run_do
from ebay_dropship.orders.purchase_channel import PurchaseChannel
from ebay_dropship.store.repository import SqlProposalRepository
from ebay_dropship.supplier import SupplierAdapter


class PdcaPhase(StrEnum):
    PLAN = "plan"
    DO = "do"
    CHECK = "check"
    ACT = "act"


class Orchestrator:
    def run_plan(self) -> None:
        raise NotImplementedError("Phase 6 でスケジューラに統合(research/listing 自体は Phase 3 で実装済み)")

    def run_do(
        self,
        *,
        repository: SqlProposalRepository,
        ebay_client: EbayClient,
        settings: Settings,
        calls_remaining: int,
        dry_run: bool = False,
        supplier: SupplierAdapter | None = None,
        purchase_channel: PurchaseChannel | None = None,
    ) -> list[Proposal | Exception]:
        """承認済み(APPROVED)の publish/price_change/purchase を実行する。実体は orchestrator/do.py。"""
        return _run_do(
            repository=repository,
            ebay_client=ebay_client,
            settings=settings,
            calls_remaining=calls_remaining,
            dry_run=dry_run,
            supplier=supplier,
            purchase_channel=purchase_channel,
        )

    def run_check(self) -> None:
        raise NotImplementedError("Phase 6 で実装(analytics 集計)")

    def run_act(self) -> None:
        raise NotImplementedError("Phase 6 で実装(pricing の改善提案生成)")

    def run_cycle(self) -> None:
        """PDCA_CYCLE(初期値: daily)の頻度でスケジューラから呼ばれる想定(Phase 6 で APScheduler に接続)。"""
        raise NotImplementedError("Phase 6 で実装")
