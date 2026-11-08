"""Markdown and HTML reports for one benchmark run."""

from __future__ import annotations

import html
from collections import Counter

from bench.baseline import ComparisonReport
from bench.models import EndpointRunSummary, RunResult

CHART_CAPTIONS = {
    "throughput_vs_concurrency.png": (
        "Throughput across concurrency levels for performance endpoints."
    ),
    "p95_vs_concurrency.png": "p95 latency across concurrency levels for performance endpoints.",
    "latency_percentiles.png": "Median, p95, and p99 at one concurrency level.",
    "latency_histogram.png": (
        "Latency distribution for the slowest performance endpoint at that level."
    ),
    "error_breakdown.png": "Fault-injection and auth-check outcomes summed across the sweep.",
    "p95_trend.png": "p95 latency across saved runs at one concurrency level.",
}

_RESULT_HEADERS = (
    "Endpoint",
    "Role",
    "C",
    "N",
    "OK",
    "Avg",
    "Median",
    "p90",
    "p95",
    "p99",
    "Min",
    "Max",
    "RPS",
    "Error %",
)


def fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def fmt_rps(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _latency_cells(summary: EndpointRunSummary) -> list[str]:
    latency = summary.latency
    if latency is None:
        return ["n/a"] * 7
    return [
        fmt_ms(latency.avg_ms),
        fmt_ms(latency.median_ms),
        fmt_ms(latency.p90_ms),
        fmt_ms(latency.p95_ms),
        fmt_ms(latency.p99_ms),
        fmt_ms(latency.min_ms),
        fmt_ms(latency.max_ms),
    ]


def result_rows(run: RunResult) -> list[list[str]]:
    rows: list[list[str]] = []
    for summary in run.summaries:
        rows.append(
            [
                summary.endpoint,
                summary.role,
                str(summary.concurrency),
                str(summary.requests),
                str(summary.successes),
                *_latency_cells(summary),
                fmt_rps(summary.throughput_rps),
                f"{summary.error_rate * 100:.1f}%",
            ]
        )
    return rows


def latency_note(summaries: list[EndpointRunSummary]) -> str:
    performance = [
        summary
        for summary in summaries
        if summary.role == "performance" and summary.latency is not None
    ]
    if not performance:
        return "No successful performance samples were recorded."
    slowest = max(performance, key=lambda summary: summary.latency.p95_ms if summary.latency else 0)
    fastest = min(performance, key=lambda summary: summary.latency.p95_ms if summary.latency else 0)
    assert slowest.latency is not None and fastest.latency is not None
    return (
        f"Highest p95 in this run was {slowest.endpoint} at concurrency "
        f"{slowest.concurrency}: {slowest.latency.p95_ms:.2f} ms. "
        f"Lowest p95 was {fastest.endpoint} at concurrency {fastest.concurrency}: "
        f"{fastest.latency.p95_ms:.2f} ms."
    )


def throughput_note(summaries: list[EndpointRunSummary]) -> str:
    performance = [summary for summary in summaries if summary.role == "performance"]
    if not performance:
        return "No performance endpoints were recorded."
    best = max(performance, key=lambda summary: summary.throughput_rps)
    return (
        f"Highest throughput was {best.endpoint} at concurrency {best.concurrency}: "
        f"{best.throughput_rps:.1f} requests/s."
    )


def _levels(summaries: list[EndpointRunSummary]) -> list[int]:
    levels: list[int] = []
    for summary in summaries:
        if summary.concurrency not in levels:
            levels.append(summary.concurrency)
    return levels


def scaling_rows(summaries: list[EndpointRunSummary]) -> tuple[list[int], list[list[str]]]:
    """Compare p95 and throughput at the lowest, middle, and highest concurrency."""

    performance = [summary for summary in summaries if summary.role == "performance"]
    levels = _levels(performance)
    if not levels:
        return [], []
    chosen = [levels[0]]
    if len(levels) >= 3:
        middle = levels[len(levels) // 2]
        if middle not in chosen:
            chosen.append(middle)
    if levels[-1] not in chosen:
        chosen.append(levels[-1])
    by_key = {(summary.endpoint, summary.concurrency): summary for summary in performance}
    names: list[str] = []
    for summary in performance:
        if summary.endpoint not in names:
            names.append(summary.endpoint)
    rows: list[list[str]] = []
    for name in names:
        cells = [name]
        for level in chosen:
            summary = by_key.get((name, level))
            if summary is None or summary.latency is None:
                cells.append("n/a")
            else:
                cells.append(fmt_ms(summary.latency.p95_ms))
        for level in chosen:
            summary = by_key.get((name, level))
            cells.append("n/a" if summary is None else fmt_rps(summary.throughput_rps))
        rows.append(cells)
    return chosen, rows


def outcome_rows(summaries: list[EndpointRunSummary]) -> list[tuple[str, str, str, int]]:
    totals: Counter[tuple[str, str, str]] = Counter()
    order: list[tuple[str, str, str]] = []
    for summary in summaries:
        pairs = [("status", code, count) for code, count in sorted(summary.status_counts.items())]
        pairs += [
            ("exception", name, count) for name, count in sorted(summary.exception_counts.items())
        ]
        for kind, key, count in pairs:
            label = (summary.endpoint, kind, key)
            if label not in totals:
                order.append(label)
            totals[label] += count
    return [(endpoint, kind, key, totals[(endpoint, kind, key)]) for endpoint, kind, key in order]


def zero_success_labels(run: RunResult) -> list[str]:
    labels: list[str] = []
    for summary in run.summaries:
        if summary.successes == 0 and not summary.allow_zero_success:
            labels.append(f"{summary.endpoint} at concurrency {summary.concurrency}")
    return labels


def _scaling_headers(levels: list[int]) -> list[str]:
    return [
        "Endpoint",
        *[f"p95 @ {level}" for level in levels],
        *[f"RPS @ {level}" for level in levels],
    ]


def _markdown_table(headers: list[str] | tuple[str, ...], rows: list[list[str]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def _environment_lines(run: RunResult) -> list[str]:
    labels = (
        ("python", "Python"),
        ("implementation", "Implementation"),
        ("platform", "Platform"),
        ("processor", "Processor"),
        ("logical_cpus", "Logical CPUs"),
        ("host", "Host"),
    )
    lines = []
    for key, label in labels:
        if key in run.environment:
            lines.append(f"- {label}: {run.environment[key]}")
    return lines


def render_markdown(
    run: RunResult,
    comparison: ComparisonReport | None = None,
    chart_paths: list[str] | None = None,
) -> str:
    chart_paths = chart_paths or []
    lines = [
        f"# Benchmark report: {run.scenario}",
        "",
        "Benchmark only systems you own or are authorized to test.",
        "",
        f"- Run: `{run.run_id}`",
        f"- Target: `{run.base_url}`",
        f"- Started: {run.started_at}",
        f"- Finished: {run.finished_at}",
        f"- Warmup requests per endpoint: {run.warmup_requests}",
        f"- Default timeout: {run.timeout_seconds:.2f}s",
        f"- Requests per level: {run.requests_per_level}",
        f"- Concurrency: {', '.join(str(level) for level in run.concurrency_levels)}",
    ]
    if run.description:
        lines.extend(["", run.description])
    if run.token_acquisition_ms is not None:
        lines.append(f"- Token acquisition: {run.token_acquisition_ms:.2f} ms")
    lines.extend(["", "## Environment", "", *_environment_lines(run)])
    lines.extend(
        [
            "",
            "## Results",
            "",
            "Latency columns are milliseconds for successful responses only. "
            "RPS is successful responses divided by the wall-clock time of that cell. "
            "Error % counts unexpected statuses and exceptions. "
            "stdev in the CSV and JSON is the sample standard deviation.",
            "",
            latency_note(run.summaries),
            "",
            throughput_note(run.summaries),
            "",
            _markdown_table(_RESULT_HEADERS, result_rows(run)),
        ]
    )

    chosen, scaling = scaling_rows(run.summaries)
    if chosen and scaling:
        lines.extend(
            ["", "## Throughput comparison", "", _markdown_table(_scaling_headers(chosen), scaling)]
        )

    lines.extend(["", "## Status and exception breakdown", ""])
    outcomes = outcome_rows(run.summaries)
    if outcomes:
        rendered = [[endpoint, kind, key, str(count)] for endpoint, kind, key, count in outcomes]
        lines.append(_markdown_table(("Endpoint", "Kind", "Key", "Count"), rendered))
    else:
        lines.append("No statuses or exceptions were recorded.")

    lines.extend(["", "## Baseline comparison", ""])
    if comparison is None:
        lines.append("No baseline was supplied for this run.")
    else:
        lines.append(
            "A latency regression requires p95 to increase by more than "
            f"{comparison.p95_regression_pct:.0f}% and more than "
            f"{comparison.p95_abs_floor_ms:.0f} ms. A throughput regression requires "
            f"a drop of more than {comparison.throughput_regression_pct:.0f}% and more than "
            f"{comparison.throughput_abs_floor_rps:.0f} requests/s."
        )
        lines.append("")
        if comparison.regressions:
            lines.append(f"Regressions: {len(comparison.regressions)}.")
        else:
            lines.append("No metrics regressed beyond the configured thresholds.")
        lines.append("")
        comparison_rows = []
        for row in comparison.rows:
            comparison_rows.append(
                [
                    row.endpoint,
                    str(row.concurrency),
                    row.metric,
                    "n/a" if row.baseline is None else f"{row.baseline:.2f}",
                    "n/a" if row.current is None else f"{row.current:.2f}",
                    fmt_pct(row.delta_pct),
                    row.status,
                ]
            )
        lines.append(
            _markdown_table(
                ("Endpoint", "C", "Metric", "Baseline", "Current", "Delta", "Status"),
                comparison_rows,
            )
        )

    if chart_paths:
        lines.extend(["", "## Charts", ""])
        for path in chart_paths:
            name = path.rsplit("/", 1)[-1]
            caption = CHART_CAPTIONS.get(name, name)
            lines.append(f"![{caption}]({path})")
            lines.append("")
            lines.append(caption)
            lines.append("")

    lines.extend(
        [
            "## How to read a cell",
            "",
            "Warmup requests are discarded. Percentiles use linear interpolation "
            "between the closest ranks. A fault endpoint that is configured to time out "
            "can legitimately record zero successes when `allow_zero_success` is set.",
            "",
        ]
    )
    return "\n".join(lines)


def _html_table(headers: list[str] | tuple[str, ...], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(cell)}</td>" for cell in row)
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html(
    run: RunResult,
    comparison: ComparisonReport | None = None,
    chart_paths: list[str] | None = None,
) -> str:
    chart_paths = chart_paths or []
    environment = "".join(f"<li>{html.escape(line[2:])}</li>" for line in _environment_lines(run))
    description = f"<p>{html.escape(run.description)}</p>" if run.description else ""
    token = ""
    if run.token_acquisition_ms is not None:
        token = f"<li>Token acquisition: {run.token_acquisition_ms:.2f} ms</li>"
    chosen, scaling = scaling_rows(run.summaries)
    scaling_html = ""
    if chosen and scaling:
        scaling_html = (
            '<h2>Throughput comparison</h2><div class="wrap">'
            + _html_table(_scaling_headers(chosen), scaling)
            + "</div>"
        )

    outcomes = outcome_rows(run.summaries)
    if outcomes:
        outcome_html = _html_table(
            ("Endpoint", "Kind", "Key", "Count"),
            [[endpoint, kind, key, str(count)] for endpoint, kind, key, count in outcomes],
        )
    else:
        outcome_html = "<p>No statuses or exceptions were recorded.</p>"

    if comparison is None:
        baseline_html = "<p>No baseline was supplied for this run.</p>"
    else:
        verdict = (
            f"<p><strong>Regressions: {len(comparison.regressions)}.</strong></p>"
            if comparison.regressions
            else "<p>No metrics regressed beyond the configured thresholds.</p>"
        )
        baseline_html = (
            "<p>A latency regression requires p95 to increase by more than "
            f"{comparison.p95_regression_pct:.0f}% and more than "
            f"{comparison.p95_abs_floor_ms:.0f} ms. A throughput regression requires "
            f"a drop of more than {comparison.throughput_regression_pct:.0f}% and more than "
            f"{comparison.throughput_abs_floor_rps:.0f} requests/s.</p>"
            + verdict
            + _html_table(
                ("Endpoint", "C", "Metric", "Baseline", "Current", "Delta", "Status"),
                [
                    [
                        row.endpoint,
                        str(row.concurrency),
                        row.metric,
                        "n/a" if row.baseline is None else f"{row.baseline:.2f}",
                        "n/a" if row.current is None else f"{row.current:.2f}",
                        fmt_pct(row.delta_pct),
                        row.status,
                    ]
                    for row in comparison.rows
                ],
            )
        )

    figures = []
    for path in chart_paths:
        name = path.rsplit("/", 1)[-1]
        caption = CHART_CAPTIONS.get(name, name)
        figures.append(
            "<figure>"
            f'<img src="{html.escape(path, quote=True)}" alt="{html.escape(caption, quote=True)}">'
            f"<figcaption>{html.escape(caption)}</figcaption>"
            "</figure>"
        )
    charts_html = "<h2>Charts</h2>" + "".join(figures) if figures else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Benchmark report: {html.escape(run.scenario)}</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{
      margin: 0 auto;
      max-width: 1100px;
      padding: 2rem 1.25rem 4rem;
      font: 16px/1.5 "Segoe UI", Helvetica, Arial, sans-serif;
      color: #1f2933;
      background: #f8fafc;
    }}
    h1, h2 {{ line-height: 1.2; color: #102a43; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .banner {{
      background: #e8f1fb;
      border-left: 4px solid #1f4e79;
      padding: 0.75rem 1rem;
      margin: 1rem 0 1.5rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      margin: 0.75rem 0 1.5rem;
      font-variant-numeric: tabular-nums;
    }}
    th, td {{
      text-align: left;
      padding: 0.45rem 0.55rem;
      border-bottom: 1px solid #d9e2ec;
      white-space: nowrap;
    }}
    th {{ background: #1f4e79; color: white; font-weight: 600; }}
    tr:nth-child(even) td {{ background: #f0f4f8; }}
    .wrap {{ overflow-x: auto; }}
    figure {{ margin: 1.5rem 0; }}
    img {{ max-width: 100%; height: auto; background: white; border: 1px solid #d9e2ec; }}
    figcaption {{ color: #52606d; margin-top: 0.35rem; }}
    code {{ background: #e4e7eb; padding: 0.1rem 0.3rem; }}
  </style>
</head>
<body>
  <h1>Benchmark report: {html.escape(run.scenario)}</h1>
  <div class="banner">
    Benchmark only systems you own or are authorized to test.
    Target: {html.escape(run.base_url)}
  </div>
  {description}
  <ul>
    <li>Run: {html.escape(run.run_id)}</li>
    <li>Started: {html.escape(run.started_at)}</li>
    <li>Finished: {html.escape(run.finished_at)}</li>
    <li>Warmup requests per endpoint: {run.warmup_requests}</li>
    <li>Default timeout: {run.timeout_seconds:.2f}s</li>
    <li>Requests per level: {run.requests_per_level}</li>
    <li>Concurrency: {html.escape(", ".join(str(level) for level in run.concurrency_levels))}</li>
    {token}
  </ul>
  <h2>Environment</h2>
  <ul>{environment}</ul>
  <h2>Results</h2>
  <p>{html.escape(latency_note(run.summaries))}</p>
  <p>{html.escape(throughput_note(run.summaries))}</p>
  <p>
    Latency columns are milliseconds for successful responses only.
    RPS is successful responses divided by wall-clock time.
    Error % counts unexpected statuses and exceptions.
  </p>
  <div class="wrap">{_html_table(_RESULT_HEADERS, result_rows(run))}</div>
  {scaling_html}
  <h2>Status and exception breakdown</h2>
  <div class="wrap">{outcome_html}</div>
  <h2>Baseline comparison</h2>
  <div class="wrap">{baseline_html}</div>
  {charts_html}
  <h2>How to read a cell</h2>
  <p>
    Warmup requests are discarded. Percentiles use linear interpolation between
    the closest ranks. A fault endpoint configured to time out can record zero
    successes when allow_zero_success is set.
  </p>
</body>
</html>
"""
