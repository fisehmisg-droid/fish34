## Abebe EUEE Bot

Production webhook Telegram bot for Grade 12 EUEE preparation.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Set required values in `.env`:

- `BOT_TOKEN`
- `WEBHOOK_URL`
- `WEBHOOK_SECRET`
- `DATABASE_URL`
- `BASE_WEB_URL`
- `ADMIN_TOKEN`
- `ADMIN_USER_ID`
- `TELEBIRR_NUMBER`

Run locally:

```powershell
python bot.py
```

Health check:

- `GET /health` returns 200

## Railway Deployment Checklist

1. Push code to GitHub.
2. Create Railway project from repo.
3. Add a Railway PostgreSQL plugin and copy its `DATABASE_URL` into Variables.
4. Ensure start command is `python bot.py` (already set in `railway.json`).
5. Add all environment variables from `.env.example`.
6. Set `WEBHOOK_URL` to your Railway public URL.
7. Set strong random `WEBHOOK_SECRET` and `ADMIN_TOKEN`.
8. Deploy and confirm logs show webhook registration.
9. Verify:
   - `/health` returns 200
   - Telegram webhook endpoint receives updates
   - `/admin` opens and authenticates
   - payment attempts are written to the database

## Security Notes

- No secrets in source code.
- Webhook secret validation enforced.
- Admin endpoints guarded by token auth and rate limiting.
- Premium expiry enforced per action; tier changes are persistent.

## Data Model

- PostgreSQL is the runtime DB.
- `schema.sql` defines the generic document-store schema used by the bot backend.
