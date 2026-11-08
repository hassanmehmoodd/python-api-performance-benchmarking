"""Host allowlist, acknowledgement, and concurrency caps."""

from __future__ import annotations

import pytest

from bench.config import EndpointConfig, ScenarioConfig, guard_scenario
from bench.safety import (
    DEFAULT_ALLOWED_HOSTS,
    HARD_CONCURRENCY_CEILING,
    SafetyError,
    SafetySettings,
    ensure_concurrency_allowed,
    ensure_host_allowed,
    ensure_request_budget,
    load_safety_settings,
)


def _scenario(base_url: str, levels: list[int] | None = None, requests: int = 1) -> ScenarioConfig:
    return ScenarioConfig(
        name="guard",
        base_url=base_url,
        concurrency_levels=levels or [1],
        requests_per_level=requests,
        endpoints=[EndpointConfig(name="health", path="/health")],
    )


def _settings(**overrides: object) -> SafetySettings:
    data: dict[str, object] = {
        "allowed_hosts": DEFAULT_ALLOWED_HOSTS,
        "max_concurrency": 100,
        "allow_remote": False,
        "acknowledge_remote": False,
    }
    data.update(overrides)
    return SafetySettings(**data)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://localhost/health",
        "http://LOCALHOST:8000",
        "http://[::1]:8000/",
        "https://user:pass@127.0.0.1/private",
    ],
)
def test_loopback_hosts_are_allowed(url: str) -> None:
    ensure_host_allowed(url, _settings())
    guard_scenario(_scenario(url), _settings())


def test_remote_host_requires_both_opt_ins() -> None:
    scenario = _scenario("https://example.com/api")
    with pytest.raises(SafetyError, match="authorized") as denied:
        guard_scenario(scenario, _settings())
    message = str(denied.value)
    assert "own" in message
    assert "BENCH_ALLOW_REMOTE" in message

    with pytest.raises(SafetyError):
        guard_scenario(scenario, _settings(allow_remote=True))
    with pytest.raises(SafetyError):
        guard_scenario(scenario, _settings(acknowledge_remote=True))

    ensure_host_allowed(
        "https://example.com/api",
        _settings(allow_remote=True, acknowledge_remote=True),
    )


@pytest.mark.parametrize("url", ["ftp://127.0.0.1", "http://", "not-a-url", "http:///missing"])
def test_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises(SafetyError):
        ensure_host_allowed(url, _settings())


def test_concurrency_cap_and_hard_ceiling() -> None:
    with pytest.raises(SafetyError, match="cap"):
        ensure_concurrency_allowed([101], _settings(max_concurrency=100))
    with pytest.raises(SafetyError):
        SafetySettings(max_concurrency=HARD_CONCURRENCY_CEILING + 1)
    ensure_concurrency_allowed([50], _settings(max_concurrency=50))
    with pytest.raises(SafetyError):
        guard_scenario(_scenario("http://127.0.0.1", levels=[25]), _settings(max_concurrency=10))


def test_request_budget() -> None:
    with pytest.raises(SafetyError, match="100000"):
        guard_scenario(
            _scenario("http://127.0.0.1", levels=[1] * 21, requests=5000),
            _settings(),
        )
    with pytest.raises(SafetyError, match="cap of 5000"):
        ensure_request_budget(1, [5001])


def test_allowlist_from_the_environment_does_not_need_remote_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BENCH_ALLOWED_HOSTS", "api.internal, localhost")
    monkeypatch.delenv("BENCH_ALLOW_REMOTE", raising=False)
    monkeypatch.delenv("BENCH_ACKNOWLEDGE_REMOTE", raising=False)
    settings = load_safety_settings()
    ensure_host_allowed("https://api.internal/v1", settings)
    with pytest.raises(SafetyError):
        ensure_host_allowed("https://example.com", settings)


def test_max_concurrency_env_cannot_exceed_the_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENCH_MAX_CONCURRENCY", "500")
    with pytest.raises(SafetyError, match="200"):
        load_safety_settings()
    monkeypatch.setenv("BENCH_MAX_CONCURRENCY", "nope")
    with pytest.raises(SafetyError, match="integer"):
        load_safety_settings()


def test_remote_flags_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENCH_ALLOW_REMOTE", "true")
    monkeypatch.setenv("BENCH_ACKNOWLEDGE_REMOTE", "1")
    settings = load_safety_settings()
    assert settings.allow_remote is True
    assert settings.acknowledge_remote is True
    ensure_host_allowed("https://example.com", settings)
