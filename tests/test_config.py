"""Scenario file parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from bench.config import ConfigError, ScenarioConfig, load_scenario
from bench.safety import load_safety_settings

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_scenarios_stay_on_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BENCH_ALLOW_REMOTE", raising=False)
    monkeypatch.delenv("BENCH_ACKNOWLEDGE_REMOTE", raising=False)
    monkeypatch.delenv("BENCH_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("BENCH_MAX_CONCURRENCY", raising=False)
    settings = load_safety_settings()
    for name in ("smoke.yaml", "portfolio.yaml"):
        scenario = load_scenario(ROOT / "scenarios" / name)
        from bench.config import guard_scenario

        guard_scenario(scenario, settings)
        assert scenario.base_url.startswith("http://127.0.0.1")


def test_auth_endpoint_requires_an_auth_block() -> None:
    with pytest.raises(ValueError, match="auth block"):
        ScenarioConfig.model_validate(
            {
                "name": "broken",
                "base_url": "http://127.0.0.1",
                "concurrency_levels": [1],
                "requests_per_level": 1,
                "endpoints": [{"name": "profile", "path": "/secure", "auth": True}],
            }
        )


def test_duplicate_endpoint_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        ScenarioConfig.model_validate(
            {
                "name": "broken",
                "base_url": "http://127.0.0.1",
                "concurrency_levels": [1],
                "requests_per_level": 1,
                "endpoints": [
                    {"name": "health", "path": "/health"},
                    {"name": "health", "path": "/health"},
                ],
            }
        )


def test_invalid_yaml_and_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigError, match="not found"):
        load_scenario(missing)
    broken = tmp_path / "broken.yaml"
    broken.write_text("name: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Could not parse"):
        load_scenario(broken)
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("name: ok\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid scenario"):
        load_scenario(invalid)


def test_portfolio_declares_the_expected_sweep() -> None:
    scenario = load_scenario(ROOT / "scenarios" / "portfolio.yaml")
    assert scenario.concurrency_levels == [1, 5, 10, 25, 50]
    names = [endpoint.name for endpoint in scenario.endpoints]
    assert names == [
        "health",
        "items",
        "item_detail",
        "db_orders",
        "compute",
        "secure_profile",
        "secure_unauthorized",
        "flaky_error",
        "flaky_timeout",
    ]
    timeout = next(endpoint for endpoint in scenario.endpoints if endpoint.name == "flaky_timeout")
    assert timeout.allow_zero_success is True
    assert timeout.timeout_seconds == pytest.approx(0.1)
    secure = next(endpoint for endpoint in scenario.endpoints if endpoint.name == "secure_profile")
    assert secure.auth is True
    denied = next(
        endpoint for endpoint in scenario.endpoints if endpoint.name == "secure_unauthorized"
    )
    assert denied.expected_statuses == [401]
    assert denied.auth is False
