"""S3: `guardrails/autonomy.py`(自動承認の対象範囲。レベルB)のテスト。"""

from __future__ import annotations

from ebay_dropship.approval import ProposalType
from ebay_dropship.config import Settings
from ebay_dropship.guardrails.autonomy import (
    AUTO_APPROVABLE_TYPES,
    auto_approve_publish_active,
    autonomy_active,
    is_auto_approvable,
)


def test_only_publish_is_auto_approvable():
    assert AUTO_APPROVABLE_TYPES == {ProposalType.PUBLISH}
    assert is_auto_approvable(ProposalType.PUBLISH) is True
    for t in (ProposalType.SUPPLIER_PURCHASE, ProposalType.PRICE_CHANGE, ProposalType.WITHDRAW, ProposalType.PURCHASE):
        assert is_auto_approvable(t) is False


def test_autonomy_active_requires_flag_true():
    assert autonomy_active(Settings()) is False
    assert autonomy_active(Settings(autonomy_enabled=True)) is True


def test_kill_switch_forces_autonomy_inactive():
    settings = Settings(autonomy_enabled=True, autonomy_kill_switch=True)
    assert autonomy_active(settings) is False


def test_auto_approve_publish_active_requires_both_flags():
    assert auto_approve_publish_active(Settings(autonomy_enabled=True, auto_approve_publish=False)) is False
    assert auto_approve_publish_active(Settings(autonomy_enabled=False, auto_approve_publish=True)) is False
    assert auto_approve_publish_active(Settings(autonomy_enabled=True, auto_approve_publish=True)) is True
    assert (
        auto_approve_publish_active(
            Settings(autonomy_enabled=True, auto_approve_publish=True, autonomy_kill_switch=True)
        )
        is False
    )
