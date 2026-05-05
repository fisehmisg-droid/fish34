Redis-backed Rate Limiting and Jitter
===================================

Summary
-------

This project now supports a Redis-backed atomic token-bucket limiter used by
the `rate_limited` decorator in `jitter.py`. It falls back to a local
in-process limiter when `REDIS_URL` is not set or Redis is unavailable.

How to enable (single process or distributed)
---------------------------------------------

- Provision a Redis instance and make it accessible to your app.
- Set the environment variable `REDIS_URL`, e.g. `redis://:password@host:6379/0`.
- Install the Redis client:

  pip install -r requirements-redis.txt

- Restart your bot process. `jitter.py` will detect `REDIS_URL` and use it.

Recommended infra (multi-layer)
--------------------------------

- Application: Redis token-bucket per-user and per-IP.
- Proxy: Nginx rate limiting for early connection dropping.
- Edge: Cloudflare rate limiting and IP reputation filtering.

Nginx example (basic)
----------------------

In your `server` block:

    limit_req_zone $binary_remote_addr zone=one:10m rate=10r/s;

In the relevant `location`:

    limit_req zone=one burst=20 nodelay;

Cloudflare
----------

Use Cloudflare's "Rate Limiting" rules to block repetitive POST/GET
patterns and challenge or block abusive IPs.

Webhook hardening
-----------------

- Use Telegram webhooks with a secret path (not the default). Example:
  `/webhook/<long-random-token>`
- Require TLS (HTTPS) with a valid cert.
- Restrict allowed updates via the Telegram API to only the types you need.

Notes
-----

- The Redis Lua script stores `{tokens, last}` and uses an expiry to
  automatically clean up idle keys.
- Tune `max_tokens` and `refill_rate` in `rate_limited()` decorator calls.
- Monitor metrics for blocked requests and errors to tune thresholds.
