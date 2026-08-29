"""run_cycle を叩くだけの薄いトリガー層。

APScheduler本体の登録(`scheduler.add_job(cycle_scheduler.tick, "interval", hours=24)` 等)は
実際のアプリ起動処理(将来の `api/` FastAPI アプリの起動時)で行う。ここでは
「サイクルのロジック(orchestrator/cycle.py)」と「いつ起動するか(トリガー)」を分離し、
このクラス自身はビジネスロジックを一切持たない(single-flight制御のみ)。

single-flight: 前回の run_cycle 呼び出しが完了していなければ、新しい呼び出しは何もせず
None を返してスキップする(重複起動によるコール消費・二重処理を防ぐ)。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from ebay_dropship.orchestrator.cycle import CycleResult

logger = logging.getLogger(__name__)


class CycleScheduler:
    def __init__(self, run_cycle_fn: Callable[[], CycleResult]):
        self._run_cycle_fn = run_cycle_fn
        self._lock = threading.Lock()

    def tick(self) -> CycleResult | None:
        """スケジューラ(APScheduler等)が定期的に呼ぶ想定のエントリポイント。"""
        if not self._lock.acquire(blocking=False):
            logger.warning("前回のサイクルが実行中のため、このtickはスキップします(single-flight)。")
            return None
        try:
            return self._run_cycle_fn()
        finally:
            self._lock.release()

    def run_once_now(self) -> CycleResult | None:
        """手動「今すぐ1回実行」用。tickと同じsingle-flight制御を使う。"""
        return self.tick()
