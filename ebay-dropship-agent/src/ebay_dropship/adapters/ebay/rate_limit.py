"""日次コールバジェットと指数バックオフ・リトライ(compliance.md 第4章)。"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx


class RateLimitExceeded(Exception):
    pass


@dataclass
class CallBudget:
    """API単位の日次コール上限。上限に近づいたら呼び出し側で減速・停止できるようにする。"""

    daily_limit: int
    calls_made: int = 0
    warn_threshold_pct: float = 0.9

    def remaining(self) -> int:
        return max(self.daily_limit - self.calls_made, 0)

    def is_near_limit(self) -> bool:
        return self.calls_made >= self.daily_limit * self.warn_threshold_pct

    def record_call(self) -> None:
        if self.remaining() <= 0:
            raise RateLimitExceeded(f"日次コール上限({self.daily_limit})に達しました。")
        self.calls_made += 1

    def reset(self) -> None:
        self.calls_made = 0


def retry_with_backoff(
    func: Callable[[], httpx.Response],
    *,
    max_retries: int = 4,
    base_delay: float = 1.0,
    retry_on: tuple[int, ...] = (429, 500, 502, 503, 504),
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[], float] = random.random,
) -> httpx.Response:
    """指数バックオフ + ジッタでリトライする。retry_on 以外のステータスは即座に返す。"""
    attempt = 0
    while True:
        response = func()
        if response.status_code not in retry_on or attempt >= max_retries:
            return response
        delay = base_delay * (2**attempt) + rand() * base_delay
        sleep(delay)
        attempt += 1
