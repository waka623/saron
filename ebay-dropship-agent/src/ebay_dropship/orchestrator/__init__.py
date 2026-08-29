"""PDCA スケジューラ。PROMPT.md 第3章の4フェーズを起動し状態遷移を管理する(Phase 2〜6 で段階実装)。

書き込み系(Do フェーズの実行)は必ず guardrails を通してから実行すること。
"""

from enum import StrEnum


class PdcaPhase(StrEnum):
    PLAN = "plan"
    DO = "do"
    CHECK = "check"
    ACT = "act"


class Orchestrator:
    def run_plan(self) -> None:
        raise NotImplementedError("Phase 3 で実装(research + listing)")

    def run_do(self) -> None:
        raise NotImplementedError("Phase 4 で実装(承認済み提案の実行)")

    def run_check(self) -> None:
        raise NotImplementedError("Phase 6 で実装(analytics 集計)")

    def run_act(self) -> None:
        raise NotImplementedError("Phase 6 で実装(pricing の改善提案生成)")

    def run_cycle(self) -> None:
        """PDCA_CYCLE(初期値: daily)の頻度でスケジューラから呼ばれる想定(Phase 6 で APScheduler に接続)。"""
        raise NotImplementedError("Phase 6 で実装")
