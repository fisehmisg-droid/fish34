"""FastAPI endpoints for payments and the parent dashboard."""

from __future__ import annotations

import logging
import os
import hmac
import time
import hashlib
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, Header, Depends, APIRouter
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Update

import payments
import notes
from config import ADMIN_TOKEN, WEBHOOK_SECRET, BASE_WEB_URL, TIER_PRICES, BOT_TOKEN, validate_env

import db_supabase as db

app = FastAPI(title="Abebe EUEE Bot Web Services")
logger = logging.getLogger(__name__)

# FIX: Defer bot application build to startup so importing server.py never triggers
# Firebase init, scheduler start, or Telegram token validation at import time.
ptb_app = None


def _get_ptb_app():
    global ptb_app
    if ptb_app is None:
        from main import build_app as build_bot_app
        ptb_app = build_bot_app()
    return ptb_app

# ── Redis Rate Limiting (Pass 6.3) ──────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL")
r = None
if REDIS_URL:
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        logger.info("📡 Connected to Redis for rate limiting.")
    except Exception as e:
        logger.warning(f"⚠️ Redis connection failed: {e}. Falling back to in-memory limiting.")
        r = None

_auth_attempts = {} # Fallback in-memory dict

def check_rate_limit(client_ip: str) -> bool:
    """Returns True if allowed, False if blocked."""
    key = f"auth_fail:{client_ip}"
    if r:
        try:
            count = r.get(key)
            if count and int(count) > 100:
                return False
            return True
        except Exception:
            pass
    
    # Fallback to in-memory
    now = time.time()
    attempts, last_reset = _auth_attempts.get(client_ip, [0, now])
    if now - last_reset > 3600:
        attempts = 0
        last_reset = now
        _auth_attempts[client_ip] = [attempts, last_reset]
    
    return attempts <= 100

def increment_rate_limit(client_ip: str):
    key = f"auth_fail:{client_ip}"
    if r:
        try:
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, 3600)
            pipe.execute()
            return
        except Exception:
            pass
    
    # Fallback
    attempts, last_reset = _auth_attempts.get(client_ip, [0, time.time()])
    _auth_attempts[client_ip] = [attempts + 1, last_reset]

# ── Pydantic Models (Pass 4.1) ──────────────────────────────────────────────
class PaymentActionRequest(BaseModel):
    tx_id: str

class AdminLoginRequest(BaseModel):
    token: str

# ── Auth Dependency (Pass 3.1/3.5) ───────────────────────────────────────────
async def admin_auth(request: Request):
    """Verifies session cookie or Bearer token."""
    client_ip = request.client.host
    
    if not check_rate_limit(client_ip):
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        raise HTTPException(status_code=429, detail="Too many authentication attempts.")

    if not ADMIN_TOKEN or ADMIN_TOKEN == "change-me-immediately":
        raise HTTPException(status_code=500, detail="Admin token not configured securely.")
    
    # 1. Try Cookie
    token = request.cookies.get("abebe_admin_session")
    
    # 2. Try Header
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "", 1)
    
    if not token or not hmac.compare_digest(token, ADMIN_TOKEN):
        increment_rate_limit(client_ip)
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return True

# ── Admin Router (Pass 3.2 Default-Deny) ─────────────────────────────────────
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_auth)])

@app.on_event("startup")
async def on_startup():
    validate_env()
    # FIX: [startup DB check] — [fail fast if database is unreachable or credentials are invalid]
    try:
        # Test database connection by getting a user (will fail if DB is down)
        db.init_database()
        test_user = db.get_user(1)  # Non-existent user, just to test connection
        logger.info("Database connection test passed.")
    except Exception as exc:
        logger.exception("Database connection test failed at startup.")
        raise RuntimeError("Database connection test failed. Check Supabase credentials.") from exc

    bot = _get_ptb_app()
    await bot.initialize()
    await bot.start()
    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    if webhook_url:
        logger.info("Setting webhook to %s/telegram/webhook", webhook_url)
        # FIX: Never use hardcoded secrets in production — rely on env var only.
        if not WEBHOOK_SECRET:
            logger.error("WEBHOOK_SECRET not set — cannot register secure webhook.")
        else:
            await bot.bot.set_webhook(url=f"{webhook_url}/telegram/webhook", secret_token=WEBHOOK_SECRET)

    # FIX: Start background scheduler here when running as the Railway web service.
    # main.py's post_init skips scheduler in webhook/Railway mode to avoid duplicates.
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from main import daily_reminder, panic_reminder, weekly_parent_report, reset_weekly_counters
    scheduler = AsyncIOScheduler()
    scheduler.add_job(daily_reminder, "cron", hour=4, minute=0, args=[bot])
    scheduler.add_job(panic_reminder, "cron", hour=9, minute=0, args=[bot], id="panic_noon")
    scheduler.add_job(panic_reminder, "cron", hour=17, minute=0, args=[bot], id="panic_evening")
    scheduler.add_job(weekly_parent_report, "cron", day_of_week="sun", hour=15, minute=0, args=[bot])
    scheduler.add_job(reset_weekly_counters, "cron", day_of_week="mon", hour=21, minute=0, args=[bot])
    scheduler.add_job(db.check_and_expire_subscriptions, "interval", hours=1, args=[bot])
    scheduler.start()
    logger.info("📅 Scheduler started in server.py (Railway mode).")

@app.on_event("shutdown")
async def on_shutdown():
    # FIX: Graceful shutdown on SIGTERM — finish processing updates before exiting.
    bot = _get_ptb_app()
    logger.info("Shutting down PTB application...")
    await bot.stop()
    await bot.shutdown()


# FIX: SIGTERM handler for Railway zero-downtime redeploys.
import signal

def _handle_sigterm(signum, frame):
    logger.info("Received SIGTERM — initiating graceful shutdown...")
    # FastAPI will trigger shutdown events automatically; this just ensures logging.

signal.signal(signal.SIGTERM, _handle_sigterm)

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    # FIX: Strict secret check — reject if no secret configured or mismatch.
    if not WEBHOOK_SECRET:
        logger.error("WEBHOOK_SECRET not configured — rejecting all webhook requests.")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    if not hmac.compare_digest(secret or "", WEBHOOK_SECRET):
        logger.warning("Invalid webhook secret received")
        raise HTTPException(status_code=401, detail="Invalid secret token")

    bot = _get_ptb_app()
    payload = await request.json()
    update = Update.de_json(data=payload, bot=bot.bot)
    await bot.update_queue.put(update)
    return {"ok": True}

@app.get("/")
async def root_health():
    return {"status": "ok", "service": "Abebe EUEE Bot", "version": "2.0"}


@app.get("/health")
async def health_check():
    """FIX: Explicit /health endpoint for Railway healthchecks. Must return HTTP 200."""
    return {"status": "ok", "service": "Abebe EUEE Bot", "version": "2.0"}

_allowed_origins = [BASE_WEB_URL] if (BASE_WEB_URL and "your-url" not in BASE_WEB_URL) else ["http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins, 
    allow_credentials=True, # Enabled for cookies
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https://cdn.pixabay.com https://images.unsplash.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if request.url.path.startswith("/api/admin") or request.url.path.startswith("/parent/"):
        response.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        response.headers.setdefault("Pragma", "no-cache")
    return response

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ── Admin Login (Pass 3.5/6.2) ───────────────────────────────────────────────
@app.post("/api/admin/login")
async def admin_login(req: AdminLoginRequest, request: Request):
    client_ip = request.client.host
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many attempts")

    if hmac.compare_digest(req.token, ADMIN_TOKEN):
        response = JSONResponse(content={"status": "success"})
        response.set_cookie(
            key="abebe_admin_session",
            value=req.token,
            httponly=True,
            secure=True, 
            samesite="strict",
            max_age=86400 * 7
        )
        return response
    
    increment_rate_limit(client_ip)
    raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/api/admin/logout")
async def admin_logout():
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie("abebe_admin_session")
    return response

# ── Admin API Endpoints (Now using Router) ───────────────────────────────────

@admin_router.get("/overview")
async def admin_overview():
    # Get user statistics from Supabase
    total, free, pro, max_tier = 0, 0, 0, 0
    recent_users = []
    
    # Stream all users using the Supabase-compatible API
    for doc in db.db.collection("users").limit(500).stream():
        total += 1
        d = doc.to_dict()
        t = str(d.get("tier", "free")).lower()
        if t == "free":
            free += 1
        elif t.startswith("pro"):
            pro += 1
        elif t.startswith("max"):
            max_tier += 1

        if len(recent_users) < 50:
            recent_users.append({
                "telegram_id": d.get("telegram_id"),
                "name": d.get("name", "Unknown"),
                "tier": d.get("tier", "free"),
                "joined": str(d.get("joined", ""))
            })
        await asyncio.sleep(0)

    recent_users.sort(key=lambda x: x.get("joined", ""), reverse=True)
    pending_payments = db.get_pending_payments()
    suggestions = db.get_feature_suggestions()

    return {
        "stats": {
            "total_users": total,
            "free_users": free,
            "pro_users": pro,
            "max_users": max_tier,
            "pending_payments": len(pending_payments),
            "earnings_etb": (pro * TIER_PRICES.get("pro_monthly", 100)) + (max_tier * TIER_PRICES.get("max_monthly", 200))
        },
        "users": recent_users,
        "payments": pending_payments,
        "suggestions": suggestions
    }

@admin_router.post("/payments/approve")
async def admin_approve_payment(req: PaymentActionRequest):
    if db.approve_payment(req.tx_id):
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Failed to approve")

@admin_router.post("/payments/reject")
async def admin_reject_payment(req: PaymentActionRequest):
    if db.reject_payment(req.tx_id):
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Failed to reject")

@admin_router.post("/payments/auto_approve")
async def admin_auto_approve():
    pending = db.get_pending_payments()
    approved, skipped = [], []
    for p in pending:
        tx = p.get("tx_id") or p.get("transaction_id")
        if tx and payments.validate_telebirr_tx_id(tx) and p.get("screenshot_url"):
            if db.approve_payment(tx):
                approved.append(tx)
                continue
        skipped.append(tx)
    return {"approved": approved, "skipped": skipped}

@admin_router.get("/notes")
async def admin_notes():
    from config import SUBJECTS
    results = []
    for subject in SUBJECTS.keys():
        files = notes.get_generated_notes_files(subject)
        results.append({
            "subject": subject,
            "has_pdf": bool(files.get("pdf")),
            "has_md": bool(files.get("md")),
            "has_flashcards": bool(files.get("flashcards"))
        })
    return results

@admin_router.post("/notes/{subject}/regenerate")
async def admin_regenerate_notes(subject: str):
    await asyncio.to_thread(notes.ensure_subject_notes_generated, subject, True)
    return {"status": "success"}

app.include_router(admin_router)

# ── Public / Student Endpoints ──────────────────────────────────────────────

@app.get("/api/textbooks/download/{filename}")
async def download_textbook(filename: str, user_id: int, sig: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    from helpers import verify_download_signature
    if not verify_download_signature(user_id, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    user = db.get_user(user_id)
    if not user or user.get("tier") == "free":
        raise HTTPException(status_code=403, detail="Unauthorized")

    file_path = os.path.join(os.path.dirname(__file__), "textbooks", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Not found")
        
    return FileResponse(file_path, filename=filename)

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_view():
    admin_path = os.path.join(TEMPLATES_DIR, "admin_dashboard.html")
    return FileResponse(admin_path, media_type="text/html")

@app.get("/parent/{token}", response_class=HTMLResponse)
async def parent_dashboard(request: Request, token: str):
    user = db.get_user_by_parent_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Not found")

    # Get parent reports using Supabase-compatible API
    reports = []
    for doc in db.db.collection("parent_reports").where("parent_token", "==", token).stream():
        reports.append(doc.to_dict())
    reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    report_text = reports[0].get("report") if reports else "No report yet."

    context = {
        "request": request,
        "name": user.get("name", "Student"),
        "streak": user.get("streak", 0),
        "questions_total": user.get("questions_total", 0),
        "tier": user.get("tier", "free"),
        "report": report_text,
    }
    return templates.TemplateResponse("dashboard.html", context)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
