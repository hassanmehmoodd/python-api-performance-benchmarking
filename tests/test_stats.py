"""Latency math and endpoint aggregation."""

from __future__ import annotations

import math

import pytest

from bench.models import RequestResult
from bench.stats import latency_stats, percentile, summarize_endpoint


def test_percentile_linear_interpolation() -> None:
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert percentile(values, 0) == 1
    assert percentile(values, 100) == 10
    assert percentile(values, 50) == 5.5
    assert percentile(values, 90) == pytest.approx(9.1)
    assert percentile(values, 95) == pytest.approx(9.55)
    assert percentile(values, 99) == pytest.approx(9.91)


def test_percentile_sorts_and_handles_a_single_value() -> None:
    assert percentile([10, 1, 3], 0) == 1
    assert percentile([10, 1, 3], 100) == 10
    assert percentile([4], 95) == 4


def test_percentile_rejects_empty_and_out_of_range() -> None:
    with pytest.raises(ValueError, match="at least one"):
        percentile([], 50)
    with pytest.raises(ValueError, match="between 0 and 100"):
        percentile([1.0], -1)
    with pytest.raises(ValueError, match="between 0 and 100"):
        percentile([1.0], 100.1)


def test_latency_stats_matches_percentile_definition() -> None:
    stats = latency_stats([10, 20, 30, 40])
    assert stats is not None
    assert stats.count == 4
    assert stats.avg_ms == 25
    assert stats.median_ms == 25
    assert stats.min_ms == 10
    assert stats.max_ms == 40
    assert stats.p95_ms == percentile([10, 20, 30, 40], 95)
    variance = sum((value - 25) ** 2 for value in (10, 20, 30, 40)) / 3
    assert stats.stdev_ms == pytest.approx(math.sqrt(variance))


def test_latency_stats_empty_is_none_and_single_value_has_zero_stdev() -> None:
    assert latency_stats([]) is None
    stats = latency_stats([8])
    assert stats is not None
    assert stats.p99_ms == 8
    assert stats.stdev_ms == 0


def _result(
    ok: bool,
    elapsed: float = 10,
    status: int | None = 200,
    error: str | None = None,
) -> RequestResult:
    return RequestResult("health", 2, elapsed, status, error, ok)


def test_summarize_uses_successes_only_for_latency() -> None:
    results = [
        _result(True, 10),
        _result(True, 30),
        _result(False, 1000, status=None, error="read_timeout"),
        _result(False, 5, status=500, error="http_status"),
    ]
    summary = summarize_endpoint(
        name="health",
        role="performance",
        method="GET",
        path="/health",
        concurrency=2,
        allow_zero_success=False,
        results=results,
        wall_time_s=0.5,
    )
    assert summary.requests == 4
    assert summary.successes == 2
    assert summary.unexpected_errors == 2
    assert summary.timeouts == 1
    assert summary.error_rate == 0.5
    assert summary.throughput_rps == pytest.approx(4.0)
    assert summary.latency is not None
    assert summary.latency.count == 2
    assert summary.latencies_ms == [10.0, 30.0]
    assert summary.status_counts == {"200": 2, "500": 1}
    assert summary.exception_counts == {"read_timeout": 1, "http_status": 1}


def test_summarize_without_successes_has_no_latency() -> None:
    summary = summarize_endpoint(
        name="flaky_timeout",
        role="fault",
        method="GET",
        path="/api/flaky",
        concurrency=1,
        allow_zero_success=True,
        results=[_result(False, 100, status=None, error="read_timeout")],
        wall_time_s=0.1,
    )
    assert summary.latency is None
    assert summary.throughput_rps == 0
    assert summary.timeouts == 1
    assert summary.allow_zero_success is True
