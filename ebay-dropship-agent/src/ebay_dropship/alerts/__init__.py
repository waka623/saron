"""アラート通知(運用監視)。

`Notifier` インターフェースの背後に実装を置き、既定のログ出力から将来メール/Slack等へ
差し替え可能にする(research/market_data.py 等と同じ「インターフェース越しに差し替え」方針)。

在庫乖離・不採算のアラートは、対応する hold/withdraw 判断の `Proposal.rationale` をそのまま
`Alert.reason` に転記する。これにより「なぜ止まったか」がアラート単体から人に見えるようにする
(判断ロジック側でアラート文言を別途持たない = 二重管理にしない)。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import ClassVar

from ebay_dropship.adapters.ebay.rate_limit import CallBudget
from ebay_dropship.approval import Proposal, ProposalType

logger = logging.getLogger("ebay_dropship.alerts")


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Alert:
    category: str  # 例: "stock_divergence" | "unprofitable" | "rate_limit"
    severity: AlertSeverity
    message: str
    related_proposal_id: str | None = None
    reason: str | None = None  # 対応する判断のrationaleをそのまま転記


class Notifier(ABC):
    @abstractmethod
    def notify(self, alert: Alert) -> None: ...


class LoggingNotifier(Notifier):
    """既定実装。ログに出力するだけ。"""

    _LEVELS: ClassVar[dict[AlertSeverity, int]] = {
        AlertSeverity.INFO: logging.INFO,
        AlertSeverity.WARNING: logging.WARNING,
        AlertSeverity.CRITICAL: logging.ERROR,
    }

    def notify(self, alert: Alert) -> None:
        suffix = ""
        if alert.related_proposal_id:
            suffix += f" (proposal={alert.related_proposal_id})"
        if alert.reason:
            suffix += f" reason={alert.reason}"
        logger.log(self._LEVELS[alert.severity], "[%s] %s%s", alert.category, alert.message, suffix)


@dataclass
class DedupingNotifier(Notifier):
    """同一(category, related_proposal_id)の通知を、一定時間内は抑制する(重複抑制/レート制限)。"""

    inner: Notifier
    suppress_window: timedelta = field(default_factory=lambda: timedelta(minutes=30))
    _last_sent: dict[tuple[str, str | None], datetime] = field(default_factory=dict, init=False)

    def notify(self, alert: Alert, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        key = (alert.category, alert.related_proposal_id)
        last = self._last_sent.get(key)
        if last is not None and now - last < self.suppress_window:
            return  # 抑制(重複通知しない)
        self._last_sent[key] = now
        self.inner.notify(alert)


_STOCK_DIVERGENCE_MARKERS = ("在庫", "陳腐化", "同期ラグ", "SKUが見つかりません")


def alert_for_proposal(proposal: Proposal) -> Alert | None:
    """hold/withdraw の判断からアラートを組み立てる。none/publish/price_change/purchase等は対象外。"""
    if proposal.proposal_type is ProposalType.HOLD:
        category = "stock_divergence" if any(m in proposal.rationale for m in _STOCK_DIVERGENCE_MARKERS) else "hold"
        return Alert(
            category=category,
            severity=AlertSeverity.WARNING,
            message=proposal.summary,
            related_proposal_id=proposal.id,
            reason=proposal.rationale,
        )
    if proposal.proposal_type is ProposalType.WITHDRAW:
        return Alert(
            category="unprofitable",
            severity=AlertSeverity.WARNING,
            message=proposal.summary,
            related_proposal_id=proposal.id,
            reason=proposal.rationale,
        )
    return None


def notify_for_proposal(proposal: Proposal, notifier: Notifier) -> None:
    alert = alert_for_proposal(proposal)
    if alert is not None:
        notifier.notify(alert)


def alert_for_rate_budget(budget: CallBudget) -> Alert | None:
    """レート逼迫アラート。CallBudget.is_near_limit()がTrueのときのみ発火する。"""
    if not budget.is_near_limit():
        return None
    remaining = budget.remaining()
    severity = AlertSeverity.CRITICAL if remaining == 0 else AlertSeverity.WARNING
    return Alert(
        category="rate_limit",
        severity=severity,
        message=f"eBay APIコールバジェットが逼迫しています(残り{remaining}/{budget.daily_limit})。",
    )
