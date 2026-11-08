"""Save a baseline and flag later regressions.

A latency regression is recorded only when p95 grows by more than the percent
threshold and by more than the absolute floor. The floor keeps sub-millisecond
jitter on fast endpoints from looking like a regression. Throughput uses the
same two-part rule in the other direction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from bench.config import ConfigError
from bench.models import RunResult


@dataclass(frozen=True)
class MetricComparison:
    endpoint: str
    concurrency: int
    metric: str
    baseline: float | None
    current: float | None
    delta_pct: float | None
    delta_abs: float | None
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "concurrency": self.concurrency,
            "metric": self.metric,
            "baseline": self.baseline,
            "current": self.current,
            "delta_pct": self.delta_pct,
            "delta_abs": self.delta_abs,
            "status": self.status,
        }


@dataclass(frozen=True)
class ComparisonReport:
    p95_regression_pct: float
    p95_abs_floor_ms: float
    throughput_regression_pct: float
    throughput_abs_floor_rps: float
    rows: list[MetricComparison]

    @property
    def regressions(self) -> list[MetricComparison]:
        return [row for row in self.rows if row.status == "regression"]

    def as_dict(self) -> dict[str, object]:
        return {
            "p95_regression_pct": self.p95_regression_pct,
            "p95_abs_floor_ms": self.p95_abs_floor_ms,
            "throughput_regression_pct": self.throughput_regression_pct,
            "throughput_abs_floor_rps": self.throughput_abs_floor_rps,
            "regressions": len(self.regressions),
            "rows": [row.as_dict() for row in self.rows],
        }


def performance_metrics(run: RunResult) -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    for summary in run.summaries:
        if summary.role != "performance":
            continue
        metrics.append(
            {
                "endpoint": summary.endpoint,
                "concurrency": summary.concurrency,
                "p95_ms": None if summary.latency is None else summary.latency.p95_ms,
                "throughput_rps": summary.throughput_rps,
            }
        )
    return metrics


def baseline_document(run: RunResult) -> dict[str, object]:
    return {
        "created_at": run.finished_at,
        "scenario": run.scenario,
        "base_url": run.base_url,
        "run_id": run.run_id,
        "metrics": performance_metrics(run),
    }


def save_baseline(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ConfigError(f"Baseline not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Baseline is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("metrics"), list):
        raise ConfigError("Baseline must be an object with a metrics list.")
    return payload


def metrics_from_summary_payload(payload: Mapping[str, object]) -> list[dict[str, object]]:
    summaries = payload.get("summaries")
    if not isinstance(summaries, list):
        raise ConfigError("Summary JSON must contain a summaries list.")
    metrics: list[dict[str, object]] = []
    for item in summaries:
        if not isinstance(item, dict):
            raise ConfigError("Each summary must be an object.")
        if item.get("role", "performance") != "performance":
            continue
        latency = item.get("latency")
        p95 = None
        if isinstance(latency, dict):
            p95 = latency.get("p95_ms")
        metrics.append(
            {
                "endpoint": item.get("endpoint"),
                "concurrency": item.get("concurrency"),
                "p95_ms": p95,
                "throughput_rps": item.get("throughput_rps"),
            }
        )
    return metrics


def _key(metric: Mapping[str, object]) -> tuple[str, int]:
    endpoint = metric.get("endpoint")
    concurrency = metric.get("concurrency")
    if not isinstance(endpoint, str) or not isinstance(concurrency, int):
        raise ConfigError("Each metric needs a string endpoint and an integer concurrency.")
    return endpoint, concurrency


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"Expected a number, got {value!r}.")
    return float(value)


def _judge(
    baseline: float,
    current: float,
    *,
    higher_is_worse: bool,
    pct_threshold: float,
    abs_floor: float,
) -> tuple[str, float | None, float]:
    delta_abs = current - baseline
    if baseline == 0:
        return "ok", None, delta_abs
    delta_pct = (delta_abs / baseline) * 100
    if higher_is_worse:
        worse = delta_abs > abs_floor and delta_pct > pct_threshold
        better = -delta_abs > abs_floor and -delta_pct > pct_threshold
    else:
        worse = -delta_abs > abs_floor and -delta_pct > pct_threshold
        better = delta_abs > abs_floor and delta_pct > pct_threshold
    if worse:
        return "regression", delta_pct, delta_abs
    if better:
        return "improvement", delta_pct, delta_abs
    return "ok", delta_pct, delta_abs


def compare_metrics(
    current: Sequence[Mapping[str, object]],
    baseline: Sequence[Mapping[str, object]],
    *,
    p95_regression_pct: float = 20.0,
    p95_abs_floor_ms: float = 5.0,
    throughput_regression_pct: float = 15.0,
    throughput_abs_floor_rps: float = 1.0,
) -> ComparisonReport:
    if (
        min(
            p95_regression_pct,
            p95_abs_floor_ms,
            throughput_regression_pct,
            throughput_abs_floor_rps,
        )
        < 0
    ):
        raise ConfigError("Regression thresholds must be >= 0.")

    current_by_key = {_key(metric): metric for metric in current}
    baseline_by_key = {_key(metric): metric for metric in baseline}
    keys = list(dict.fromkeys([*current_by_key, *baseline_by_key]))
    rows: list[MetricComparison] = []

    for key in keys:
        endpoint, concurrency = key
        current_metric = current_by_key.get(key)
        baseline_metric = baseline_by_key.get(key)
        if current_metric is None or baseline_metric is None:
            present = current_metric or baseline_metric
            assert present is not None
            status = "new" if baseline_metric is None else "missing"
            rows.append(
                MetricComparison(
                    endpoint=endpoint,
                    concurrency=concurrency,
                    metric="p95_ms",
                    baseline=_as_float(present.get("p95_ms")) if baseline_metric else None,
                    current=_as_float(present.get("p95_ms")) if current_metric else None,
                    delta_pct=None,
                    delta_abs=None,
                    status=status,
                )
            )
            rows.append(
                MetricComparison(
                    endpoint=endpoint,
                    concurrency=concurrency,
                    metric="throughput_rps",
                    baseline=_as_float(present.get("throughput_rps")) if baseline_metric else None,
                    current=_as_float(present.get("throughput_rps")) if current_metric else None,
                    delta_pct=None,
                    delta_abs=None,
                    status=status,
                )
            )
            continue

        pairs = (
            (
                "p95_ms",
                _as_float(baseline_metric.get("p95_ms")),
                _as_float(current_metric.get("p95_ms")),
                True,
                p95_regression_pct,
                p95_abs_floor_ms,
            ),
            (
                "throughput_rps",
                _as_float(baseline_metric.get("throughput_rps")),
                _as_float(current_metric.get("throughput_rps")),
                False,
                throughput_regression_pct,
                throughput_abs_floor_rps,
            ),
        )
        for metric_name, base_value, current_value, higher_is_worse, pct, floor in pairs:
            if base_value is None or current_value is None:
                rows.append(
                    MetricComparison(
                        endpoint=endpoint,
                        concurrency=concurrency,
                        metric=metric_name,
                        baseline=base_value,
                        current=current_value,
                        delta_pct=None,
                        delta_abs=None,
                        status="no_data",
                    )
                )
                continue
            status, delta_pct, delta_abs = _judge(
                base_value,
                current_value,
                higher_is_worse=higher_is_worse,
                pct_threshold=pct,
                abs_floor=floor,
            )
            rows.append(
                MetricComparison(
                    endpoint=endpoint,
                    concurrency=concurrency,
                    metric=metric_name,
                    baseline=base_value,
                    current=current_value,
                    delta_pct=delta_pct,
                    delta_abs=delta_abs,
                    status=status,
                )
            )

    return ComparisonReport(
        p95_regression_pct=p95_regression_pct,
        p95_abs_floor_ms=p95_abs_floor_ms,
        throughput_regression_pct=throughput_regression_pct,
        throughput_abs_floor_rps=throughput_abs_floor_rps,
        rows=rows,
    )
