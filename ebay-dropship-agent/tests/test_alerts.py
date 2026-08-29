"""アラート通知(alerts/)のテスト。重大度・重複抑制/レート制限・hold/withdrawとの紐づけを検証する。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ebay_dropship.adapters.ebay.rate_limit import CallBudget
from ebay_dropship.alerts import (
    Alert,
    AlertSeverity,
    DedupingNotifier,
    LoggingNotifier,
    Notifier,
    alert_for_proposal,
    alert_for_rate_budget,
    notify_for_proposal,
)
from ebay_dropship.approval import Priority, Proposal, ProposalType, RiskLevel


class _SpyNotifier(Notifier):
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def notify(self, alert: Alert) -> None:
        self.alerts.append(alert)


def _proposal(proposal_type: ProposalType, rationale: str) -> Proposal:
    return Proposal(
        id="p1",
        proposal_type=proposal_type,
        priority=Priority.NEEDS_REVIEW,
        summary="s",
        rationale=rationale,
        risk_level=RiskLevel.MEDIUM,
        requires_human_approval=True,
    )


def test_logging_notifier_logs_at_the_right_level(caplog):
    caplog.set_level("WARNING", logger="ebay_dropship.alerts")
    notifier = LoggingNotifier()
    alert = Alert(category="stock_divergence", severity=AlertSeverity.WARNING, message="在庫が消失", reason="なぜ止まったか")

    notifier.notify(alert)

    assert "stock_divergence" in caplog.text
    assert "在庫が消失" in caplog.text
    assert "なぜ止まったか" in caplog.text  # 「なぜ止まったか」が見える


def test_logging_notifier_uses_error_level_for_critical(caplog):
    caplog.set_level("INFO", logger="ebay_dropship.alerts")
    notifier = LoggingNotifier()

    notifier.notify(Alert(category="rate_limit", severity=AlertSeverity.CRITICAL, message="枯渇"))

    assert any(record.levelname == "ERROR" for record in caplog.records)


# --- 在庫乖離・不採算とhold/withdraw判断の紐づけ ---


def test_alert_for_hold_due_to_stock_categorized_as_stock_divergence():
    proposal = _proposal(ProposalType.HOLD, "サプライヤーにSKUが見つかりません(在庫消失の可能性)。")

    alert = alert_for_proposal(proposal)

    assert alert is not None
    assert alert.category == "stock_divergence"
    assert alert.reason == proposal.rationale  # 「なぜ止まったか」がそのまま転記される
    assert alert.related_proposal_id == "p1"


def test_alert_for_hold_due_to_generic_reason_categorized_as_hold():
    proposal = _proposal(ProposalType.HOLD, "必須item specificsが不足のため要確認。")

    alert = alert_for_proposal(proposal)

    assert alert is not None
    assert alert.category == "hold"


def test_alert_for_withdraw_categorized_as_unprofitable():
    proposal = _proposal(ProposalType.WITHDRAW, "純利益が赤字のため取り下げを提案。")

    alert = alert_for_proposal(proposal)

    assert alert is not None
    assert alert.category == "unprofitable"


def test_no_alert_for_none_or_write_type_proposals():
    for proposal_type in (ProposalType.NONE, ProposalType.PUBLISH, ProposalType.PRICE_CHANGE, ProposalType.PURCHASE):
        assert alert_for_proposal(_proposal(proposal_type, "理由")) is None


def test_notify_for_proposal_calls_notifier_only_when_alert_exists():
    spy = _SpyNotifier()

    notify_for_proposal(_proposal(ProposalType.HOLD, "在庫消失"), spy)
    notify_for_proposal(_proposal(ProposalType.NONE, "据え置き"), spy)

    assert len(spy.alerts) == 1


# --- 重複抑制/レート制限 ---


def test_deduping_notifier_suppresses_within_window():
    spy = _SpyNotifier()
    deduper = DedupingNotifier(inner=spy, suppress_window=timedelta(minutes=30))
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    alert = Alert(category="stock_divergence", severity=AlertSeverity.WARNING, message="m", related_proposal_id="p1")

    deduper.notify(alert, now=now)
    deduper.notify(alert, now=now + timedelta(minutes=10))  # 抑制ウィンドウ内

    assert len(spy.alerts) == 1


def test_deduping_notifier_allows_after_window_elapses():
    spy = _SpyNotifier()
    deduper = DedupingNotifier(inner=spy, suppress_window=timedelta(minutes=30))
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    alert = Alert(category="stock_divergence", severity=AlertSeverity.WARNING, message="m", related_proposal_id="p1")

    deduper.notify(alert, now=now)
    deduper.notify(alert, now=now + timedelta(minutes=31))  # 抑制ウィンドウ超過

    assert len(spy.alerts) == 2


def test_deduping_notifier_treats_different_proposals_independently():
    spy = _SpyNotifier()
    deduper = DedupingNotifier(inner=spy, suppress_window=timedelta(minutes=30))
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    deduper.notify(Alert(category="hold", severity=AlertSeverity.WARNING, message="m", related_proposal_id="p1"), now=now)
    deduper.notify(Alert(category="hold", severity=AlertSeverity.WARNING, message="m", related_proposal_id="p2"), now=now)

    assert len(spy.alerts) == 2  # 別対象は別枠で通知される


# --- レート逼迫アラート ---


def test_alert_for_rate_budget_none_when_not_near_limit():
    budget = CallBudget(daily_limit=100, calls_made=10)
    assert alert_for_rate_budget(budget) is None


def test_alert_for_rate_budget_warning_when_near_limit():
    budget = CallBudget(daily_limit=100, calls_made=95)  # デフォルト閾値90%
    alert = alert_for_rate_budget(budget)
    assert alert is not None
    assert alert.severity == AlertSeverity.WARNING


def test_alert_for_rate_budget_critical_when_exhausted():
    budget = CallBudget(daily_limit=100, calls_made=100)
    alert = alert_for_rate_budget(budget)
    assert alert is not None
    assert alert.severity == AlertSeverity.CRITICAL
