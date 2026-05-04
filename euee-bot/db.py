"""
db.py — All Firebase Firestore database operations
"""
import hashlib
import json
from datetime import date, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
import logging
import os
from config import FIREBASE_KEY, STREAK_FREEZE_EVERY

logger = logging.getLogger(__name__)

# ── Init ──────────────────────────────────────────────────────────────────────
if not firebase_admin._apps:
    firebase_credentials = os.getenv("FIREBASE_CREDENTIALS", "").strip()
    if firebase_credentials:
        cred = credentials.Certificate(json.loads(firebase_credentials))
    else:
        cred = credentials.Certificate(FIREBASE_KEY)
    firebase_admin.initialize_app(cred)

db = firestore.client()


# ── Helpers ───────────────────────────────────────────────────────────────────
def to_serializable(data):
    """Recursively convert Firestore objects (datetimes, etc) to JSON-serializable types."""
    if isinstance(data, list):
        return [to_serializable(item) for item in data]
    if isinstance(data, dict):
        return {k: to_serializable(v) for k, v in data.items()}
    if hasattr(data, "isoformat"):
        return data.isoformat()
    return data


def _today() -> str:
    return date.today().isoformat()


def _now():
    return firestore.SERVER_TIMESTAMP


# ── User operations ───────────────────────────────────────────────────────────
def get_user(telegram_id: int) -> dict | None:
    doc = db.collection("users").document(str(telegram_id)).get()
    return doc.to_dict() if doc.exists else None


def create_user(telegram_id: int, name: str | None, language: str) -> dict:
    import secrets
    parent_token = secrets.token_urlsafe(16)
    safe_name = (name or "Student")[:100]
    data = {
        "telegram_id": telegram_id,
        "name": safe_name,
        "language": language,
        "tier": "free",
        "streak": 0,
        "streak_freezes": 0,
        "last_active_date": _today(),
        "questions_today": 0,
        "questions_total": 0,
        "study_minutes_today": 0,
        "study_minutes_total": 0,
        "score_by_subject": {},
        "correct_total": 0,
        "wrong_total": 0,
        "exams_taken": 0,
        "badges": [],
        "parent_token": parent_token,
        "joined": _now(),
        "last_question_date": _today(),
        "last_explanation": "",
        "chosen_subject": "math",
        "questions_this_week": 0,
        "week_start": _today(),
    }
    db.collection("users").document(str(telegram_id)).set(data)
    return data


def update_user(telegram_id: int, updates: dict):
    db.collection("users").document(str(telegram_id)).update(updates)


def upgrade_user_tier(telegram_id: int, tier: str):
    db.collection("users").document(str(telegram_id)).update({"tier": tier})


def get_or_create_user(telegram_id: int, name: str, language: str = "en") -> dict:
    user = get_user(telegram_id)
    if user is None:
        user = create_user(telegram_id, name, language)
    return user


# ── Rate limiting ─────────────────────────────────────────────────────────────
def check_and_increment_questions(telegram_id: int, tier: str, limit: int) -> bool:
    """Returns True if allowed, False if rate-limited. Resets daily counter."""
    ref = db.collection("users").document(str(telegram_id))
    user = ref.get().to_dict()
    today = _today()

    # Reset counter if it's a new day
    if user.get("last_question_date") != today:
        ref.update({
            "questions_today": 0,
            "last_question_date": today,
            "study_minutes_today": 0,
        })
        user["questions_today"] = 0

    if tier == "free" and user.get("questions_today", 0) >= limit:
        return False

    ref.update({
        "questions_today": firestore.Increment(1),
        "questions_total": firestore.Increment(1),
        "questions_this_week": firestore.Increment(1),
    })
    return True


# ── Streak management ─────────────────────────────────────────────────────────
def update_streak(telegram_id: int) -> dict:
    """Update streak, award streak freezes, return updated streak info."""
    ref = db.collection("users").document(str(telegram_id))
    user = ref.get().to_dict()
    today = _today()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    last_active = user.get("last_active_date", "")
    current_streak = user.get("streak", 0)
    freezes = user.get("streak_freezes", 0)

    if last_active == today:
        return {"streak": current_streak, "freeze_earned": False}

    if last_active == yesterday or last_active == "":
        new_streak = current_streak + 1
    else:
        # Missed a day — check for freeze
        if freezes > 0:
            new_streak = current_streak  # protected!
            ref.update({"streak_freezes": firestore.Increment(-1), "last_active_date": today})
            return {"streak": new_streak, "freeze_used": True, "freeze_earned": False}
        else:
            new_streak = 1  # reset

    # Award freeze every STREAK_FREEZE_EVERY days
    freeze_earned = (new_streak % STREAK_FREEZE_EVERY == 0 and new_streak > 0)
    updates = {
        "streak": new_streak,
        "last_active_date": today,
    }
    if freeze_earned:
        updates["streak_freezes"] = firestore.Increment(1)

    ref.update(updates)
    return {"streak": new_streak, "freeze_earned": freeze_earned}


# ── Subject performance ───────────────────────────────────────────────────────
def record_answer(telegram_id: int, subject: str, correct: bool, topic: str = "General", question_data: dict | None = None):
    ref = db.collection("users").document(str(telegram_id))
    field = f"score_by_subject.{subject}"
    
    # Sanitize topic name for Firestore field paths (dots interpret as nesting)
    safe_topic = topic.replace(".", "-")
    
    # Track overall subject and detailed topic performance
    updates = {
        field: firestore.Increment(1 if correct else 0),
        f"subject_correct.{subject}": firestore.Increment(1 if correct else 0),
        f"subject_wrong.{subject}": firestore.Increment(0 if correct else 1),
        f"subject_attempts.{subject}": firestore.Increment(1),
        f"topic_performance.{subject}.{safe_topic}.correct": firestore.Increment(1 if correct else 0),
        f"topic_performance.{subject}.{safe_topic}.attempts": firestore.Increment(1),
        "correct_total" if correct else "wrong_total": firestore.Increment(1),
        "study_minutes_today": firestore.Increment(2),
        "study_minutes_total": firestore.Increment(2),
    }
    ref.update(updates)

    # Save detailed wrong question for personalized review
    if not correct and question_data:
        try:
            db.collection("users").document(str(telegram_id)).collection("wrong_questions").add({
                "subject": subject,
                "topic": topic,
                "question": question_data.get("question", ""),
                "options": question_data.get("options", {}),
                "answer": question_data.get("answer", ""),
                "explanation": question_data.get("explanation", ""),
                "timestamp": _now()
            })
        except Exception as e:
            logger.error(f"Failed to save wrong question: {e}")


# ── Leaderboard ───────────────────────────────────────────────────────────────
def get_leaderboard(limit: int = 10) -> list[dict]:
    docs = (
        db.collection("users")
        .order_by("correct_total", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    return [d.to_dict() for d in docs]


# ── Textbook chunks ───────────────────────────────────────────────────────────
def get_chunks_for_subject(subject: str, limit: int = 5) -> list[str]:
    docs = (
        db.collection("textbook_chunks")
        .where("subject", "==", subject)
        .limit(limit)
        .stream()
    )
    return [d.to_dict().get("text", "") for d in docs]


# ── Exam operations ───────────────────────────────────────────────────────────
def save_exam_result(telegram_id: int, subject: str, score: int, total: int, weak_topics: list):
    db.collection("exam_results").add({
        "telegram_id": telegram_id,
        "subject": subject,
        "score": score,
        "total": total,
        "percentage": round(score / total * 100, 1),
        "weak_topics": weak_topics,
        "taken_at": _now(),
    })
    db.collection("users").document(str(telegram_id)).update({
        "exams_taken": firestore.Increment(1),
    })


def get_exam_results(telegram_id: int, limit: int = 5) -> list[dict]:
    docs = (
        db.collection("exam_results")
        .where("telegram_id", "==", telegram_id)
        .order_by("taken_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    return [d.to_dict() for d in docs]


# ── Confession box ────────────────────────────────────────────────────────────
def save_confession(telegram_id: int, topic: str):
    db.collection("confessions").add({
        "telegram_id": telegram_id,
        "topic": topic[:500],
        "created_at": _now(),
    })


# ── Battle mode ───────────────────────────────────────────────────────────────
def create_battle(challenger_id: int, subject: str, question_data: dict) -> str:
    doc_ref = db.collection("battles").document()
    doc_ref.set({
        "battle_id": doc_ref.id,
        "challenger_id": challenger_id,
        "opponent_id": None,
        "subject": subject,
        "question": question_data.get("question", ""),
        "options": question_data.get("options", {}),
        "correct_answer": question_data.get("answer", ""),
        "explanation": question_data.get("explanation", ""),
        "status": "waiting",  # waiting, active, done
        "challenger_answer": None,
        "opponent_answer": None,
        "challenger_correct": None,
        "opponent_correct": None,
        "challenger_time": None,
        "opponent_time": None,
        "winner_id": None,
        "created_at": _now(),
    })
    return doc_ref.id


def get_battle(battle_id: str) -> dict | None:
    doc = db.collection("battles").document(battle_id).get()
    return doc.to_dict() if doc.exists else None


def join_battle(battle_id: str, opponent_id: int) -> dict | None:
    ref = db.collection("battles").document(battle_id)
    battle = ref.get().to_dict()
    if not battle or battle.get("status") not in {"waiting", "active"}:
        return None
    if battle.get("challenger_id") == opponent_id:
        return battle
    if battle.get("opponent_id") and battle.get("opponent_id") != opponent_id:
        return None
    ref.update({"opponent_id": opponent_id, "status": "active"})
    return ref.get().to_dict()


def submit_battle_answer(
    battle_id: str,
    user_id: int,
    answer: str,
    time_secs: float,
    is_correct: bool,
) -> dict:
    ref = db.collection("battles").document(battle_id)
    battle = ref.get().to_dict()
    if not battle:
        return {}
    if battle.get("challenger_id") == user_id:
        ref.update({
            "challenger_answer": answer,
            "challenger_time": time_secs,
            "challenger_correct": is_correct,
            "status": "active",
        })
    else:
        ref.update({
            "opponent_answer": answer,
            "opponent_time": time_secs,
            "opponent_correct": is_correct,
            "status": "active",
        })
    return ref.get().to_dict()


def finalize_battle(
    battle_id: str,
    winner_id: int | None,
    challenger_correct: bool,
    opponent_correct: bool,
):
    db.collection("battles").document(battle_id).update({
        "winner_id": winner_id,
        "challenger_correct": challenger_correct,
        "opponent_correct": opponent_correct,
        "status": "done",
        "finished_at": _now(),
    })


# ── Boss fight ────────────────────────────────────────────────────────────────
def get_boss_fight_week() -> dict | None:
    from datetime import date
    week = date.today().isocalendar()[1]
    year = date.today().year
    doc = db.collection("boss_fights").document(f"{year}_{week}").get()
    return doc.to_dict() if doc.exists else None


def save_boss_fight(question: str, subject: str, model_answer: str | None = None, explanation: str | None = None):
    from datetime import date
    week = date.today().isocalendar()[1]
    year = date.today().year
    data = {
        "question": question,
        "subject": subject,
        "week": week,
        "year": year,
        "completers": [],
        "created_at": _now(),
    }
    if model_answer:
        data["model_answer"] = model_answer
    if explanation:
        data["explanation"] = explanation

    db.collection("boss_fights").document(f"{year}_{week}").set(data)
    


def complete_boss_fight(telegram_id: int):
    from datetime import date
    week = date.today().isocalendar()[1]
    year = date.today().year
    ref = db.collection("boss_fights").document(f"{year}_{week}")
    ref.update({"completers": firestore.ArrayUnion([telegram_id])})
    # Award Champion badge
    db.collection("users").document(str(telegram_id)).update({
        "badges": firestore.ArrayUnion(["🏆 Champion"])
    })


# ── Parent dashboard ──────────────────────────────────────────────────────────
def get_user_by_parent_token(token: str) -> dict | None:
    docs = db.collection("users").where("parent_token", "==", token).limit(1).stream()
    for doc in docs:
        return doc.to_dict()
    return None


# ── Top scorer this week (Voice of the Topper) ───────────────────────────────
def get_top_scorer_this_week() -> dict | None:
    docs = (
        db.collection("users")
        .order_by("questions_this_week", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    for doc in docs:
        return doc.to_dict()
    return None


# ── Weak point radar (last 10 answers) ───────────────────────────────────────
def get_weak_subjects(telegram_id: int) -> dict:
    user = get_user(telegram_id)
    if not user:
        return {}
    attempts = user.get("subject_attempts", {})
    correct = user.get("subject_correct", {})
    result = {}
    for subj, total in attempts.items():
        c = correct.get(subj, 0)
        pct = round(c / total * 100) if total > 0 else 0
        result[subj] = pct
    return result


# ── Daily tip storage ─────────────────────────────────────────────────────────
def save_daily_tip(tip: str):
    today = _today()
    db.collection("daily_tips").document(today).set({"tip": tip, "date": today})


def get_daily_tip() -> str | None:
    today = _today()
    doc = db.collection("daily_tips").document(today).get()
    return doc.to_dict().get("tip") if doc.exists else None


# ── Panic mode (exam countdown) ───────────────────────────────────────────────
def get_panic_kit_questions() -> list[str]:
    docs = db.collection("panic_kit").order_by("rank").limit(50).stream()
    return [d.to_dict().get("question", "") for d in docs]


def is_panic_mode() -> bool:
    from datetime import date
    from config import EUEE_EXAM_DATE
    delta = (EUEE_EXAM_DATE - date.today()).days
    return 0 <= delta <= 7


# ── Global Cache (For scaling to hundreds of users) ───────────────────────────
def get_cached_content(cache_key: str) -> dict | None:
    """Retrieve heavy AI generated content from cache."""
    doc = db.collection("content_cache").document(cache_key).get()
    return doc.to_dict() if doc.exists else None

def set_cached_content(cache_key: str, data: dict):
    """Save heavy AI generated content to cache."""
    db.collection("content_cache").document(cache_key).set(data)


def clear_subject_notes_cache(subject: str) -> None:
    """Drop cached markdown/audio-script blobs after notes are regenerated on disk."""
    for lang_code in ("en", "am"):
        for key in (
            f"notes_{subject}_{lang_code}",
            f"audio_script_{subject}_{lang_code}",
        ):
            db.collection("content_cache").document(key).delete()

# ── Manual Telebirr Payment Handling & Rate Limiting ──
def user_telebirr_rate_limit_exceeded(telegram_id: int) -> bool:
    """Check if the user is spamming payment attempts in the last hour."""
    # Fetch all attempts for user and sort in Python to avoid index requirement
    ref = db.collection("payment_attempts").where("telegram_id", "==", telegram_id).stream()
    attempts = [doc.to_dict() for doc in ref]
    attempts.sort(key=lambda x: x.get("submitted_at", 0), reverse=True)
    attempts = attempts[:5]
    
    if len(attempts) >= 5:
        # Check if the 5th most recent was within 1 hour
        last_attempt = attempts[-1]
        if hasattr(last_attempt.get("submitted_at"), "timestamp"):
            import datetime
            hour_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
            if last_attempt["submitted_at"] > hour_ago:
                return True
    return False

def check_transaction_exists(tx_id: str) -> bool:
    """Ensure duplicate transaction IDs are completely rejected (Zero Trust)."""
    doc = db.collection("payment_attempts").document(tx_id).get()
    return doc.exists

def save_payment_attempt(
    telegram_id: int,
    username: str,
    tx_id: str,
    plan_requested: str,
    screenshot_url: str,
    status: str = "PENDING",
    **extra_fields,
) -> bool:
    """Save a payment attempt. Returns False if duplicate tx_id."""
    if check_transaction_exists(tx_id):
        return False
        
    payload = {
        "transaction_id": tx_id,
        "telegram_id": telegram_id,
        "username": username,
        "plan_requested": plan_requested,
        "screenshot_url": screenshot_url,
        "status": str(status).upper(),
        "submitted_at": _now(),
        **extra_fields,
    }

    db.collection("payment_attempts").document(tx_id).set(payload)
    return True


def get_payment_attempt(tx_id: str) -> dict | None:
    doc = db.collection("payment_attempts").document(tx_id).get()
    return to_serializable(doc.to_dict()) if doc.exists else None


def update_payment_attempt(tx_id: str, updates: dict) -> bool:
    doc_ref = db.collection("payment_attempts").document(tx_id)
    doc = doc_ref.get()
    if not doc.exists:
        return False
    doc_ref.update(updates)
    return True


def finalize_payment_attempt(tx_id: str, *, status: str = "APPROVED", **updates) -> bool:
    doc_ref = db.collection("payment_attempts").document(tx_id)
    payload = {"status": str(status).upper(), **updates}
    if doc_ref.get().exists:
        doc_ref.update(payload)
    else:
        doc_ref.set({"transaction_id": tx_id, "submitted_at": _now(), **payload})
    return True

def get_pending_payments() -> list[dict]:
    # Filter in Firestore, sort in Python to avoid index requirement
    ref = db.collection("payment_attempts").where("status", "==", "PENDING").stream()
    results = [to_serializable(doc.to_dict()) for doc in ref]
    results.sort(key=lambda x: str(x.get("submitted_at", "")), reverse=True)
    return results

def approve_payment(tx_id: str) -> bool:
    data = get_payment_attempt(tx_id)
    if not data or str(data.get("status", "")).upper() != "PENDING":
        return False

    finalize_payment_attempt(tx_id, status="APPROVED")

    # Normalize plan_requested (e.g. 'pro_monthly', 'max_yearly') → 'pro' / 'max'
    raw_plan = str(data.get("plan_requested", "pro")).lower().strip()
    if "max" in raw_plan:
        tier = "max"
    elif "pro" in raw_plan:
        tier = "pro"
    else:
        tier = "pro"  # Safety default

    import datetime
    days = 365 if "yearly" in raw_plan else 30
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)

    # Ensure telegram_id is an int before stringifying to match create_user logic
    try:
        t_id = int(data["telegram_id"])
    except (ValueError, TypeError):
        t_id = data["telegram_id"]

    # One single update for efficiency and atomicity
    db.collection("users").document(str(t_id)).update({
        "tier": tier,
        "tier_updated_at": _now(),
        "subscription_expires_at": expires_at,
    })
    logger.info(f"Payment {tx_id} approved → user {t_id} upgraded to {tier}, expires {expires_at.date()}")
    return True

async def check_and_expire_subscriptions(application):
    """Background task to revert expired 30-day plans to free and notify users."""
    import datetime
    from telegram.constants import ParseMode
    
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Query for Pro/Max users
    try:
        paid_users = db.collection("users").where("tier", "!=", "free").stream()
    except Exception as e:
        logger.error(f"check_and_expire_subscriptions query failed: {e}")
        return
    
    for doc in paid_users:
        user_data = doc.to_dict()
        user_id = doc.id
        old_tier = user_data.get("tier", "free")
        if old_tier == "free":
            continue

        # Prefer explicit expiry field; fall back to tier_updated_at + 30 days
        expires_at = user_data.get("subscription_expires_at")
        tier_updated = user_data.get("tier_updated_at")

        if expires_at:
            # Handle Firestore Timestamp or datetime
            if hasattr(expires_at, "to_datetime"):
                expiry_dt = expires_at.to_datetime().replace(tzinfo=datetime.timezone.utc)
            elif hasattr(expires_at, "timestamp"):
                expiry_dt = expires_at.replace(tzinfo=datetime.timezone.utc) if expires_at.tzinfo is None else expires_at
            else:
                continue  # Can't parse, skip
        elif tier_updated:
            # Legacy: 30 days from tier_updated_at
            if hasattr(tier_updated, "to_datetime"):
                updated_dt = tier_updated.to_datetime().replace(tzinfo=datetime.timezone.utc)
            elif hasattr(tier_updated, "timestamp"):
                updated_dt = tier_updated.replace(tzinfo=datetime.timezone.utc) if tier_updated.tzinfo is None else tier_updated
            else:
                continue
            expiry_dt = updated_dt + datetime.timedelta(days=30)
        else:
            continue  # No date info, skip

        if now < expiry_dt:
            continue  # Not yet expired
        
        # Revert to free
        db.collection("users").document(user_id).update({
            "tier": "free",
            "tier_updated_at": _now()
        })
        logger.info(f"User {user_id} subscription expired (was {old_tier}), reverted to free.")

        # Send a single, clear expiry notification (bilingual, no duplicate)
        lang = user_data.get("language", "en")
        old_tier_upper = old_tier.upper()
        try:
            from keyboards import upgrade_keyboard
            if lang == "en":
                msg = (
                    f"⌛ **Your {old_tier_upper} Subscription has Expired**\n\n"
                    f"Your access to {old_tier_upper} features has ended. You have been moved back to the Free tier.\n\n"
                    "Don't lose your momentum! Upgrade again to continue enjoying unlimited questions, audio lessons, and expert tools. 🚀"
                )
            else:
                msg = (
                    f"⌛ **የ{old_tier_upper} ደንበኝነት ምዝገባዎ አብቅቷል**\n\n"
                    f"የ{old_tier_upper} አገልግሎቶች አጠቃቀምዎ አብቅቷል። ወደ ነፃ (Free) ተመልሰዋል።\n\n"
                    "ያልተገደቡ ጥያቄዎችን፣ የኦዲዮ ትምህርቶችን እና የባለሙያ መሳሪያዎችን ማግኘት እንዲቀጥሉ አሁኑኑ ያሳድጉ! 🚀"
                )
            await application.bot.send_message(
                chat_id=user_id,
                text=msg,
                parse_mode="Markdown",
                reply_markup=upgrade_keyboard()
            )
            logger.info(f"Notified user {user_id} of subscription expiry.")
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} of expiry: {e}")

def save_feature_suggestion(telegram_id: int, username: str, text: str):
    db.collection("feature_suggestions").add({
        "telegram_id": telegram_id,
        "username": username,
        "suggestion": text,
        "submitted_at": _now()
    })

def get_feature_suggestions() -> list[dict]:
    ref = db.collection("feature_suggestions").stream()
    results = [to_serializable(doc.to_dict()) for doc in ref]
    results.sort(key=lambda x: str(x.get("submitted_at", "")), reverse=True)
    return results

def reject_payment(tx_id: str) -> bool:
    doc = get_payment_attempt(tx_id)
    if not doc:
        return False
    
    finalize_payment_attempt(tx_id, status="REJECTED")
    return True


def check_feature_rate_limit(telegram_id: int, feature_name: str, hours: int = 24) -> bool:
    """
    Returns True if the user is allowed to use the feature (Pass 6.1 Fix).
    Prevents abuse of expensive AI endpoints like /predict and /radar.
    """
    import datetime
    ref = db.collection("users").document(str(telegram_id))
    user = ref.get().to_dict()
    if not user:
        return False
    
    last_used = user.get(f"last_{feature_name}_at")
    if last_used:
        now = datetime.datetime.now(datetime.timezone.utc)
        # Handle Firestore Timestamp objects
        if hasattr(last_used, "timestamp"):
            last_dt = last_used
        else:
            try:
                last_dt = datetime.datetime.fromisoformat(str(last_used))
            except ValueError:
                return True # Fallback if format is weird
            
        # Ensure last_dt is timezone-aware for comparison
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)

        if now - last_dt < datetime.timedelta(hours=hours):
            return False
            
    ref.update({f"last_{feature_name}_at": _now()})
    return True


def get_random_real_question(subject: str) -> dict | None:
    """Fetches a random real exam question from the Firestore collection."""
    try:
        # Simple random fetch: get a small batch and pick one
        docs = (
            db.collection("real_exam_questions")
            .where("subject", "==", subject)
            .limit(20)
            .stream()
        )
        import random
        results = [doc.to_dict() for doc in docs]
        if not results:
            return None
        return random.choice(results)
    except Exception as e:
        logger.error(f"Error fetching real question: {e}")
        return None

def get_wrong_questions(telegram_id: int, limit: int = 20) -> list[dict]:
    """Fetch the most recent wrong questions for a user."""
    try:
        docs = (
            db.collection("users")
            .document(str(telegram_id))
            .collection("wrong_questions")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        logger.error(f"Error fetching wrong questions: {e}")
        return []
