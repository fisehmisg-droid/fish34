"""Run blocking sync code without freezing the asyncio event loop (Telegram bot responsiveness)."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Callable, TypeVar

T = TypeVar("T")


async def run_blocking(func: Callable[..., T], /, *args, **kwargs) -> T:
    """Execute ``func(*args, **kwargs)`` in the default thread pool."""
    return await asyncio.to_thread(partial(func, *args, **kwargs))
