"""Append compact run summaries so later runs can draw a trend."""

from __future__ import annotations

import json
from pathlib import Path

from bench.models import RunResult


def history_document(run: RunResult) -> dict[str, object]:
    points: list[dict[str, object]] = []
    for summary in run.summaries:
        points.append(
            {
                "endpoint": summary.endpoint,
                "role": summary.role,
                "concurrency": summary.concurrency,
                "p95_ms": None if summary.latency is None else summary.latency.p95_ms,
                "throughput_rps": summary.throughput_rps,
                "error_rate": summary.error_rate,
                "successes": summary.successes,
                "requests": summary.requests,
            }
        )
    return {
        "run_id": run.run_id,
        "scenario": run.scenario,
        "started_at": run.started_at,
        "base_url": run.base_url,
        "points": points,
    }


def append_history(directory: Path, run: RunResult) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.run_id}.json"
    if path.exists():
        path = directory / f"{run.run_id}-{run.scenario}.json"
    path.write_text(json.dumps(history_document(run), indent=2) + "\n", encoding="utf-8")
    return path


def load_history(directory: Path) -> list[dict[str, object]]:
    if not directory.is_dir():
        return []
    runs: list[dict[str, object]] = []
    for path in directory.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("points"), list):
            runs.append(payload)
    runs.sort(key=lambda item: str(item.get("started_at", "")))
    return runs
