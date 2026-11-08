"""Latency percentiles and per-endpoint aggregates."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence

from bench.models import TIMEOUT_ERROR_TYPES, EndpointRunSummary, LatencyStats, RequestResult


def percentile(values: Sequence[float], pct: float) -> float:
    """Return the linear-interpolation percentile of ``values``.

    ``pct`` is between 0 and 100. The rank is ``(n - 1) * pct / 100``, which is
    the same definition NumPy uses for its default linear method. The 0th
    percentile is the minimum and the 100th is the maximum.
    """

    if not values:
        raise ValueError("percentile requires at least one value")
    if pct < 0 or pct > 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    weight = rank - low
    return float(ordered[low] * (1.0 - weight) + ordered[high] * weight)


def latency_stats(samples_ms: Sequence[float]) -> LatencyStats | None:
    """Summarize successful response times.

    ``stdev_ms`` is the sample standard deviation. It is 0 when fewer than two
    samples were recorded.
    """

    if not samples_ms:
        return None
    ordered = sorted(float(sample) for sample in samples_ms)
    stdev = statistics.stdev(ordered) if len(ordered) > 1 else 0.0
    return LatencyStats(
        count=len(ordered),
        avg_ms=statistics.fmean(ordered),
        median_ms=percentile(ordered, 50),
        p90_ms=percentile(ordered, 90),
        p95_ms=percentile(ordered, 95),
        p99_ms=percentile(ordered, 99),
        min_ms=ordered[0],
        max_ms=ordered[-1],
        stdev_ms=stdev,
    )


def summarize_endpoint(
    *,
    name: str,
    role: str,
    method: str,
    path: str,
    concurrency: int,
    allow_zero_success: bool,
    results: Sequence[RequestResult],
    wall_time_s: float,
) -> EndpointRunSummary:
    """Aggregate one endpoint at one concurrency level.

    Latency percentiles include successful responses only. Throughput is
    successes divided by wall-clock time. ``error_rate`` is the share of
    responses that missed the expected status or raised an exception.
    """

    successes = [result for result in results if result.ok]
    latencies = [round(result.elapsed_ms, 3) for result in successes]
    status_counts = Counter(
        str(result.status_code) for result in results if result.status_code is not None
    )
    exception_counts = Counter(
        result.error_type for result in results if result.error_type is not None
    )
    unexpected = sum(1 for result in results if not result.ok)
    timeouts = sum(1 for result in results if result.error_type in TIMEOUT_ERROR_TYPES)
    wall = wall_time_s if wall_time_s > 0 else 1e-9
    total = len(results)
    return EndpointRunSummary(
        endpoint=name,
        role=role,
        method=method,
        path=path,
        concurrency=concurrency,
        requests=total,
        successes=len(successes),
        unexpected_errors=unexpected,
        timeouts=timeouts,
        error_rate=(unexpected / total) if total else 0.0,
        throughput_rps=len(successes) / wall,
        attempted_rps=total / wall,
        wall_time_s=wall_time_s,
        latency=latency_stats(latencies),
        status_counts=dict(status_counts),
        exception_counts=dict(exception_counts),
        latencies_ms=latencies,
        allow_zero_success=allow_zero_success,
    )
