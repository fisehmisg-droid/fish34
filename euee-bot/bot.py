"""Railway entrypoint for the Abebe Telegram bot web service."""

from __future__ import annotations

import os
import signal
import sys

import uvicorn


def _on_sigterm(signum, frame):
    # FIX: Explicit SIGTERM handling for graceful Railway shutdowns.
    raise SystemExit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _on_sigterm)
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, lifespan="on")


if __name__ == "__main__":
    main()
