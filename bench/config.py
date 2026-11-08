"""Scenario files and the safety checks applied before a run starts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from bench.safety import (
    MAX_REQUESTS_PER_CELL,
    SafetySettings,
    ensure_concurrency_allowed,
    ensure_host_allowed,
    ensure_request_budget,
)

EndpointRole = Literal["performance", "auth_check", "fault"]


class ConfigError(ValueError):
    """The scenario file could not be loaded."""


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_path: str = "/auth/token"
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

    @field_validator("token_path")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("token_path must start with /")
        return value


class EndpointConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    method: str = "GET"
    path: str
    params: dict[str, Any] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    auth: bool = False
    expected_statuses: list[int] = Field(default_factory=lambda: [200])
    timeout_seconds: float | None = Field(default=None, gt=0, le=120)
    requests: int | None = Field(default=None, ge=1, le=MAX_REQUESTS_PER_CELL)
    role: EndpointRole = "performance"
    allow_zero_success: bool = False

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        method = value.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
            raise ValueError(f"unsupported method {value}")
        return method

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("endpoint path must start with /")
        return value

    @field_validator("expected_statuses")
    @classmethod
    def _statuses(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("expected_statuses must not be empty")
        if any(code < 100 or code > 599 for code in value):
            raise ValueError("expected_statuses must be HTTP status codes")
        return value


class ScenarioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    description: str = ""
    base_url: str
    concurrency_levels: list[int] = Field(min_length=1)
    requests_per_level: int = Field(ge=1, le=MAX_REQUESTS_PER_CELL)
    timeout_seconds: float = Field(default=5.0, gt=0, le=120)
    warmup_requests: int = Field(default=0, ge=0, le=100)
    auth: AuthConfig | None = None
    endpoints: list[EndpointConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross_checks(self) -> Self:
        names = [endpoint.name for endpoint in self.endpoints]
        if len(names) != len(set(names)):
            raise ValueError("endpoint names must be unique")
        if any(endpoint.auth for endpoint in self.endpoints) and self.auth is None:
            raise ValueError("endpoints with auth: true require an auth block")
        return self


def load_scenario(path: Path) -> ScenarioConfig:
    if not path.is_file():
        raise ConfigError(f"Scenario file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"Scenario file must be a mapping: {path}")
    try:
        return ScenarioConfig.model_validate(loaded)
    except ValidationError as exc:
        raise ConfigError(f"Invalid scenario {path}:\n{exc}") from exc


def scheduled_requests(scenario: ScenarioConfig) -> int:
    total = scenario.warmup_requests * len(scenario.endpoints)
    for endpoint in scenario.endpoints:
        count = endpoint.requests or scenario.requests_per_level
        total += count * len(scenario.concurrency_levels)
    if scenario.auth is not None:
        total += 1
    return total


def guard_scenario(scenario: ScenarioConfig, settings: SafetySettings) -> None:
    """Refuse a scenario that breaks the host, concurrency, or volume limits."""

    ensure_host_allowed(scenario.base_url, settings)
    ensure_concurrency_allowed(scenario.concurrency_levels, settings)
    counts = [endpoint.requests or scenario.requests_per_level for endpoint in scenario.endpoints]
    ensure_request_budget(scheduled_requests(scenario), counts)
