"""Shared builders for report, export, and chart tests."""

from __future__ import annotations

from bench.models import EndpointRunSummary, RunResult
from bench.stats import latency_stats

ROOT_ENV = {
    "python": "3.12.0",
    "implementation": "CPython",
    "platform": "Linux-test",
    "system": "Linux",
    "machine": "x86_64",
    "processor": "Test CPU",
    "logical_cpus": 4,
    "host": "test-host",
}


def make_summary(
    endpoint: str = "health",
    concurrency: int = 1,
    *,
    role: str = "performance",
    latencies_ms: list[float] | None = None,
    successes: int | None = None,
    requests: int | None = None,
    unexpected_errors: int = 0,
    timeouts: int = 0,
    error_rate: float | None = None,
    throughput_rps: float = 100.0,
    status_counts: dict[str, int] | None = None,
    exception_counts: dict[str, int] | None = None,
    allow_zero_success: bool = False,
    path: str = "/health",
) -> EndpointRunSummary:
    samples = [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10] if latencies_ms is None else latencies_ms
    ok = len(samples) if successes is None else successes
    total = ok + unexpected_errors if requests is None else requests
    rate = (unexpected_errors / total) if error_rate is None and total else (error_rate or 0.0)
    return EndpointRunSummary(
        endpoint=endpoint,
        role=role,
        method="GET",
        path=path,
        concurrency=concurrency,
        requests=total,
        successes=ok,
        unexpected_errors=unexpected_errors,
        timeouts=timeouts,
        error_rate=rate,
        throughput_rps=throughput_rps,
        attempted_rps=throughput_rps,
        wall_time_s=0.1,
        latency=latency_stats(samples),
        status_counts={"200": ok} if status_counts is None else status_counts,
        exception_counts={} if exception_counts is None else exception_counts,
        latencies_ms=list(samples),
        allow_zero_success=allow_zero_success,
    )


def make_run(
    summaries: list[EndpointRunSummary] | None = None,
    *,
    scenario: str = "portfolio",
    description: str = "Fixture run",
) -> RunResult:
    rows = summaries if summaries is not None else [make_summary(), make_summary(concurrency=5)]
    levels = list(dict.fromkeys(row.concurrency for row in rows))
    return RunResult(
        run_id="20261108T120000000000Z",
        scenario=scenario,
        description=description,
        base_url="http://127.0.0.1:8000",
        started_at="2026-11-08T12:00:00.000Z",
        finished_at="2026-11-08T12:00:01.000Z",
        environment=dict(ROOT_ENV),
        token_acquisition_ms=12.5,
        warmup_requests=1,
        timeout_seconds=5.0,
        concurrency_levels=levels or [1],
        requests_per_level=10,
        summaries=rows,
    )
