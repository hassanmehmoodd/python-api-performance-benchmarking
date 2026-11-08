"""Result objects produced by a benchmark run."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

TIMEOUT_ERROR_TYPES = frozenset(
    {
        "connect_timeout",
        "read_timeout",
        "write_timeout",
        "pool_timeout",
        "timeout",
    }
)


@dataclass(frozen=True)
class RequestResult:
    endpoint: str
    concurrency: int
    elapsed_ms: float
    status_code: int | None
    error_type: str | None
    ok: bool


@dataclass(frozen=True)
class LatencyStats:
    count: int
    avg_ms: float
    median_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    stdev_ms: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass
class EndpointRunSummary:
    endpoint: str
    role: str
    method: str
    path: str
    concurrency: int
    requests: int
    successes: int
    unexpected_errors: int
    timeouts: int
    error_rate: float
    throughput_rps: float
    attempted_rps: float
    wall_time_s: float
    latency: LatencyStats | None
    status_counts: dict[str, int]
    exception_counts: dict[str, int]
    latencies_ms: list[float]
    allow_zero_success: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "endpoint": self.endpoint,
            "role": self.role,
            "method": self.method,
            "path": self.path,
            "concurrency": self.concurrency,
            "requests": self.requests,
            "successes": self.successes,
            "unexpected_errors": self.unexpected_errors,
            "timeouts": self.timeouts,
            "error_rate": self.error_rate,
            "throughput_rps": self.throughput_rps,
            "attempted_rps": self.attempted_rps,
            "wall_time_s": self.wall_time_s,
            "allow_zero_success": self.allow_zero_success,
            "latency": None if self.latency is None else self.latency.as_dict(),
            "status_counts": self.status_counts,
            "exception_counts": self.exception_counts,
            "latencies_ms": self.latencies_ms,
        }


@dataclass
class RunResult:
    run_id: str
    scenario: str
    description: str
    base_url: str
    started_at: str
    finished_at: str
    environment: dict[str, str | int]
    token_acquisition_ms: float | None
    warmup_requests: int
    timeout_seconds: float
    concurrency_levels: list[int]
    requests_per_level: int
    summaries: list[EndpointRunSummary] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "description": self.description,
            "base_url": self.base_url,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "environment": self.environment,
            "token_acquisition_ms": self.token_acquisition_ms,
            "warmup_requests": self.warmup_requests,
            "timeout_seconds": self.timeout_seconds,
            "concurrency_levels": self.concurrency_levels,
            "requests_per_level": self.requests_per_level,
            "summaries": [summary.as_dict() for summary in self.summaries],
        }
