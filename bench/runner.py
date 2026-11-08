"""Async benchmark runner.

A single ``httpx.AsyncClient`` is shared for the run so keep-alive is real.
In-flight requests at each level are capped with a semaphore, and the client
connection pool is sized to the largest level so the pool itself is not the
bottleneck.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx

from bench.auth import acquire_token, classify_exception
from bench.config import EndpointConfig, ScenarioConfig, guard_scenario
from bench.environment import collect_environment
from bench.models import EndpointRunSummary, RequestResult, RunResult
from bench.runner_timeout import request_timeout
from bench.safety import SafetySettings
from bench.stats import summarize_endpoint

ProgressCallback = Callable[[EndpointRunSummary], None]
_USER_AGENT = "api-performance-benchmark/1.0"


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _run_id(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%S%fZ")


async def run_batch(
    concurrency: int,
    total: int,
    worker: Callable[[], Awaitable[RequestResult]],
) -> tuple[list[RequestResult], float]:
    """Run ``total`` calls with at most ``concurrency`` calls in flight."""

    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    if total < 1:
        raise ValueError("total must be >= 1")
    semaphore = asyncio.Semaphore(concurrency)

    async def limited() -> RequestResult:
        async with semaphore:
            return await worker()

    started = time.perf_counter()
    results = await asyncio.gather(*(limited() for _ in range(total)))
    return list(results), time.perf_counter() - started


async def perform_request(
    client: httpx.AsyncClient,
    endpoint: EndpointConfig,
    headers: dict[str, str],
    timeout_seconds: float,
    *,
    concurrency: int,
) -> RequestResult:
    started = time.perf_counter()
    try:
        response = await client.request(
            endpoint.method,
            endpoint.path,
            params=endpoint.params or None,
            json=endpoint.json_body,
            headers=headers or None,
            timeout=request_timeout(timeout_seconds),
        )
    except httpx.TimeoutException as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return RequestResult(
            endpoint=endpoint.name,
            concurrency=concurrency,
            elapsed_ms=elapsed,
            status_code=None,
            error_type=classify_exception(exc),
            ok=False,
        )
    except httpx.RequestError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return RequestResult(
            endpoint=endpoint.name,
            concurrency=concurrency,
            elapsed_ms=elapsed,
            status_code=None,
            error_type=classify_exception(exc),
            ok=False,
        )
    elapsed = (time.perf_counter() - started) * 1000
    ok = response.status_code in endpoint.expected_statuses
    return RequestResult(
        endpoint=endpoint.name,
        concurrency=concurrency,
        elapsed_ms=elapsed,
        status_code=response.status_code,
        error_type=None if ok else "http_status",
        ok=ok,
    )


def _worker(
    client: httpx.AsyncClient,
    endpoint: EndpointConfig,
    headers: dict[str, str],
    timeout_seconds: float,
    concurrency: int,
) -> Callable[[], Awaitable[RequestResult]]:
    async def send() -> RequestResult:
        return await perform_request(
            client,
            endpoint,
            headers,
            timeout_seconds,
            concurrency=concurrency,
        )

    return send


async def run_scenario(
    scenario: ScenarioConfig,
    settings: SafetySettings,
    *,
    transport: httpx.BaseTransport | None = None,
    progress: ProgressCallback | None = None,
) -> RunResult:
    """Execute a scenario. Safety checks run before any socket is opened."""

    guard_scenario(scenario, settings)
    started_at = datetime.now(UTC)
    max_level = max(scenario.concurrency_levels)
    limits = httpx.Limits(
        max_connections=max_level,
        max_keepalive_connections=max_level,
    )
    summaries = []
    token_acquisition_ms: float | None = None
    async with httpx.AsyncClient(
        base_url=scenario.base_url.rstrip("/"),
        limits=limits,
        timeout=request_timeout(scenario.timeout_seconds),
        transport=transport,
        follow_redirects=False,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    ) as client:
        token: str | None = None
        if scenario.auth is not None:
            token_started = time.perf_counter()
            token = await acquire_token(client, scenario.auth, scenario.timeout_seconds)
            token_acquisition_ms = (time.perf_counter() - token_started) * 1000

        for endpoint in scenario.endpoints:
            headers: dict[str, str] = {}
            if endpoint.auth:
                if token is None:
                    raise RuntimeError(f"{endpoint.name} requires a bearer token.")
                headers["Authorization"] = f"Bearer {token}"
            timeout_seconds = endpoint.timeout_seconds or scenario.timeout_seconds
            warmup = _worker(client, endpoint, headers, timeout_seconds, concurrency=1)
            for _ in range(scenario.warmup_requests):
                await warmup()
            for level in scenario.concurrency_levels:
                total = endpoint.requests or scenario.requests_per_level
                results, wall = await run_batch(
                    level,
                    total,
                    _worker(client, endpoint, headers, timeout_seconds, concurrency=level),
                )
                summary = summarize_endpoint(
                    name=endpoint.name,
                    role=endpoint.role,
                    method=endpoint.method,
                    path=endpoint.path,
                    concurrency=level,
                    allow_zero_success=endpoint.allow_zero_success,
                    results=results,
                    wall_time_s=wall,
                )
                summaries.append(summary)
                if progress is not None:
                    progress(summary)

    finished_at = datetime.now(UTC)
    return RunResult(
        run_id=_run_id(started_at),
        scenario=scenario.name,
        description=scenario.description,
        base_url=scenario.base_url,
        started_at=_stamp(started_at),
        finished_at=_stamp(finished_at),
        environment=collect_environment(),
        token_acquisition_ms=token_acquisition_ms,
        warmup_requests=scenario.warmup_requests,
        timeout_seconds=scenario.timeout_seconds,
        concurrency_levels=list(scenario.concurrency_levels),
        requests_per_level=scenario.requests_per_level,
        summaries=summaries,
    )
