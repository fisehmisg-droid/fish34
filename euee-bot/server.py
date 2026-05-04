"""FastAPI endpoints for payments and the parent dashboard."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Request, Header, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import hmac
import time
import hashlib
import secrets
import payments
import asyncio
import notes
from fastapi.middleware.cors import CORSMiddleware
from config import ADMIN_TOKEN, WEBHOOK_SECRET, BASE_WEB_URL, TIER_PRICES

if os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes"):
    import db_stub as db
else:
    import db

app = FastAPI(title="Abebe EUEE Bot Web Services")
logger = logging.getLogger(__name__)


# ── Health Check for Railway ─────────────────────────────────────────────────
@app.get("/")
async def health_check():
    return {"status": "ok", "service": "Abebe EUEE Bot", "version": "1.0"}

# ── CORS Configuration (Section 7.1 Hardening) ──────────────────────────────
# Restrict access to the bot's own production domain. 
# Defaults to localhost for development if BASE_WEB_URL is not set.
_allowed_origins = [BASE_WEB_URL] if (BASE_WEB_URL and "your-url" not in BASE_WEB_URL) else ["http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins, 
    allow_credentials=False,
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
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if request.url.path.startswith("/admin") or request.url.path.startswith("/parent/"):
        response.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        response.headers.setdefault("Pragma", "no-cache")
    return response

# ── Admin Auth Rate Limiting (Pass 6.2) ──────────────────────────────────────
_auth_attempts = {} # {ip: [count, last_reset]}

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

_DEFAULT_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Abebe EUEE Parent Dashboard</title>
  <style>
    body { font-family: Georgia, 'Times New Roman', serif; background: #f7f4ee; color: #222; margin: 0; padding: 24px; }
    .wrap { max-width: 860px; margin: 0 auto; background: #fffdf8; border: 1px solid #eadfc8; border-radius: 16px; padding: 32px; box-shadow: 0 10px 30px rgba(0,0,0,0.06); }
    h1, h2 { color: #23423b; }
    .stats { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin: 24px 0; }
    .card { background: #f1efe7; border-radius: 12px; padding: 16px; }
    .report { white-space: pre-wrap; line-height: 1.6; background: #fff9ea; border: 1px solid #f0df9c; border-radius: 12px; padding: 20px; }
    .tier { display: inline-block; padding: 4px 10px; border-radius: 999px; background: #23423b; color: #fff; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Student Progress: {{ name }}</h1>
    <div class="stats">
      <div class="card"><strong>Streak</strong><br>{{ streak }} day(s)</div>
      <div class="card"><strong>Total Questions</strong><br>{{ questions_total }}</div>
      <div class="card"><strong>Tier</strong><br><span class="tier">{{ tier.upper() }}</span></div>
    </div>
    <h2>Weekly Parent Report</h2>
    <div class="report">{{ report }}</div>
  </div>
</body>
</html>
"""

dashboard_template_path = os.path.join(TEMPLATES_DIR, "dashboard.html")
if not os.path.exists(dashboard_template_path):
    with open(dashboard_template_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(_DEFAULT_DASHBOARD_HTML)


async def admin_auth(request: Request, authorization: str = Header(None)):
    """Verifies the Bearer token with fail-only rate limiting (Pass 6.2 Hardening)."""
    client_ip = request.client.host
    now = time.time()
    
    # 1. Check existing block (100 failures/hour)
    attempts, last_reset = _auth_attempts.get(client_ip, [0, now])
    if now - last_reset > 3600:
        attempts = 0
        last_reset = now
    
    if attempts > 100:
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        raise HTTPException(status_code=429, detail="Too many authentication attempts.")

    # 2. Basic Configuration Check
    if not ADMIN_TOKEN or ADMIN_TOKEN == "change-me-immediately":
        raise HTTPException(status_code=500, detail="Admin token not configured securely.")
    
    # 3. Validate Header Presence
    if not authorization or not authorization.startswith("Bearer "):
        _auth_attempts[client_ip] = [attempts + 1, last_reset]
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    # 4. Secure Token Comparison
    token = authorization.replace("Bearer ", "", 1)
    if not hmac.compare_digest(token, ADMIN_TOKEN):
        _auth_attempts[client_ip] = [attempts + 1, last_reset]
        logger.warning(f"Invalid admin token attempt from IP: {client_ip}")
        raise HTTPException(status_code=403, detail="Invalid admin token")
    
    # Success: Do NOT increment attempts counter. We want to block brute-forcers, not valid users.
    return True


def verify_chapa_signature(body: bytes, signature: str) -> bool:
    """Verifies that the webhook payload came from Chapa using HMAC-SHA256."""
    if not WEBHOOK_SECRET:
        return False
    computed_hash = hmac.new(
        key=WEBHOOK_SECRET.encode('utf-8'),
        msg=body,
        digestmod=hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed_hash, signature)


@app.get("/api/textbooks/download/{filename}")
async def download_textbook(filename: str, user_id: int, sig: str):
    """
    Secure textbook download with identity verification (Pass 4.2 Hardening).
    Ensures that only authorized users with a signed link can download materials.
    """
    # 1. Path Traversal Protection (Section 8.3)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # 2. Cryptographic Identity Verification (Pass 3.3/4.2 IDOR Fix)
    from helpers import verify_download_signature
    if not verify_download_signature(user_id, sig):
        logger.warning(f"IDOR attempt blocked: user_id={user_id} filename={filename}")
        raise HTTPException(status_code=403, detail="Invalid download signature. Please get a fresh link from the bot.")

    # 3. Authorization Check (Pass 4.2 Fix)
    user = db.get_user(user_id)
    if not user:
        logger.warning(f"Unauthorized textbook download attempt: user_id={user_id}")
        raise HTTPException(status_code=403, detail="Unauthorized: Student record not found.")

    # 4. Tier Check (Business Logic Security - Section 4.2)
    if user.get("tier") == "free":
        logger.warning(f"Free user attempted textbook download: user_id={user_id}")
        raise HTTPException(status_code=403, detail="Upgrade to Pro or Max to download textbooks.")

    textbooks_dir = os.path.join(os.path.dirname(__file__), "textbooks")
    file_path = os.path.join(textbooks_dir, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    logger.info(f"✅ TEXTBOOK_DOWNLOAD: file={filename} user={user.get('name')} id={user_id}")
    return FileResponse(file_path, filename=filename)


@app.api_route("/chapa/callback", methods=["POST"])
async def chapa_callback(request: Request):
    """Manual-review mode: keep webhook disabled so no automatic approval happens."""
    logger.info("Chapa callback received but manual-review mode is enabled; ignoring payload.")
    raise HTTPException(status_code=501, detail="Automatic payment processing is disabled. Use manual admin review.")


@app.get("/api/admin/stats")
async def admin_stats(_: bool = Depends(admin_auth)):
    users_ref = db.db.collection("users").stream()
    total = 0
    free = 0
    pro = 0
    max_tier = 0
    for doc in users_ref:
        total += 1
        d = doc.to_dict()
        t = str(d.get("tier", "free")).lower()
        if t == "free":
            free += 1
        elif t.startswith("pro"):
            pro += 1
        elif t.startswith("max"):
            max_tier += 1
    
    pending = db.get_pending_payments()
    
    return {
        "total_users": total,
        "active_users": total,
        "free_users": free,
        "pro_users": pro,
        "max_users": max_tier,
        "pending_payments": len(pending),
        "expired_subs": 0,
        "earnings_etb": (pro * TIER_PRICES.get("pro_monthly", 100)) + (max_tier * TIER_PRICES.get("max_monthly", 200))
    }

@app.get("/api/admin/users")
async def admin_users(_: bool = Depends(admin_auth)):
    users_ref = db.db.collection("users").limit(50).stream()
    results = []
    for doc in users_ref:
        d = doc.to_dict()
        results.append({
            "telegram_id": d.get("telegram_id"),
            "name": d.get("name", "Unknown"),
            "tier": d.get("tier", "free"),
            "joined": str(d.get("joined", ""))
        })
    results.sort(key=lambda x: x.get("joined", ""), reverse=True)
    return results

@app.get("/api/admin/payments")
async def admin_pending(_: bool = Depends(admin_auth)):
    return db.get_pending_payments()

@app.post("/api/admin/payments/{tx_id}/approve")
async def admin_approve_payment(tx_id: str, _: bool = Depends(admin_auth)):
    success = db.approve_payment(tx_id)
    if success:
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Failed to approve payment")

@app.post("/api/admin/payments/{tx_id}/reject")
async def admin_reject_payment(tx_id: str, _: bool = Depends(admin_auth)):
    success = db.reject_payment(tx_id)
    if success:
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Failed to reject payment")


@app.post("/api/admin/payments/auto_approve")
async def admin_auto_approve(_: bool = Depends(admin_auth)):
    """Auto-approve believable pending Telebirr payments using simple heuristics.

    Heuristic: valid-looking transaction ID format + a submitted screenshot URL.
    This runs synchronously and returns lists of approved/skipped tx ids.
    """
    pending = db.get_pending_payments()
    approved = []
    skipped = []
    for p in pending:
        tx = p.get("transaction_id") or p.get("transaction") or p.get("tx_id")
        if not tx:
            skipped.append(None)
            continue
        # Basic format validation using existing helper
        if not payments.validate_telebirr_tx_id(tx):
            skipped.append(tx)
            continue
        # Require a screenshot to consider auto-approval
        if not p.get("screenshot_url"):
            skipped.append(tx)
            continue
        # Attempt approval
        try:
            if db.approve_payment(tx):
                approved.append(tx)
            else:
                skipped.append(tx)
        except Exception:
            skipped.append(tx)

    return {"approved": approved, "skipped": skipped}


@app.get("/api/admin/notes")
async def admin_notes(_: bool = Depends(admin_auth)):
    """List generated notes status for each subject."""
    from config import SUBJECTS

    results = []
    for subject in SUBJECTS.keys():
        files = notes.get_generated_notes_files(subject)
        info = {
            "subject": subject,
            "has_pdf": bool(files.get("pdf")),
            "pdf": str(files.get("pdf")) if files.get("pdf") else None,
            "has_md": bool(files.get("md")),
            "md": str(files.get("md")) if files.get("md") else None,
            "has_flashcards": bool(files.get("flashcards")),
            "flashcards": str(files.get("flashcards")) if files.get("flashcards") else None,
            "folder": str(files.get("folder")) if files.get("folder") else None,
        }
        results.append(info)
    return results


@app.post("/api/admin/notes/{subject}/regenerate")
async def admin_regenerate_notes(subject: str, _: bool = Depends(admin_auth)):
    """Force regenerate notes for a subject (runs in threadpool)."""
    await asyncio.to_thread(notes.ensure_subject_notes_generated, subject, True)
    return {"status": "success"}

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_view():
    # Note: The dashboard HTML itself will handle auth via JS prompting for the token
    admin_path = os.path.join(TEMPLATES_DIR, "admin_dashboard.html")
    return FileResponse(admin_path, media_type="text/html")

@app.get("/api/admin/overview")
async def admin_overview(_: bool = Depends(admin_auth)):
    """Combined endpoint to reduce request volume and prevent 429 errors."""
    # 1. Get Stats
    users_ref = db.db.collection("users").stream()
    total = 0
    free = 0
    pro = 0
    max_tier = 0
    recent_users = []
    
    for doc in users_ref:
        total += 1
        d = doc.to_dict()
        t = str(d.get("tier", "free")).lower()
        if t == "free":
            free += 1
        elif t.startswith("pro"):
            pro += 1
        elif t.startswith("max"):
            max_tier += 1
        
        # Collect for users list (limit to 50 for performance)
        if len(recent_users) < 50:
            recent_users.append({
                "telegram_id": d.get("telegram_id"),
                "name": d.get("name", "Unknown"),
                "tier": d.get("tier", "free"),
                "joined": str(d.get("joined", ""))
            })
    
    recent_users.sort(key=lambda x: x.get("joined", ""), reverse=True)
    
    # 2. Get Payments
    pending_payments = db.get_pending_payments()
    
    # 3. Get Suggestions
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

@app.get("/api/admin/suggestions")
async def get_admin_suggestions(_: bool = Depends(admin_auth)):
    return db.get_feature_suggestions()

@app.get("/parent/{token}", response_class=HTMLResponse)
async def parent_dashboard(request: Request, token: str):
    user = db.get_user_by_parent_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Student not found or invalid link")

    reports_ref = (
        db.db.collection("parent_reports")
        .where("parent_token", "==", token)
        .stream()
    )
    all_reports = [r.to_dict() for r in reports_ref]
    all_reports.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    report_doc = all_reports[0] if all_reports else None
    report_text = (
        report_doc.get("report", "No report available yet.")
        if report_doc
        else "Abebe is still observing your child's progress. Check back after the next weekly report."
    )

    context = {
        "request": request,
        "name": user.get("name", "Student"),
        "streak": user.get("streak", 0),
        "questions_total": user.get("questions_total", 0),
        "tier": user.get("tier", "free"),
        "report": report_text,
    }
    # Use the newer Starlette API signature
    try:
        return templates.TemplateResponse(request, "dashboard.html", context)
    except TypeError:
        return templates.TemplateResponse("dashboard.html", context)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
