"""CSV, JSON, and the pandas pivots used by the charts."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from bench.export import p95_pivot, throughput_pivot, write_summary_csv, write_summary_json
from bench.stats import percentile
from tests.conftest import make_run, make_summary


def _rows():
    return [
        make_summary(endpoint="zeta", concurrency=1, throughput_rps=1),
        make_summary(endpoint="zeta", concurrency=5, throughput_rps=2),
        make_summary(endpoint="alpha", concurrency=1, throughput_rps=3),
        make_summary(endpoint="alpha", concurrency=5, throughput_rps=4),
    ]


def test_throughput_pivot_keeps_scenario_order() -> None:
    frame = throughput_pivot(_rows())
    assert list(frame.columns) == ["zeta", "alpha"]
    assert list(frame.index) == [1, 5]
    assert frame.loc[5, "alpha"] == 4
    assert p95_pivot(_rows()).loc[1, "zeta"] == pytest.approx(percentile(list(range(1, 11)), 95))


def test_csv_and_json_round_trip(tmp_path) -> None:
    summaries = _rows()
    csv_path = tmp_path / "summary.csv"
    write_summary_csv(summaries, csv_path)
    frame = pd.read_csv(csv_path)
    assert list(frame["endpoint"]) == ["zeta", "zeta", "alpha", "alpha"]
    assert "p99_ms" in frame.columns
    assert frame.loc[0, "throughput_rps"] == 1

    json_path = tmp_path / "summary.json"
    run = make_run(summaries)
    write_summary_json(run, json_path, comparison=None)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["scenario"] == "portfolio"
    assert payload["comparison"] is None
    assert payload["summaries"][0]["latencies_ms"]
    assert payload["summaries"][0]["latency"]["p95_ms"] == pytest.approx(
        percentile(list(range(1, 11)), 95)
    )
    assert payload["environment"]["processor"] == "Test CPU"
