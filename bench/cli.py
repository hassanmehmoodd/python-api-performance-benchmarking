"""Command-line entry point for the benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from bench.auth import AuthenticationError
from bench.baseline import (
    baseline_document,
    compare_metrics,
    load_baseline,
    metrics_from_summary_payload,
    performance_metrics,
    save_baseline,
)
from bench.charts import chart_trend, write_charts
from bench.config import ConfigError, guard_scenario, load_scenario
from bench.export import write_summary_csv, write_summary_json
from bench.history import append_history, load_history
from bench.models import EndpointRunSummary
from bench.report import fmt_ms, render_html, render_markdown, zero_success_labels
from bench.runner import run_scenario
from bench.safety import SafetyError, load_safety_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bench",
        description=(
            "Benchmark a local FastAPI demo, or another HTTP service you own "
            "or are authorized to test."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m bench run --scenario scenarios/smoke.yaml --output-dir results/smoke\n"
            "  python -m bench run --scenario scenarios/portfolio.yaml "
            "--output-dir results/latest \\\n"
            "      --history-dir results/history --save-baseline results/baseline.json\n"
            "  python -m bench run --scenario scenarios/portfolio.yaml "
            "--output-dir results/latest \\\n"
            "      --history-dir results/history --compare-baseline results/baseline.json\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Execute a scenario and write reports")
    run.add_argument("--scenario", required=True, type=Path)
    run.add_argument("--output-dir", required=True, type=Path)
    run.add_argument("--history-dir", type=Path)
    run.add_argument("--save-baseline", type=Path)
    run.add_argument("--compare-baseline", type=Path)
    run.add_argument("--p95-regression-pct", type=float, default=20.0)
    run.add_argument("--p95-abs-floor-ms", type=float, default=5.0)
    run.add_argument("--throughput-regression-pct", type=float, default=15.0)
    run.add_argument("--throughput-abs-floor-rps", type=float, default=1.0)
    run.add_argument(
        "--acknowledge-remote",
        action="store_true",
        help=(
            "Acknowledge that a non-allowlisted target is owned or authorized. "
            "Also requires BENCH_ALLOW_REMOTE=1."
        ),
    )
    run.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit 3 when the baseline comparison reports a regression.",
    )
    run.add_argument("--no-charts", action="store_true")

    compare = sub.add_parser("compare", help="Compare a saved summary JSON with a baseline")
    compare.add_argument("--baseline", required=True, type=Path)
    compare.add_argument("--current", required=True, type=Path)
    compare.add_argument("--p95-regression-pct", type=float, default=20.0)
    compare.add_argument("--p95-abs-floor-ms", type=float, default=5.0)
    compare.add_argument("--throughput-regression-pct", type=float, default=15.0)
    compare.add_argument("--throughput-abs-floor-rps", type=float, default=1.0)
    compare.add_argument("--fail-on-regression", action="store_true")
    return parser


def _print_progress(summary: EndpointRunSummary) -> None:
    p95 = "n/a" if summary.latency is None else f"{fmt_ms(summary.latency.p95_ms)} ms"
    print(
        f"{summary.endpoint:<22} c={summary.concurrency:<3} "
        f"ok={summary.successes}/{summary.requests:<4} "
        f"rps={summary.throughput_rps:8.1f} p95={p95:<12} "
        f"errors={summary.unexpected_errors}",
        flush=True,
    )


def _thresholds(args: argparse.Namespace) -> dict[str, float]:
    return {
        "p95_regression_pct": args.p95_regression_pct,
        "p95_abs_floor_ms": args.p95_abs_floor_ms,
        "throughput_regression_pct": args.throughput_regression_pct,
        "throughput_abs_floor_rps": args.throughput_abs_floor_rps,
    }


def _relative_charts(paths: list[Path], output_dir: Path) -> list[str]:
    relative: list[str] = []
    for path in paths:
        relative.append(path.relative_to(output_dir).as_posix())
    return relative


def _cmd_run(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    settings = load_safety_settings().with_acknowledgement(args.acknowledge_remote)
    guard_scenario(scenario, settings)
    print(
        f"Benchmarking {scenario.base_url} ({scenario.name}). "
        "Only test systems you own or are authorized to test.",
        flush=True,
    )
    run = asyncio.run(run_scenario(scenario, settings, progress=_print_progress))
    comparison = None
    if args.compare_baseline:
        comparison = compare_metrics(
            performance_metrics(run),
            _baseline_metrics(load_baseline(args.compare_baseline)),
            **_thresholds(args),
        )
    history: list[dict[str, object]] = []
    if args.history_dir:
        append_history(args.history_dir, run)
        history = load_history(args.history_dir)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    write_summary_json(run, output_dir / "summary.json", comparison)
    write_summary_csv(run.summaries, output_dir / "summary.csv")

    chart_paths: list[Path] = []
    if not args.no_charts:
        chart_paths.extend(write_charts(run, output_dir / "charts"))
        trend = chart_trend(
            history,
            output_dir / "charts" / "p95_trend.png",
            scenario=run.scenario,
        )
        if trend is not None:
            chart_paths.append(trend)

    relative = _relative_charts(chart_paths, output_dir)
    (output_dir / "report.md").write_text(
        render_markdown(run, comparison, relative),
        encoding="utf-8",
    )
    (output_dir / "report.html").write_text(
        render_html(run, comparison, relative),
        encoding="utf-8",
    )
    if args.save_baseline:
        save_baseline(args.save_baseline, baseline_document(run))
        print(f"Saved baseline to {args.save_baseline}", flush=True)
    print(f"Wrote {output_dir / 'report.md'}", flush=True)

    failed = zero_success_labels(run)
    if failed:
        print(
            "Endpoints with zero successes: " + ", ".join(failed),
            file=sys.stderr,
        )
        return 2
    if args.fail_on_regression and comparison is not None and comparison.regressions:
        print(
            f"{len(comparison.regressions)} metric(s) regressed past the threshold.",
            file=sys.stderr,
        )
        return 3
    return 0


def _baseline_metrics(document: dict[str, object]) -> list[dict[str, object]]:
    metrics = document.get("metrics")
    if not isinstance(metrics, list) or not all(isinstance(item, dict) for item in metrics):
        raise ConfigError("Baseline metrics must be a list of objects.")
    return [dict(item) for item in metrics]


def _cmd_compare(args: argparse.Namespace) -> int:
    try:
        current_payload = json.loads(args.current.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Current summary is not valid JSON: {args.current}") from exc
    if not isinstance(current_payload, dict):
        raise ConfigError("Current summary must be a JSON object.")
    comparison = compare_metrics(
        metrics_from_summary_payload(current_payload),
        _baseline_metrics(load_baseline(args.baseline)),
        **_thresholds(args),
    )
    print(json.dumps(comparison.as_dict(), indent=2))
    if args.fail_on_regression and comparison.regressions:
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "compare":
            return _cmd_compare(args)
    except (SafetyError, ConfigError, AuthenticationError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Unknown command {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
