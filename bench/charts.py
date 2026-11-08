"""Matplotlib charts for a single run and for saved history."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt
from cycler import cycler

from bench.export import p95_pivot, throughput_pivot
from bench.models import EndpointRunSummary, RunResult

COLORS = (
    "#1f4e79",
    "#0f6e56",
    "#b45309",
    "#7c3aed",
    "#9f1239",
    "#0e7490",
    "#365314",
    "#9a3412",
)

_STYLE_READY = False


def _apply_style() -> None:
    global _STYLE_READY
    if _STYLE_READY:
        return
    plt.rcParams.update(
        {
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.3,
            "grid.linestyle": "--",
            "font.size": 11,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.prop_cycle": cycler(color=list(COLORS)),
            "legend.frameon": False,
        }
    )
    _STYLE_READY = True


def select_concurrency(levels: list[int], preferred: int = 10) -> int | None:
    unique = list(dict.fromkeys(levels))
    if not unique:
        return None
    if preferred in unique:
        return preferred
    return unique[len(unique) // 2]


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def _line_chart(frame, path: Path, *, title: str, ylabel: str) -> Path | None:
    if frame.empty:
        return None
    _apply_style()
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    plotted = False
    for column in frame.columns:
        series = frame[column].dropna()
        if series.empty:
            continue
        ax.plot(
            series.index.astype(float),
            series.to_numpy(),
            marker="o",
            linewidth=2,
            label=column,
        )
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax.set_title(title)
    ax.set_xlabel("Concurrency")
    ax.set_ylabel(ylabel)
    ax.set_xticks(list(frame.index))
    ax.legend(ncol=2)
    fig.tight_layout()
    return _save(fig, path)


def chart_throughput(run: RunResult, path: Path) -> Path | None:
    return _line_chart(
        throughput_pivot(run.summaries),
        path,
        title="Throughput by concurrency",
        ylabel="Successful requests / second",
    )


def chart_p95(run: RunResult, path: Path) -> Path | None:
    return _line_chart(
        p95_pivot(run.summaries),
        path,
        title="p95 latency by concurrency",
        ylabel="p95 latency (ms)",
    )


def chart_latency_bars(run: RunResult, path: Path) -> Path | None:
    level = select_concurrency(run.concurrency_levels)
    if level is None:
        return None
    rows = [
        summary
        for summary in run.summaries
        if summary.role == "performance"
        and summary.concurrency == level
        and summary.latency is not None
    ]
    if not rows:
        return None
    _apply_style()
    labels = [summary.endpoint for summary in rows]
    series = {
        "median": [summary.latency.median_ms for summary in rows if summary.latency],
        "p95": [summary.latency.p95_ms for summary in rows if summary.latency],
        "p99": [summary.latency.p99_ms for summary in rows if summary.latency],
    }
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    count = len(series)
    width = 0.8 / count
    positions = list(range(len(labels)))
    for index, (name, values) in enumerate(series.items()):
        offset = (index - (count - 1) / 2) * width
        ax.bar(
            [pos + offset for pos in positions],
            values,
            width=width,
            label=name,
            color=COLORS[index],
        )
    ax.set_xticks(positions, labels, rotation=15, ha="right")
    ax.set_ylabel("Latency (ms)")
    ax.set_title(f"Latency percentiles at concurrency {level}")
    ax.legend()
    fig.tight_layout()
    return _save(fig, path)


def chart_histogram(run: RunResult, path: Path) -> Path | None:
    level = select_concurrency(run.concurrency_levels)
    if level is None:
        return None
    candidates = [
        summary
        for summary in run.summaries
        if summary.role == "performance"
        and summary.concurrency == level
        and summary.latency is not None
        and len(summary.latencies_ms) >= 2
    ]
    if not candidates:
        return None

    def _median(summary: EndpointRunSummary) -> float:
        if summary.latency is None:
            return 0
        return summary.latency.median_ms

    chosen = max(candidates, key=_median)
    _apply_style()
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    bins = min(20, max(5, len(set(chosen.latencies_ms))))
    ax.hist(chosen.latencies_ms, bins=bins, color=COLORS[0], edgecolor="white")
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Requests")
    ax.set_title(f"{chosen.endpoint} latency at concurrency {level}")
    fig.tight_layout()
    return _save(fig, path)


def _outcome_rows(summaries: list[EndpointRunSummary]) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    order: list[str] = []
    for summary in summaries:
        if summary.role not in {"fault", "auth_check"}:
            continue
        pairs = [
            (f"{summary.endpoint} status {code}", count)
            for code, count in summary.status_counts.items()
        ]
        for name, count in summary.exception_counts.items():
            pairs.append((f"{summary.endpoint} {name}", count))
        for label, count in pairs:
            if label not in totals:
                order.append(label)
                totals[label] = 0
            totals[label] += count
    return [(label, totals[label]) for label in order]


def chart_errors(run: RunResult, path: Path) -> Path | None:
    rows = _outcome_rows(run.summaries)
    if not rows:
        return None
    rows.sort(key=lambda item: item[1], reverse=True)
    _apply_style()
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    labels = [label for label, _ in rows]
    values = [value for _, value in rows]
    ax.barh(list(range(len(labels))), values, color=COLORS[4])
    ax.set_yticks(list(range(len(labels))), labels)
    ax.invert_yaxis()
    ax.set_xlabel("Responses")
    ax.set_title("Fault-injection and auth-check outcomes")
    fig.tight_layout()
    return _save(fig, path)


def chart_trend(
    history: list[dict[str, object]],
    path: Path,
    *,
    scenario: str | None = None,
    preferred_concurrency: int = 10,
) -> Path | None:
    if scenario is not None:
        history = [item for item in history if item.get("scenario") == scenario]
    if len(history) < 2:
        return None
    levels: list[int] = []
    for run in history:
        points = run.get("points")
        if not isinstance(points, list):
            continue
        for point in points:
            if isinstance(point, dict) and isinstance(point.get("concurrency"), int):
                levels.append(point["concurrency"])
    level = select_concurrency(levels, preferred_concurrency)
    if level is None:
        return None

    series: dict[str, list[float | None]] = {}
    labels: list[str] = []
    for run in history:
        started = str(run.get("started_at", ""))
        if "T" in started:
            labels.append(started.split("T", 1)[1][:8])
        else:
            labels.append(started or str(run.get("run_id", "")))
        points = run.get("points")
        seen: set[str] = set()
        if isinstance(points, list):
            for point in points:
                if not isinstance(point, dict):
                    continue
                if point.get("role") not in {None, "performance"}:
                    continue
                if point.get("concurrency") != level:
                    continue
                endpoint = str(point.get("endpoint"))
                seen.add(endpoint)
                series.setdefault(endpoint, [None] * (len(labels) - 1))
                value = point.get("p95_ms")
                series[endpoint].append(float(value) if isinstance(value, (int, float)) else None)
        for endpoint, values in series.items():
            if endpoint not in seen:
                values.append(None)
            if len(values) < len(labels):
                values.extend([None] * (len(labels) - len(values)))

    plotted = {
        name: values
        for name, values in series.items()
        if any(value is not None for value in values)
    }
    if not plotted:
        return None
    _apply_style()
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    for name, values in plotted.items():
        xs = [index for index, value in enumerate(values) if value is not None]
        ys = [value for value in values if value is not None]
        ax.plot(xs, ys, marker="o", linewidth=2, label=name)
    ax.set_xticks(range(len(labels)), labels, rotation=20, ha="right")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title(f"p95 trend at concurrency {level}")
    ax.legend(ncol=2)
    fig.tight_layout()
    return _save(fig, path)


def write_charts(run: RunResult, directory: Path) -> list[Path]:
    writers = (
        ("throughput_vs_concurrency.png", chart_throughput),
        ("p95_vs_concurrency.png", chart_p95),
        ("latency_percentiles.png", chart_latency_bars),
        ("latency_histogram.png", chart_histogram),
        ("error_breakdown.png", chart_errors),
    )
    written: list[Path] = []
    for name, writer in writers:
        path = writer(run, directory / name)
        if path is not None:
            written.append(path)
    return written
