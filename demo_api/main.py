"""Run the local demo API on the loopback interface."""

from __future__ import annotations

import os
import sys

import uvicorn


def main() -> None:
    host = os.environ.get("DEMO_API_HOST", "127.0.0.1")
    raw_port = os.environ.get("DEMO_API_PORT", "8000")
    try:
        port = int(raw_port)
    except ValueError:
        print(f"DEMO_API_PORT must be an integer, got {raw_port!r}", file=sys.stderr)
        raise SystemExit(1) from None
    uvicorn.run(
        "demo_api.app:app",
        host=host,
        port=port,
        access_log=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
