"""Baseline regression rules."""

from __future__ import annotations

import pytest

from bench.baseline import compare_metrics
from bench.config import ConfigError


def _metric(endpoint: str, concurrency: int, p95: float | None, rps: float) -> dict[str, object]:
    return {
        "endpoint": endpoint,
        "concurrency": concurrency,
        "p95_ms": p95,
        "throughput_rps": rps,
    }


def _status(rows, endpoint: str, concurrency: int, metric: str) -> str:
    match = [
        row
        for row in rows
        if row.endpoint == endpoint and row.concurrency == concurrency and row.metric == metric
    ]
    assert len(match) == 1
    return match[0].status


def test_latency_and_throughput_regressions() -> None:
    baseline = [_metric("db_orders", 10, 100, 100)]
    current = [_metric("db_orders", 10, 130, 70)]
    report = compare_metrics(current, baseline)
    assert _status(report.rows, "db_orders", 10, "p95_ms") == "regression"
    assert _status(report.rows, "db_orders", 10, "throughput_rps") == "regression"
    assert len(report.regressions) == 2


def test_small_percent_and_sub_floor_moves_stay_ok() -> None:
    baseline = [_metric("health", 1, 100, 100), _metric("items", 1, 10, 50)]
    current = [_metric("health", 1, 110, 90), _metric("items", 1, 14, 50)]
    report = compare_metrics(current, baseline)
    assert _status(report.rows, "health", 1, "p95_ms") == "ok"
    assert _status(report.rows, "health", 1, "throughput_rps") == "ok"
    # 40% and 4 ms is under the 5 ms floor.
    assert _status(report.rows, "items", 1, "p95_ms") == "ok"


def test_improvements_are_labeled() -> None:
    report = compare_metrics(
        [_metric("db_orders", 5, 70, 140)],
        [_metric("db_orders", 5, 100, 100)],
    )
    assert _status(report.rows, "db_orders", 5, "p95_ms") == "improvement"
    assert _status(report.rows, "db_orders", 5, "throughput_rps") == "improvement"
    assert report.regressions == []


def test_new_missing_and_no_data_rows() -> None:
    report = compare_metrics(
        [_metric("new_endpoint", 1, 12, 80), _metric("empty", 1, None, 0)],
        [_metric("gone", 1, 12, 80), _metric("empty", 1, 10, 5)],
    )
    assert _status(report.rows, "new_endpoint", 1, "p95_ms") == "new"
    assert _status(report.rows, "gone", 1, "throughput_rps") == "missing"
    assert _status(report.rows, "empty", 1, "p95_ms") == "no_data"
    assert _status(report.rows, "empty", 1, "throughput_rps") == "regression"


def test_zero_baseline_does_not_divide() -> None:
    report = compare_metrics([_metric("health", 1, 5, 10)], [_metric("health", 1, 0, 0)])
    row = next(item for item in report.rows if item.metric == "throughput_rps")
    assert row.status == "ok"
    assert row.delta_pct is None
    assert row.delta_abs == pytest.approx(10)


def test_negative_thresholds_are_rejected() -> None:
    with pytest.raises(ConfigError):
        compare_metrics([], [], p95_regression_pct=-1)
