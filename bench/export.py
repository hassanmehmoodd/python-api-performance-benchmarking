"""CSV and JSON exports. Pandas builds the frames the charts pivot on."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bench.baseline import ComparisonReport
from bench.models import EndpointRunSummary, RunResult


def summary_frame(summaries: list[EndpointRunSummary]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for summary in summaries:
        latency = summary.latency
        rows.append(
            {
                "endpoint": summary.endpoint,
                "role": summary.role,
                "method": summary.method,
                "path": summary.path,
                "concurrency": summary.concurrency,
                "requests": summary.requests,
                "successes": summary.successes,
                "unexpected_errors": summary.unexpected_errors,
                "timeouts": summary.timeouts,
                "error_rate": summary.error_rate,
                "throughput_rps": summary.throughput_rps,
                "attempted_rps": summary.attempted_rps,
                "wall_time_s": summary.wall_time_s,
                "avg_ms": None if latency is None else latency.avg_ms,
                "median_ms": None if latency is None else latency.median_ms,
                "p90_ms": None if latency is None else latency.p90_ms,
                "p95_ms": None if latency is None else latency.p95_ms,
                "p99_ms": None if latency is None else latency.p99_ms,
                "min_ms": None if latency is None else latency.min_ms,
                "max_ms": None if latency is None else latency.max_ms,
                "stdev_ms": None if latency is None else latency.stdev_ms,
            }
        )
    return pd.DataFrame(rows)


def _pivot(summaries: list[EndpointRunSummary], value: str) -> pd.DataFrame:
    selected = [summary for summary in summaries if summary.role == "performance"]
    frame = summary_frame(selected)
    if frame.empty:
        return frame
    order: list[str] = []
    for summary in selected:
        if summary.endpoint not in order:
            order.append(summary.endpoint)
    pivoted = frame.pivot(index="concurrency", columns="endpoint", values=value).sort_index()
    return pivoted.reindex(columns=order)


def throughput_pivot(summaries: list[EndpointRunSummary]) -> pd.DataFrame:
    return _pivot(summaries, "throughput_rps")


def p95_pivot(summaries: list[EndpointRunSummary]) -> pd.DataFrame:
    return _pivot(summaries, "p95_ms")


def write_summary_csv(summaries: list[EndpointRunSummary], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_frame(summaries).to_csv(path, index=False)


def write_summary_json(
    run: RunResult,
    path: Path,
    comparison: ComparisonReport | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = run.as_dict()
    payload["comparison"] = None if comparison is None else comparison.as_dict()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
