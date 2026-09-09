"""S3: スケジュール自走ループ(レベルB)。

1サイクル =
  (1) 候補スキャン(Plan。`orchestrator/cycle.py::run_cycle`にそのまま委譲)
  (2) [自走が有効なら] publish系提案のみ自動承認(`guardrails/autonomy.py`のコード固定の
      許可リストで判定。supplier_purchase等は対象外)
  (3) 受注取得→supplier_purchase提案を生成(常に`requires_human_approval=True`固定。
      自動承認は一切行わない。冪等: 既に同じ注文明細の提案が存在すれば再作成しない)
  (4) 承認済み(自動承認されたpublish＋既に人間が承認済みだったsupplier_purchase等)をまとめて
      実行(Do。`orchestrator/do.py::run_do`にそのまま委譲。新しい実行経路は作らない。(3)で
      新たに積んだsupplier_purchaseはまだPENDINGなのでここでは実行されない)
  (5) 実行済み(EXECUTED)のsupplier_purchase提案について、発送済みならtrackingをShopifyへ同期
      (受注取得の有無に関わらず、過去のサイクルでEXECUTEDになった分もここで拾う。冪等)

レベルB(厳守): "お金が動かない"publish系のみが自動承認の対象になりうる。supplier_purchase
(発注=お金が動く)は、`settings.autonomy_enabled`/`auto_approve_publish`の値に関わらず、
このモジュールが自動承認することは無い(`guardrails.autonomy.AUTO_APPROVABLE_TYPES`にコード
固定。(2)の自動承認ステップはこのモジュール内の`_auto_approve_eligible`のみが行い、対象を
`AUTO_APPROVABLE_TYPES`でフィルタする。それ以外の場所でproposalをapproveする経路は無い)。

自動承認された提案も、他のあらゆる承認済み提案と全く同じ`guardrails.gateway.execute_side_effect`
(status==APPROVEDでなければ実行しない・利益ガード等の全guardrailを再検査する)を経由する
`orchestrator/do.py`の実行関数を通ってから実行される。自動承認ステップ自体は
`repository.approve()`でstatusをAPPROVEDに変えるだけであり、guardrailの検査を一切バイパスしない
(人間が承認ボタンを押す場合と全く同じ経路)。

安全既定: `settings.autonomy_enabled=False`(既定)の間は(2)が何もしないため、実行されるのは
「この呼び出しより前に人間が承認済みだった提案」だけになる(S3以前と同じ挙動)。
`dry_run=True`(既定)の間は`execute_*`のdry-run挙動により実際の外部API呼び出しは一切発生しない。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from ebay_dropship.alerts import (
    Alert,
    AlertSeverity,
    Notifier,
    alert_for_error,
    alert_for_supplier_purchase_pending_approval,
    notify_for_proposal,
)
from ebay_dropship.approval import Proposal, ProposalStatus, ProposalType
from ebay_dropship.channels.base import SalesChannel
from ebay_dropship.config import Settings
from ebay_dropship.guardrails.autonomy import auto_approve_publish_active, is_auto_approvable
from ebay_dropship.orchestrator.cycle import CycleResult, TaskFn, run_cycle
from ebay_dropship.orchestrator.do import run_do, sync_supplier_fulfillment
from ebay_dropship.orders import evaluate_supplier_purchase
from ebay_dropship.pod import SupplierProvider, SupplierPurchaseLineItem
from ebay_dropship.store.repository import SqlProposalRepository

logger = logging.getLogger("ebay_dropship.orchestrator.autopilot")

OrderToSupplierItems = Callable[[dict], list[SupplierPurchaseLineItem]]


def make_order_to_supplier_items(cost_lookup: Callable[[str], Decimal]) -> OrderToSupplierItems:
    """`SalesChannel.get_orders()`が返すorder dict(S2で拡張した"line_items": [{"sku","quantity"}])を

    `SupplierPurchaseLineItem`へ変換する既定のヘルパー。注文データ自体にはPOD原価が含まれない
    ため(Shopifyは自己設定価格の販路であり、原価は自前のカタログ等が持つ)、SKUごとの原価を
    引く`cost_lookup`を呼び出し側から渡してもらう(実カタログ統合はS3の範囲外。DECISIONS.md参照)。
    """

    def _convert(order: dict) -> list[SupplierPurchaseLineItem]:
        items = []
        for line in order.get("line_items") or []:
            sku = line.get("sku")
            quantity = line.get("quantity")
            if not sku or not quantity:
                continue
            items.append(SupplierPurchaseLineItem(sku=sku, quantity=quantity, unit_cost=cost_lookup(sku)))
        return items

    return _convert


@dataclass
class AutopilotCycleResult:
    plan: CycleResult
    auto_approved: list[Proposal] = field(default_factory=list)
    orders_fetched: int = 0
    supplier_purchase_enqueued: list[Proposal] = field(default_factory=list)
    supplier_purchase_skipped_duplicate: int = 0
    do_results: list[Proposal | Exception] = field(default_factory=list)
    tracking_sync_results: list[Proposal | Exception] = field(default_factory=list)
    pending_supplier_purchase_count: int = 0
    errors: list[Exception] = field(default_factory=list)

    def log_summary(self) -> None:
        """構造化ログ(件数・PASS/FAIL・pending承認数・エラー)を1行で残す(監視要件)。"""
        do_ok = sum(1 for r in self.do_results if isinstance(r, Proposal))
        do_failed = sum(1 for r in self.do_results if isinstance(r, Exception))
        tracking_ok = sum(1 for r in self.tracking_sync_results if isinstance(r, Proposal))
        tracking_failed = sum(1 for r in self.tracking_sync_results if isinstance(r, Exception))
        logger.info(
            "autopilot_cycle_result "
            "plan_enqueued=%d auto_approved=%d do_ok=%d do_failed=%d "
            "orders_fetched=%d supplier_purchase_enqueued=%d supplier_purchase_skipped_duplicate=%d "
            "tracking_synced=%d tracking_sync_failed=%d pending_supplier_purchase=%d errors=%d",
            len(self.plan.plan_enqueued) + len(self.plan.act_enqueued),
            len(self.auto_approved),
            do_ok,
            do_failed,
            self.orders_fetched,
            len(self.supplier_purchase_enqueued),
            self.supplier_purchase_skipped_duplicate,
            tracking_ok,
            tracking_failed,
            self.pending_supplier_purchase_count,
            len(self.errors),
        )


def _auto_approve_eligible(
    repository: SqlProposalRepository,
    settings: Settings,
    *,
    max_actions: int,
    notifier: Notifier | None,
) -> list[Proposal]:
    """PENDINGのうち、コード固定の許可リスト(publish系のみ)に該当するものだけを自動承認する。

    `settings.auto_approve_publish`が有効でなければ何もしない(空リストを返す)。有効でも
    `max_actions`件を超えては承認しない(暴走防止)。承認は`repository.approve()`のみで行い、
    ここでguardrailの合否を判定・シミュレーションすることはしない(実際の合否判定は
    `execute_side_effect`が実行時に行う。二重に判定ロジックを持たない)。
    """
    if not auto_approve_publish_active(settings) or max_actions <= 0:
        return []

    approved: list[Proposal] = []
    for proposal in repository.list_pending():
        if len(approved) >= max_actions:
            break
        if not is_auto_approvable(proposal.proposal_type):
            continue
        saved = repository.approve(proposal.id, decided_by="autopilot")
        logger.info("autopilot: auto-approved proposal_id=%s type=%s", saved.id, saved.proposal_type.value)
        if notifier is not None:
            notifier.notify(
                Alert(
                    category="auto_approved",
                    severity=AlertSeverity.INFO,
                    message=f"自動承認: {saved.summary}",
                    related_proposal_id=saved.id,
                )
            )
        approved.append(saved)
    return approved


def _ingest_supplier_purchase_orders(
    *,
    channel: SalesChannel,
    repository: SqlProposalRepository,
    settings: Settings,
    order_to_items: OrderToSupplierItems,
    notifier: Notifier | None,
    errors: list[Exception],
) -> tuple[int, list[Proposal], int]:
    """受注を取得し、まだ提案化していない明細についてのみ`evaluate_supplier_purchase`を呼ぶ(冪等)。

    戻り値: (取得した注文件数, 新規に積んだ提案のリスト, 冪等スキップ件数)。
    """
    try:
        orders = channel.get_orders()
    except Exception as exc:  # noqa: BLE001 - 受注取得の失敗でサイクル全体を止めない
        errors.append(exc)
        if notifier is not None:
            notifier.notify(alert_for_error("受注取得に失敗しました", exc))
        return 0, [], 0

    existing = repository.list_by_type(ProposalType.SUPPLIER_PURCHASE)
    seen = {(p.payload.get("shopify_order_id"), p.payload.get("sku")) for p in existing}

    enqueued: list[Proposal] = []
    skipped_duplicate = 0
    for order in orders:
        order_id = order.get("_shopify_order_gid") or order.get("orderId")
        shipping_address = order.get("shipping_address")
        try:
            items = order_to_items(order)
        except Exception as exc:  # noqa: BLE001 - 1注文の変換失敗で他の注文の処理を止めない
            errors.append(exc)
            if notifier is not None:
                notifier.notify(alert_for_error(f"注文{order_id}の明細変換に失敗しました", exc))
            continue
        for item in items:
            key = (order_id, item.sku)
            if key in seen:
                skipped_duplicate += 1
                continue
            proposal = evaluate_supplier_purchase(order_id, item, shipping_address, settings=settings)
            saved = repository.enqueue(proposal)
            seen.add(key)
            enqueued.append(saved)
            if notifier is not None:
                notify_for_proposal(saved, notifier)  # holdなら「なぜ止まったか」を通知
                pending_alert = alert_for_supplier_purchase_pending_approval(saved)
                if pending_alert is not None:
                    notifier.notify(pending_alert)  # 承認待ち発生を通知((3)人間の承認待ち要件)
    return len(orders), enqueued, skipped_duplicate


def _sync_all_pending_tracking(
    *,
    repository: SqlProposalRepository,
    channel: SalesChannel,
    supplier_provider: SupplierProvider | None,
    notifier: Notifier | None,
) -> list[Proposal | Exception]:
    if supplier_provider is None:
        return []
    results: list[Proposal | Exception] = []
    for proposal in repository.list_by_type(ProposalType.SUPPLIER_PURCHASE):
        if proposal.status is not ProposalStatus.EXECUTED:
            continue
        if proposal.payload.get("tracking_synced"):
            continue
        try:
            results.append(
                sync_supplier_fulfillment(
                    proposal, repository=repository, channel=channel, supplier_provider=supplier_provider
                )
            )
        except Exception as exc:  # noqa: BLE001 - 1件の同期失敗で他の同期を止めない
            results.append(exc)
            if notifier is not None:
                notifier.notify(alert_for_error(f"tracking同期に失敗しました(proposal={proposal.id})", exc))
    return results


def run_autopilot_cycle(
    *,
    repository: SqlProposalRepository,
    channel: SalesChannel,
    settings: Settings,
    calls_remaining: int,
    plan_tasks: list[TaskFn] | None = None,
    act_tasks: list[TaskFn] | None = None,
    order_to_items: OrderToSupplierItems | None = None,
    supplier_provider: SupplierProvider | None = None,
    dry_run: bool = True,
    notifier: Notifier | None = None,
) -> AutopilotCycleResult:
    """1サイクル分の自走ループを実行する(冪等。何度呼んでも安全)。

    実行順序: (1)Plan→(2)publish系のみ自動承認(オプトイン)→(3)受注取得→supplier_purchase提案
    (`order_to_items`指定時のみ。常にrequires_human_approval=True・自動承認されない)→
    (4)承認済み(自動承認された分＋既に人間が承認済みだった分)をまとめて実行(Do、1回)→
    (5)実行済みsupplier_purchaseのtracking同期(`supplier_provider`指定時のみ、受注取得の有無に
    関わらず実施。前サイクル以前にEXECUTEDになった分もここで拾う)。

    `order_to_items`を渡さない場合、受注取得(3)は行わない(実運用のPOD原価カタログ統合は
    未着手のため。DECISIONS.md参照)。`supplier_provider`を渡さない場合はsupplier_purchase関連
    (発注実行・tracking同期)を丸ごとスキップする(`orchestrator/do.py::run_do`の既存の
    フェイルセーフ挙動と揃えている)。
    """
    errors: list[Exception] = []

    plan_result = run_cycle(repository=repository, plan_tasks=plan_tasks, act_tasks=act_tasks, notifier=notifier)
    errors.extend(plan_result.errors)

    auto_approved = _auto_approve_eligible(
        repository, settings, max_actions=settings.max_auto_actions_per_run, notifier=notifier
    )

    orders_fetched = 0
    supplier_purchase_enqueued: list[Proposal] = []
    skipped_duplicate = 0
    if order_to_items is not None:
        orders_fetched, supplier_purchase_enqueued, skipped_duplicate = _ingest_supplier_purchase_orders(
            channel=channel,
            repository=repository,
            settings=settings,
            order_to_items=order_to_items,
            notifier=notifier,
            errors=errors,
        )

    # 自動承認されたpublish、および(受注取得より前から)既に人間が承認済みだった提案
    # (price_change/purchase/supplier_purchase)をまとめて実行する。新たに積んだ
    # supplier_purchase提案はここではまだPENDINGのため対象にならない(自動承認されないため)。
    do_results = run_do(
        repository=repository,
        channel=channel,
        settings=settings,
        calls_remaining=calls_remaining,
        dry_run=dry_run,
        supplier_provider=supplier_provider,
    )
    for r in do_results:
        if isinstance(r, Exception):
            errors.append(r)
            if notifier is not None:
                notifier.notify(alert_for_error("Do実行でエラーが発生しました", r))

    tracking_results = _sync_all_pending_tracking(
        repository=repository, channel=channel, supplier_provider=supplier_provider, notifier=notifier
    )
    for r in tracking_results:
        if isinstance(r, Exception):
            errors.append(r)

    pending_supplier_purchase_count = sum(
        1
        for p in repository.list_by_type(ProposalType.SUPPLIER_PURCHASE)
        if p.status is ProposalStatus.PENDING
    )

    result = AutopilotCycleResult(
        plan=plan_result,
        auto_approved=auto_approved,
        orders_fetched=orders_fetched,
        supplier_purchase_enqueued=supplier_purchase_enqueued,
        supplier_purchase_skipped_duplicate=skipped_duplicate,
        do_results=do_results,
        tracking_sync_results=tracking_results,
        pending_supplier_purchase_count=pending_supplier_purchase_count,
        errors=errors,
    )
    result.log_summary()
    return result
