"""orchestrator/scheduler.py::CycleScheduler のテスト。single-flight(前サイクル未完なら重複起動しない)。"""

from __future__ import annotations

import threading

from ebay_dropship.orchestrator.cycle import CycleResult
from ebay_dropship.orchestrator.scheduler import CycleScheduler


def test_tick_runs_when_not_already_running():
    calls: list[int] = []

    def cycle_fn() -> CycleResult:
        calls.append(1)
        return CycleResult()

    scheduler = CycleScheduler(cycle_fn)

    result = scheduler.tick()

    assert result is not None
    assert calls == [1]


def test_tick_skips_when_a_cycle_is_already_running():
    started = threading.Event()
    release = threading.Event()

    def slow_cycle() -> CycleResult:
        started.set()
        release.wait(timeout=2)
        return CycleResult()

    scheduler = CycleScheduler(slow_cycle)
    thread = threading.Thread(target=scheduler.tick)
    thread.start()
    assert started.wait(timeout=2)

    result = scheduler.tick()  # 前回がまだ実行中のはずなのでスキップされる

    assert result is None
    release.set()
    thread.join(timeout=2)


def test_tick_runs_again_after_previous_cycle_completes():
    calls: list[int] = []

    def cycle_fn() -> CycleResult:
        calls.append(1)
        return CycleResult()

    scheduler = CycleScheduler(cycle_fn)
    scheduler.tick()

    result = scheduler.tick()

    assert result is not None
    assert calls == [1, 1]


def test_run_once_now_uses_the_same_single_flight_lock():
    started = threading.Event()
    release = threading.Event()

    def slow_cycle() -> CycleResult:
        started.set()
        release.wait(timeout=2)
        return CycleResult()

    scheduler = CycleScheduler(slow_cycle)
    thread = threading.Thread(target=scheduler.tick)
    thread.start()
    assert started.wait(timeout=2)

    result = scheduler.run_once_now()  # tickと同じロックを使うのでスキップされる

    assert result is None
    release.set()
    thread.join(timeout=2)
