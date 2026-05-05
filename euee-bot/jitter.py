"""Simple async rate limiter with jitter for handler protection.

This module provides a decorator `rate_limited` that applies a token-bucket
rate limit per key (by default per Telegram user id) and a small random
jitter sleep to desynchronize requests. It's intentionally lightweight and
process-local. For production/multi-process deployments use Redis or
another external store for shared limiting.
"""

from __future__ import annotations

import asyncio
import functools
import os
import random
import time
from typing import Callable, Optional

_REDIS_URL = os.getenv("REDIS_URL")
_REDIS_CLIENT = None

try:
    if _REDIS_URL:
        import redis.asyncio as aioredis  # type: ignore
    else:
        aioredis = None
except Exception:
    aioredis = None

_STORE: dict = {}
_STORE_LOCK = asyncio.Lock()


class RateLimiter:
    def __init__(self, max_tokens: float = 5.0, refill_rate: float = 0.2):
        # max_tokens: maximum burst
        # refill_rate: tokens per second
        self.max_tokens = float(max_tokens)
        self.refill_rate = float(refill_rate)

    async def allow(self, key: str) -> bool:
        # Prefer Redis-backed limiter when available
        if aioredis and _REDIS_URL:
            try:
                return await _redis_allow(key, self.max_tokens, self.refill_rate)
            except Exception:
                # Fall back to local if Redis fails
                pass

        # In-process token-bucket fallback
        now = time.monotonic()
        async with _STORE_LOCK:
            tokens, last = _STORE.get(key, (self.max_tokens, now))
            if now > last:
                tokens = min(self.max_tokens, tokens + (now - last) * self.refill_rate)
            allowed = tokens >= 1.0
            if allowed:
                tokens -= 1.0
            _STORE[key] = (tokens, now)
            return allowed


async def _get_redis_client():
    global _REDIS_CLIENT
    if not aioredis or not _REDIS_URL:
        return None
    if _REDIS_CLIENT:
        return _REDIS_CLIENT
    # Create redis client lazily
    _REDIS_CLIENT = aioredis.from_url(_REDIS_URL, decode_responses=True)
    return _REDIS_CLIENT


# Lua script for atomic token-bucket stored as hash {tokens, last}
_TB_LUA = """
local key = KEYS[1]
local cap = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local req = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'last')
local tokens = tonumber(data[1]) or cap
local last = tonumber(data[2]) or now
local delta = math.max(0, now - last)
tokens = math.min(cap, tokens + delta * rate)
local allowed = tokens >= req
if allowed then
  tokens = tokens - req
end
redis.call('HMSET', key, 'tokens', tokens, 'last', now)
redis.call('EXPIRE', key, 3600)
if allowed then return 1 else return 0 end
"""


async def _redis_allow(key: str, cap: float, rate: float, requested: int = 1) -> bool:
    client = await _get_redis_client()
    if client is None:
        raise RuntimeError("Redis client not available")
    now = time.monotonic()
    try:
        # Use EVAL to run the token-bucket atomically
        res = await client.eval(_TB_LUA, 1, key, str(cap), str(rate), str(now), str(requested))
        # redis-py returns int
        return bool(int(res))
    except Exception:
        # Try a safe fallback using simple INCR/TTL logic (best-effort)
        try:
            h = await client.hgetall(key)
            tokens = float(h.get('tokens', cap))
            last = float(h.get('last', now))
            delta = max(0.0, now - last)
            tokens = min(cap, tokens + delta * rate)
            allowed = tokens >= requested
            if allowed:
                tokens -= requested
            await client.hset(key, mapping={'tokens': tokens, 'last': now})
            await client.expire(key, 3600)
            return allowed
        except Exception:
            raise


def _get_user_key_from_update(update) -> Optional[str]:
    try:
        if getattr(update, 'effective_user', None) and update.effective_user:
            return f"user:{update.effective_user.id}"
        if getattr(update, 'effective_chat', None) and update.effective_chat:
            return f"chat:{update.effective_chat.id}"
    except Exception:
        return None
    return None


def _is_rate_limited_callable(func: Callable) -> bool:
    current = func
    while current is not None:
        if getattr(current, "_rate_limited", False):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def rate_limited(max_tokens: float = 5.0, refill_rate: float = 0.2, jitter_max: float = 0.12):
    """Decorator for async handlers.

    Usage:
      @rate_limited(max_tokens=3, refill_rate=0.2)
      async def handler(update, ctx): ...

    If the rate limit is exceeded, the decorator sends a short 'slow down'
    message and returns early.
    """

    def _decorator(func: Callable):
        if _is_rate_limited_callable(func):
            return func

        limiter = RateLimiter(max_tokens=max_tokens, refill_rate=refill_rate)

        @functools.wraps(func)
        async def _wrapped(update, ctx, *args, **kwargs):
            key = _get_user_key_from_update(update) or "anon"
            allowed = await limiter.allow(key)
            if not allowed:
                # Try to reply gracefully depending on update shape
                try:
                    if getattr(update, 'callback_query', None) and update.callback_query:
                        await update.callback_query.answer('Too many requests — please slow down.', show_alert=False)
                    elif getattr(update, 'message', None) and update.message:
                        await update.message.reply_text('Too many requests — please slow down.')
                except Exception:
                    pass
                return

            # small random jitter to make processing timing less predictable
            try:
                await asyncio.sleep(random.uniform(0.0, float(jitter_max)))
            except Exception:
                # If sleep fails for any reason, continue without jitter
                pass

            return await func(update, ctx, *args, **kwargs)

        _wrapped._rate_limited = True
        return _wrapped

    return _decorator
