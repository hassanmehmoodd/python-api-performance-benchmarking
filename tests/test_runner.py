"""Runner concurrency, auth, and error categories."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time

import httpx
import pytest

from bench.auth import AuthenticationError, classify_exception
from bench.config import AuthConfig, EndpointConfig, ScenarioConfig
from bench.runner import perform_request, run_batch, run_scenario
from bench.safety import SafetyError, SafetySettings
from demo_api.app import app


def test_exception_categories() -> None:
    assert classify_exception(httpx.ConnectTimeout("connect")) == "connect_timeout"
    assert classify_exception(httpx.ReadTimeout("read")) == "read_timeout"
    assert classify_exception(httpx.WriteTimeout("write")) == "write_timeout"
    assert classify_exception(httpx.PoolTimeout("pool")) == "pool_timeout"
    assert classify_exception(httpx.ConnectError("refused")) == "connect_error"
    assert classify_exception(RuntimeError("other")) == "unexpected_error"


async def test_run_batch_caps_in_flight_work() -> None:
    from bench.models import RequestResult

    current = 0
    peak = 0

    async def worker() -> RequestResult:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        return RequestResult("health", 5, 50.0, 200, None, True)

    results, wall = await run_batch(5, 10, worker)
    assert len(results) == 10
    assert peak == 5
    assert 0.09 < wall < 0.35


def _scenario(password: str = "demo-pass") -> ScenarioConfig:
    return ScenarioConfig(
        name="local",
        base_url="http://127.0.0.1",
        concurrency_levels=[2],
        requests_per_level=4,
        timeout_seconds=2,
        auth=AuthConfig(username="demo", password=password),
        endpoints=[
            EndpointConfig(name="health", path="/health"),
            EndpointConfig(name="secure_profile", path="/api/secure/profile", auth=True),
            EndpointConfig(
                name="secure_unauthorized",
                path="/api/secure/profile",
                role="auth_check",
                expected_statuses=[401],
            ),
        ],
    )


async def test_auth_flow_against_the_demo_app() -> None:
    result = await run_scenario(
        _scenario(),
        SafetySettings(),
        transport=httpx.ASGITransport(app=app),
    )
    by_name = {summary.endpoint: summary for summary in result.summaries}
    assert by_name["health"].successes == 4
    assert by_name["secure_profile"].successes == 4
    assert by_name["secure_profile"].error_rate == 0
    assert by_name["secure_unauthorized"].successes == 4
    assert by_name["secure_unauthorized"].status_counts == {"401": 4}
    assert result.token_acquisition_ms is not None
    assert result.token_acquisition_ms >= 0


async def test_bad_password_stops_the_run() -> None:
    scenario = _scenario(password="wrong-password")
    with pytest.raises(AuthenticationError, match="status 401"):
        await run_scenario(scenario, SafetySettings(), transport=httpx.ASGITransport(app=app))


async def test_unexpected_status_is_classified() -> None:
    scenario = ScenarioConfig(
        name="faults",
        base_url="http://127.0.0.1",
        concurrency_levels=[1],
        requests_per_level=3,
        endpoints=[
            EndpointConfig(
                name="flaky_error",
                path="/api/flaky",
                role="fault",
                params={"mode": "error", "status_code": 503},
            )
        ],
    )
    result = await run_scenario(
        scenario,
        SafetySettings(),
        transport=httpx.ASGITransport(app=app),
    )
    summary = result.summaries[0]
    assert summary.successes == 0
    assert summary.status_counts == {"503": 3}
    assert summary.exception_counts == {"http_status": 3}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("demo API did not start")


async def test_read_timeout_is_categorized() -> None:
    # ASGITransport does not enforce client timeouts, so this check uses a real socket.
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "demo_api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        scenario = ScenarioConfig(
            name="timeouts",
            base_url=f"http://127.0.0.1:{port}",
            concurrency_levels=[1],
            requests_per_level=2,
            timeout_seconds=0.05,
            endpoints=[
                EndpointConfig(
                    name="flaky_timeout",
                    path="/api/flaky",
                    role="fault",
                    timeout_seconds=0.05,
                    allow_zero_success=True,
                    params={"mode": "slow", "delay_ms": 400},
                )
            ],
        )
        result = await run_scenario(scenario, SafetySettings())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    summary = result.summaries[0]
    assert summary.exception_counts.get("read_timeout") == 2
    assert summary.latency is None
    assert summary.successes == 0


async def test_remote_target_does_not_open_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"client created: {args} {kwargs}")

    monkeypatch.setattr("bench.runner.httpx.AsyncClient", boom)
    scenario = ScenarioConfig(
        name="remote",
        base_url="http://example.com",
        concurrency_levels=[1],
        requests_per_level=1,
        endpoints=[EndpointConfig(name="health", path="/health")],
    )
    with pytest.raises(SafetyError, match="authorized"):
        await run_scenario(scenario, SafetySettings())


async def test_perform_request_records_expected_status() -> None:
    endpoint = EndpointConfig(
        name="secure_unauthorized",
        path="/api/secure/profile",
        expected_statuses=[401],
        role="auth_check",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
    ) as client:
        result = await perform_request(client, endpoint, {}, 2, concurrency=1)
    assert result.ok is True
    assert result.status_code == 401
    assert result.error_type is None
