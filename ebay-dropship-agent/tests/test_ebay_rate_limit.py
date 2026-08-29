"""レート制限付きクライアント(コールバジェット・指数バックオフ・リトライ)のテスト。"""

import httpx
import pytest

from ebay_dropship.adapters.ebay.rate_limit import CallBudget, RateLimitExceeded, retry_with_backoff


def test_call_budget_allows_calls_within_limit():
    budget = CallBudget(daily_limit=3)
    budget.record_call()
    budget.record_call()
    assert budget.remaining() == 1


def test_call_budget_blocks_when_exhausted():
    budget = CallBudget(daily_limit=1)
    budget.record_call()
    with pytest.raises(RateLimitExceeded):
        budget.record_call()


def test_call_budget_is_near_limit_at_threshold():
    budget = CallBudget(daily_limit=10, warn_threshold_pct=0.9)
    budget.calls_made = 9
    assert budget.is_near_limit() is True


def test_retry_with_backoff_retries_on_503_then_succeeds():
    responses = iter(
        [httpx.Response(503), httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    sleeps: list[float] = []

    result = retry_with_backoff(
        lambda: next(responses),
        max_retries=4,
        base_delay=0.01,
        sleep=sleeps.append,
        rand=lambda: 0.0,
    )

    assert result.status_code == 200
    assert len(sleeps) == 2  # 2回リトライしてから成功


def test_retry_with_backoff_gives_up_after_max_retries():
    call_count = {"n": 0}

    def always_fails() -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503)

    result = retry_with_backoff(
        always_fails, max_retries=2, base_delay=0.01, sleep=lambda _s: None, rand=lambda: 0.0
    )

    assert result.status_code == 503
    assert call_count["n"] == 3  # 初回 + リトライ2回


def test_retry_with_backoff_does_not_retry_non_retryable_status():
    call_count = {"n": 0}

    def not_found() -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404)

    result = retry_with_backoff(not_found, sleep=lambda _s: None)

    assert result.status_code == 404
    assert call_count["n"] == 1
