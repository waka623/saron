"""PDCA スケジューラ。PROMPT.md 第3章の4フェーズを起動し状態遷移を管理する。

書き込み系(Do フェーズの実行)は必ず guardrails を通してから実行すること。

- Plan: research.evaluate_candidate / listing.generate_draft(判断関数。Phase 3で実装)
- Check: analytics.summarize_listing_metrics(KPI集計。Phase 6で実装)
- Act: pricing.evaluate_next_action(改善提案生成。Phase 6で実装)
- Do: このモジュールの run_do(承認済み提案の実行。Phase 4/5で実装)

Plan/Check/Act の1サイクル分の実行(承認キューに積むところまで)は orchestrator/cycle.py の
`run_cycle`(直接呼べる関数)が担う。スケジュール起動(いつ回すか)は orchestrator/scheduler.py の
`CycleScheduler` が薄いトリガーとして分離している。
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

