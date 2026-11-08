"""Limits that keep a benchmark pointed at a service you are allowed to test."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1")
DEFAULT_MAX_CONCURRENCY = 100
HARD_CONCURRENCY_CEILING = 200
MAX_REQUESTS_PER_CELL = 5_000
MAX_TOTAL_REQUESTS = 100_000

_TRUE_VALUES = {"1", "true", "yes", "on"}


class SafetyError(ValueError):
    """The benchmark refused to run because a safety check failed."""


@dataclass(frozen=True)
class SafetySettings:
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    allow_remote: bool = False
    acknowledge_remote: bool = False

    def __post_init__(self) -> None:
        hosts = tuple(host.strip().lower() for host in self.allowed_hosts if host and host.strip())
        if not hosts:
            raise SafetyError("The host allowlist must not be empty.")
        if self.max_concurrency < 1 or self.max_concurrency > HARD_CONCURRENCY_CEILING:
            raise SafetyError(
                "Max concurrency must be between 1 and "
                f"{HARD_CONCURRENCY_CEILING}. Got {self.max_concurrency}."
            )
        object.__setattr__(self, "allowed_hosts", hosts)

    def with_acknowledgement(self, acknowledged: bool) -> SafetySettings:
        if not acknowledged or self.acknowledge_remote:
            return self
        return SafetySettings(
            allowed_hosts=self.allowed_hosts,
            max_concurrency=self.max_concurrency,
            allow_remote=self.allow_remote,
            acknowledge_remote=True,
        )


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def load_safety_settings() -> SafetySettings:
    """Read safety settings from the environment.

    Unset variables keep the localhost allowlist and the default concurrency cap.
    """

    raw_hosts = os.environ.get("BENCH_ALLOWED_HOSTS", "").strip()
    if raw_hosts:
        hosts = tuple(part.strip() for part in raw_hosts.split(",") if part.strip())
    else:
        hosts = DEFAULT_ALLOWED_HOSTS

    raw_max = os.environ.get("BENCH_MAX_CONCURRENCY", "").strip()
    if raw_max:
        try:
            max_concurrency = int(raw_max)
        except ValueError as exc:
            raise SafetyError("BENCH_MAX_CONCURRENCY must be an integer.") from exc
    else:
        max_concurrency = DEFAULT_MAX_CONCURRENCY

    return SafetySettings(
        allowed_hosts=hosts,
        max_concurrency=max_concurrency,
        allow_remote=_env_flag("BENCH_ALLOW_REMOTE"),
        acknowledge_remote=_env_flag("BENCH_ACKNOWLEDGE_REMOTE"),
    )


def hostname_of(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SafetyError(
            f"Unsupported base URL {base_url!r}. Use an http or https URL with a host."
        )
    return parsed.hostname.lower()


def ensure_host_allowed(base_url: str, settings: SafetySettings) -> str:
    """Return the hostname when the target is allowed.

    Localhost is allowed by default. Any other host requires both
    ``BENCH_ALLOW_REMOTE=1`` and an explicit acknowledgement. Benchmark only
    systems you own or are authorized to test.
    """

    host = hostname_of(base_url)
    if host in settings.allowed_hosts:
        return host
    if settings.allow_remote and settings.acknowledge_remote:
        return host

    missing: list[str] = []
    if not settings.allow_remote:
        missing.append("set BENCH_ALLOW_REMOTE=1")
    if not settings.acknowledge_remote:
        missing.append("pass --acknowledge-remote or set BENCH_ACKNOWLEDGE_REMOTE=1")
    joined = " and ".join(missing)
    raise SafetyError(
        f"Refusing to benchmark host {host!r}. Benchmark only systems you own or are "
        "authorized to test. The default allowlist is localhost, 127.0.0.1, and ::1. "
        f"To target another authorized host, {joined}."
    )


def ensure_concurrency_allowed(
    levels: list[int] | tuple[int, ...],
    settings: SafetySettings,
) -> None:
    if not levels:
        raise SafetyError("At least one concurrency level is required.")
    for level in levels:
        if level < 1:
            raise SafetyError(f"Concurrency must be >= 1. Got {level}.")
        if level > HARD_CONCURRENCY_CEILING or level > settings.max_concurrency:
            raise SafetyError(
                f"Concurrency {level} exceeds the cap of {settings.max_concurrency} "
                f"(hard ceiling {HARD_CONCURRENCY_CEILING})."
            )


def ensure_request_budget(total_requests: int, per_cell: list[int]) -> None:
    for count in per_cell:
        if count < 1:
            raise SafetyError(f"Request count must be >= 1. Got {count}.")
        if count > MAX_REQUESTS_PER_CELL:
            raise SafetyError(
                f"A single endpoint and concurrency level schedules {count} requests, "
                f"above the cap of {MAX_REQUESTS_PER_CELL}."
            )
    if total_requests > MAX_TOTAL_REQUESTS:
        raise SafetyError(
            f"Scenario schedules {total_requests} requests, above the cap of {MAX_TOTAL_REQUESTS}."
        )
