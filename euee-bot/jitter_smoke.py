"""Smoke test for the jitter/limiter functionality.

Run with REDIS_URL set to test the Redis-backed limiter, or without it to test
the in-process fallback.

Example:
  REDIS_URL=redis://localhost:6379 python jitter_smoke.py
"""
import asyncio
import os
import time

from jitter import RateLimiter


async def run_test():
    limiter = RateLimiter(max_tokens=3, refill_rate=0.5)
    key = 'testuser:1'
    print('Testing limiter; burst=3, refill=0.5 token/s')
    for i in range(6):
        allowed = await limiter.allow(key)
        print(f'Attempt {i+1}:', 'allowed' if allowed else 'blocked')
        await asyncio.sleep(0.2)

    print('Waiting 3 seconds to refill...')
    await asyncio.sleep(3)
    for i in range(3):
        allowed = await limiter.allow(key)
        print(f'After-wait Attempt {i+1}:', 'allowed' if allowed else 'blocked')


if __name__ == '__main__':
    asyncio.run(run_test())
