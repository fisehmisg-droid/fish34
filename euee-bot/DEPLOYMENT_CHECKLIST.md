Railway / Deployment checklist

1. Required environment variables

- BOT_TOKEN: Telegram bot token
- DATABASE_URL: Railway PostgreSQL connection string
- CHAPA_SECRET_KEY: (optional) Chapa secret if you use Chapa payments
- ADMIN_TOKEN: Strong token for admin dashboard
- ADMIN_USER_ID: Your Telegram user id (integer)
- BASE_WEB_URL: Public URL for the dashboard (e.g. https://<your-railway>.app)
- PUBLIC_BOT_USERNAME: Bot username without @ (for deep links)
- GEMINI_API_KEY, GROQ_API_KEY, ANTHROPIC_API_KEY, ELEVENLABS_API_KEY: optional AI/TTS keys
- ALLOW_DEMO_UPGRADE: set to true for dev quick upgrades

2. Files to include in project

- Railway PostgreSQL plugin (provides `DATABASE_URL`)

3. Local testing commands
   Create and activate virtualenv (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the web dashboard (server):

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

Run the Telegram bot (in another terminal):

```bash
python bot.py
```

Open the admin dashboard at: `http://localhost:8000/admin`

4. Railway notes

- Add environment variables in the Railway project settings (secrets). Set `DATABASE_URL`, `BOT_TOKEN`, `ADMIN_TOKEN`, `ADMIN_USER_ID`, `CHAPA_SECRET_KEY`, `WEBHOOK_SECRET`, `BASE_WEB_URL`, and `PUBLIC_BOT_USERNAME`.
- Railway should run the bot entrypoint as the public web process. The `Procfile` is now:

```
web: python bot.py
```

5. Post-deploy verification

- Visit `/admin`, enter `ADMIN_TOKEN` to view dashboard.
- Check `/api/admin/notes` to ensure notes are listed.
- Submit a Telebirr payment attempt to ensure `payment_attempts` appears in admin payments.
- Use the Auto-Approve button to test heuristic on pending payments.

6. Troubleshooting

- If audio/TTS fails, confirm `ELEVENLABS_API_KEY` or Edge TTS packages are available.
- If AI generation returns "temporarily offline", provider API keys may be missing.
- Check logs (Railway provides service logs) to see stack traces.

7. Security

- Use a strong `ADMIN_TOKEN` and never commit secret keys to git.
- Consider limiting `BASE_WEB_URL` CORS configuration if you add other admin clients.

If you want, I can create a `Procfile`, a minimal `README.md`, and help prepare Railway environment variables now.
