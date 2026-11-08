"""Markdown and HTML report rendering."""

from __future__ import annotations

from bench.baseline import compare_metrics
from bench.report import latency_note, render_html, render_markdown, throughput_note
from tests.conftest import make_run, make_summary


def test_markdown_report_contains_measured_percentiles() -> None:
    run = make_run(
        [
            make_summary(endpoint="health", concurrency=1, throughput_rps=250),
            make_summary(
                endpoint="db_orders",
                concurrency=1,
                throughput_rps=40,
                path="/api/db/orders",
            ),
            make_summary(endpoint="health", concurrency=10, throughput_rps=900),
            make_summary(
                endpoint="db_orders",
                concurrency=10,
                throughput_rps=120,
                path="/api/db/orders",
            ),
        ]
    )
    text = render_markdown(run, chart_paths=["charts/throughput_vs_concurrency.png"])
    assert "Benchmark only systems you own or are authorized to test." in text
    assert "health" in text
    assert "9.55" in text
    assert "250.0" in text
    assert "![Throughput across concurrency levels" in text
    assert "Test CPU" in text
    assert "12.50 ms" in text or "12.50" in text
    assert latency_note(run.summaries).startswith("Highest p95")
    assert "Highest throughput" in throughput_note(run.summaries)


def test_report_flags_regressions_and_a_clean_comparison() -> None:
    run = make_run([make_summary(endpoint="db_orders", path="/api/db/orders")])
    regressed = compare_metrics(
        [{"endpoint": "db_orders", "concurrency": 1, "p95_ms": 40.0, "throughput_rps": 10.0}],
        [{"endpoint": "db_orders", "concurrency": 1, "p95_ms": 10.0, "throughput_rps": 10.0}],
    )
    text = render_markdown(run, regressed)
    assert "Regressions: 1." in text
    assert "regression" in text

    stable = compare_metrics(
        [{"endpoint": "db_orders", "concurrency": 1, "p95_ms": 10.0, "throughput_rps": 10.0}],
        [{"endpoint": "db_orders", "concurrency": 1, "p95_ms": 10.0, "throughput_rps": 10.0}],
    )
    assert "No metrics regressed beyond the configured thresholds." in render_markdown(run, stable)
    assert "No baseline was supplied" in render_markdown(run, None)


def test_html_escapes_names_and_includes_the_table() -> None:
    run = make_run([make_summary(endpoint="<script>")])
    page = render_html(run, chart_paths=["charts/p95_vs_concurrency.png"])
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "p95" in page
    assert 'src="charts/p95_vs_concurrency.png"' in page
    assert "Benchmark only systems you own or are authorized to test." in page
