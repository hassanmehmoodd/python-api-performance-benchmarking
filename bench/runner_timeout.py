"""Build the per-request timeout used by the benchmark client."""

from __future__ import annotations

import httpx


def request_timeout(seconds: float) -> httpx.Timeout:
    """Apply one budget to connect, read, write, and pool acquisition.

    HTTPX raises a distinct exception for each phase, which is how the report
    separates connect timeouts from read timeouts.
    """

    return httpx.Timeout(connect=seconds, read=seconds, write=seconds, pool=seconds)
