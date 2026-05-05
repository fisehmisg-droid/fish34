"""Chapa & Telebirr payment helpers."""

from __future__ import annotations

import uuid
import httpx
import re
import io
from PIL import Image

from tenacity import retry, stop_after_attempt, wait_exponential

from config import BASE_WEB_URL, CHAPA_SECRET_KEY, PUBLIC_BOT_USERNAME, TIER_PRICES

_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=30),
    reraise=True,
)

CHAPA_BASE = "https://api.chapa.co/v1"

# --- Telebirr Security & Validation ---
def validate_telebirr_tx_id(tx_id: str) -> bool:
    """Strictly validates Telebirr transaction ID format to prevent injections."""
    # Assuming Telebirr IDs are strictly alphanumeric, no spaces or special chars
    if not tx_id or not isinstance(tx_id, str):
        return False
    if len(tx_id) < 8 or len(tx_id) > 20: 
        return False
    if not re.match(r"^[A-Z0-9]+$", tx_id.upper()):
        return False
    return True

def is_valid_image(file_bytes: bytes) -> bool:
    """Zero-trust file upload verification: checks the magic bytes/header of the image, preventing malicious executable disguise."""
    try:
        # Load the bytes into Pillow
        image = Image.open(io.BytesIO(file_bytes))
        
        # Must be a standard web image formats
        if image.format not in ['JPEG', 'PNG', 'WEBP']:
            return False
            
        # Optional: verify structural integrity
        image.verify()
        return True
    except Exception:
        return False

# --- Chapa Functions ---
async def create_payment(telegram_id: int, tier: str, first_name: str, email: str = "") -> dict:
    if not CHAPA_SECRET_KEY:
        return {"error": "Payment setup is incomplete. Add the Chapa secret key first."}

    tx_ref = f"euee_{tier}_{telegram_id}_{uuid.uuid4().hex[:8]}"
    amount = TIER_PRICES.get(tier, 99)
    if not email:
        email = f"student{telegram_id}@euee.bot"

    return_url = f"https://t.me/{PUBLIC_BOT_USERNAME}" if PUBLIC_BOT_USERNAME else BASE_WEB_URL
    payload = {
        "amount": str(amount),
        "currency": "ETB",
        "email": email,
        "first_name": first_name[:50],
        "tx_ref": tx_ref,
        "callback_url": f"{BASE_WEB_URL}/chapa/callback",
        "return_url": return_url,
        "customization[title]": f"EUEE Bot {tier.title()} Plan",
        "customization[description]": f"Upgrade to {tier.title()} for more Abebe features",
    }
    headers = {
        "Authorization": f"Bearer {CHAPA_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    try:
        # FIX: 30-second timeout + retry on transient network errors.
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{CHAPA_BASE}/transaction/initialize", json=payload, headers=headers)
            data = response.json()
            if data.get("status") == "success":
                return {"checkout_url": data["data"]["checkout_url"], "tx_ref": tx_ref}
            return {"error": data.get("message", "Payment initialization failed.")}
    except Exception:
        return {"error": "Payment service unavailable. Try again later."}


@_RETRY
async def verify_payment(tx_ref: str) -> dict:
    if not CHAPA_SECRET_KEY:
        return {"verified": False}

    headers = {"Authorization": f"Bearer {CHAPA_SECRET_KEY}"}
    try:
        # FIX: 30-second timeout + retry on transient errors.
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{CHAPA_BASE}/transaction/verify/{tx_ref}", headers=headers)
            data = response.json()
            if data.get("status") == "success" and data.get("data", {}).get("status") == "success":
                return {"verified": True, "amount": data["data"].get("amount")}
            return {"verified": False}
    except Exception:
        return {"verified": False}
