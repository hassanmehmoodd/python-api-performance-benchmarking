"""Capture the machine description stored with a benchmark run."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def _cpu_model() -> str:
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return platform.processor() or "unknown"
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip() or "unknown"
    return platform.processor() or "unknown"


def collect_environment() -> dict[str, str | int]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": _cpu_model(),
        "logical_cpus": os.cpu_count() or 0,
        "host": platform.node(),
    }
