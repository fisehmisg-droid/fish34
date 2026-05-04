Abebe EUEE Bot — Local dev & deployment

Quick start (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
# In another terminal run the web dashboard:
uvicorn server:app --reload
```

Deployment notes:

- Use `Procfile` to run both the web dashboard and the bot (Railway).
- Add required secrets listed in `DEPLOYMENT_CHECKLIST.md` to your Railway project.

Admin dashboard:

- Visit `/admin` and provide `ADMIN_TOKEN` when prompted.
- Use the 'Auto-Approve' button to let the server auto-approve believable Telebirr payments.

If you want, I can prepare a minimal GitHub Actions workflow or help push to Railway directly.
