"""Chart files are real PNGs."""

from __future__ import annotations

from bench.charts import chart_trend, write_charts
from tests.conftest import make_run, make_summary

PNG = b"\x89PNG\r\n\x1a\n"


def test_write_charts_and_trend(tmp_path) -> None:
    run = make_run(
        [
            make_summary(endpoint="health", concurrency=1, throughput_rps=100),
            make_summary(endpoint="health", concurrency=10, throughput_rps=400),
            make_summary(
                endpoint="db_orders",
                concurrency=1,
                throughput_rps=20,
                path="/api/db/orders",
            ),
            make_summary(
                endpoint="db_orders",
                concurrency=10,
                throughput_rps=80,
                path="/api/db/orders",
            ),
            make_summary(
                endpoint="flaky_timeout",
                concurrency=1,
                role="fault",
                latencies_ms=[],
                successes=0,
                requests=3,
                unexpected_errors=3,
                status_counts={},
                exception_counts={"read_timeout": 3},
                allow_zero_success=True,
                throughput_rps=0,
            ),
        ]
    )
    written = write_charts(run, tmp_path / "charts")
    names = {path.name for path in written}
    assert "throughput_vs_concurrency.png" in names
    assert "p95_vs_concurrency.png" in names
    assert "latency_percentiles.png" in names
    assert "latency_histogram.png" in names
    assert "error_breakdown.png" in names
    for path in written:
        assert path.read_bytes().startswith(PNG)

    history = [
        {
            "run_id": "a",
            "scenario": "portfolio",
            "started_at": "2026-11-08T12:00:00.000Z",
            "points": [
                {
                    "endpoint": "health",
                    "role": "performance",
                    "concurrency": 10,
                    "p95_ms": 5.0,
                }
            ],
        },
        {
            "run_id": "b",
            "scenario": "portfolio",
            "started_at": "2026-11-08T12:01:00.000Z",
            "points": [
                {
                    "endpoint": "health",
                    "role": "performance",
                    "concurrency": 10,
                    "p95_ms": 6.0,
                }
            ],
        },
        {
            "run_id": "c",
            "scenario": "other",
            "started_at": "2026-11-08T12:02:00.000Z",
            "points": [
                {
                    "endpoint": "health",
                    "role": "performance",
                    "concurrency": 10,
                    "p95_ms": 9.0,
                }
            ],
        },
    ]
    trend = chart_trend(history, tmp_path / "p95_trend.png", scenario="portfolio")
    assert trend is not None
    assert trend.read_bytes().startswith(PNG)
    assert chart_trend(history[:1], tmp_path / "short.png", scenario="portfolio") is None
