"""
db_supabase.py — Supabase PostgreSQL Database Layer for Abebe EUEE Bot

This module replaces Firebase/Firestore with Supabase PostgreSQL.
All functions maintain backward compatibility with the original db.py API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2.pool import ThreadedConnectionPool

from config import STREAK_FREEZE_EVERY, TIER_FEATURES, TIER_LIMITS, DATABASE_URL, SUPABASE_URL, SUPABASE_KEY, SUPABASE_DB_PASSWORD

logger = logging.getLogger(__name__)

# ============================================================================
# IN-MEMORY FALLBACK FOR DEV MODE
# ============================================================================

# Check if we're in DEV_MODE
_DEV_MODE = os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")

# In-memory store for DEV_MODE when database is unavailable
_memory_store = {
    "users": {},
    "payment_attempts": {},
    "tier_changes": [],
    "wrong_questions": [],
    "feature_suggestions": [],
    "battles": {},
    "boss_fights": {},
    "exams": [],
    "parent_reports": {},
    "content_cache": {},
    "daily_tips": [],
    "textbook_chunks": {},
    "real_exams": [],
}

# Connection pool (psycopg2)
_connection_pool: Optional[ThreadedConnectionPool] = None
_db_available = False

def _init_pool():
    """Initialize connection pool if possible."""
    global _connection_pool, _db_available
    if _connection_pool is not None:
        return _db_available
    
    # In DEV_MODE, skip database connection entirely
    if _DEV_MODE:
        logger.info("🔧 DEV_MODE detected - using IN-MEMORY mode (no database)")
        _db_available = False
        return False
    
    # Parse DATABASE_URL or construct from Supabase credentials
    db_url = DATABASE_URL
    if not db_url and SUPABASE_URL:
        project_ref = SUPABASE_URL.replace("https://", "").replace(".supabase.co", "")
        if SUPABASE_DB_PASSWORD:
            db_url = f"postgresql://postgres:{SUPABASE_DB_PASSWORD}@db.{project_ref}.supabase.co:5432/postgres"
    
    if not db_url:
        if _DEV_MODE:
            logger.warning("⚠️ No database URL configured — using IN-MEMORY mode for DEV")
            _db_available = False
            return False
        raise RuntimeError("DATABASE_URL or SUPABASE_URL with SUPABASE_DB_PASSWORD must be set")
    
    try:
        logger.info(f"🔗 Attempting database connection to: {db_url.split('@')[1] if '@' in db_url else 'unknown'}")
        _connection_pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=db_url
        )
        # Test connection
        conn = _connection_pool.getconn()
        _connection_pool.putconn(conn)
        _db_available = True
        logger.info("✅ Database connection pool initialized")
        return True
    except Exception as exc:
        if _DEV_MODE:
            logger.warning(f"⚠️ Database connection failed: {exc}")
            logger.warning("⚠️ Falling back to IN-MEMORY mode for DEV")
            _db_available = False
            return False
        logger.error(f"❌ Database connection failed: {exc}")
        raise

def _get_pool() -> ThreadedConnectionPool:
    """Get or create connection pool."""
    _init_pool()
    if _connection_pool is None:
        raise RuntimeError("Database not available")
    return _connection_pool

def _get_connection():
    """Get a connection from the pool."""
    return _get_pool().getconn()

def _put_connection(conn):
    """Return a connection to the pool."""
    if _connection_pool:
        _connection_pool.putconn(conn)

def _execute(query: str, params: tuple = None, fetch: str = None):
    """Execute a query and optionally fetch results."""
    if not _db_available:
        raise RuntimeError("Database not available")
    
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            
            if fetch == "one":
                result = cur.fetchone()
                conn.commit()
                return dict(result) if result else None
            elif fetch == "all":
                result = cur.fetchall()
                conn.commit()
                return [dict(row) for row in result]
            else:
                conn.commit()
                return None
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            _put_connection(conn)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


def _now() -> datetime:
    return _utcnow()


def _coerce_datetime(value: Any) -> Optional[datetime]:
    """Convert various datetime formats to Python datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Handle ISO format with timezone
        try:
            # Replace Z with +00:00 for Python < 3.11 compatibility
            value = value.replace("Z", "+00:00")
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                try:
                    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    return None
    return None


def to_serializable(data: Any) -> Any:
    """Recursively convert values to JSON-friendly objects."""
    if isinstance(data, list):
        return [to_serializable(item) for item in data]
    if isinstance(data, dict):
        return {key: to_serializable(value) for key, value in data.items()}
    if isinstance(data, datetime):
        return data.isoformat()
    if hasattr(data, "isoformat"):
        try:
            return data.isoformat()
        except Exception:
            return str(data)
    return data


# ============================================================================
# TIER FUNCTIONS
# ============================================================================

def normalize_tier(raw: str | None) -> str:
    if not raw:
        return "free"
    raw = str(raw).lower().strip()
    if "max" in raw:
        return "max"
    if "pro" in raw:
        return "pro"
    if raw == "free":
        return "free"
    return "free"


def has_access(tier: str, feature: str) -> bool:
    tier = normalize_tier(tier)
    if tier == "max":
        return True
    allowed = TIER_FEATURES.get(tier, [])
    if feature in allowed:
        return True
    if tier == "pro" and feature in TIER_FEATURES.get("free", []):
        return True
    return False


# ============================================================================
# USER FUNCTIONS
# ============================================================================

def get_user(telegram_id: int, use_cache: bool = True) -> dict | None:
    """Get user by Telegram ID."""
    if not _db_available:
        return _memory_store["users"].get(str(telegram_id))
    
    query = "SELECT * FROM users WHERE telegram_id = %s"
    result = _execute(query, (telegram_id,), fetch="one")
    return result


def create_user(telegram_id: int, name: str | None, language: str) -> dict:
    """Create a new user."""
    if not _db_available:
        parent_token = secrets.token_urlsafe(16)
        data = {
            "telegram_id": telegram_id,
            "name": (name or "Student")[:100],
            "language": language,
            "tier": "free",
            "subscription_active": True,
            "subscription_expires_at": None,
            "tier_updated_at": _now(),
            "streak": 0,
            "streak_freezes": 0,
            "last_active_date": _today(),
            "questions_today": 0,
            "questions_total": 0,
            "study_minutes_today": 0,
            "study_minutes_total": 0,
            "score_by_subject": {},
            "subject_correct": {},
            "subject_wrong": {},
            "subject_attempts": {},
            "topic_performance": {},
            "correct_total": 0,
            "wrong_total": 0,
            "exams_taken": 0,
            "badges": [],
            "parent_token": parent_token,
            "joined_at": _now(),
            "last_question_date": _today(),
            "last_explanation": "",
            "chosen_subject": "math",
            "questions_this_week": 0,
            "week_start": _today(),
        }
        
        _memory_store["users"][str(telegram_id)] = data
        return data
    
    parent_token = secrets.token_urlsafe(16)
    data = {
        "telegram_id": telegram_id,
        "name": (name or "Student")[:100],
        "language": language,
        "tier": "free",
        "subscription_active": True,
        "subscription_expires_at": None,
        "tier_updated_at": _now(),
        "streak": 0,
        "streak_freezes": 0,
        "last_active_date": _today(),
        "questions_today": 0,
        "questions_total": 0,
        "study_minutes_today": 0,
        "study_minutes_total": 0,
        "score_by_subject": {},
        "subject_correct": {},
        "subject_wrong": {},
        "subject_attempts": {},
        "topic_performance": {},
        "correct_total": 0,
        "wrong_total": 0,
        "exams_taken": 0,
        "badges": [],
        "parent_token": parent_token,
        "joined_at": _now(),
        "last_question_date": _today(),
        "last_explanation": "",
        "chosen_subject": "math",
        "questions_this_week": 0,
        "week_start": _today(),
    }
    
    query = """
        INSERT INTO users (telegram_id, name, language, tier, subscription_active,
                          subscription_expires_at, tier_updated_at, streak, streak_freezes,
                          last_active_date, questions_today, questions_total, study_minutes_today,
                          study_minutes_total, score_by_subject, subject_correct, subject_wrong,
                          subject_attempts, topic_performance, correct_total, wrong_total,
                          exams_taken, badges, parent_token, joined_at, last_question_date,
                          last_explanation, chosen_subject, questions_this_week, week_start)
        VALUES (%(telegram_id)s, %(name)s, %(language)s, %(tier)s, %(subscription_active)s,
                %(subscription_expires_at)s, %(tier_updated_at)s, %(streak)s, %(streak_freezes)s,
                %(last_active_date)s, %(questions_today)s, %(questions_total)s, %(study_minutes_today)s,
                %(study_minutes_total)s, %(score_by_subject)s, %(subject_correct)s, %(subject_wrong)s,
                %(subject_attempts)s, %(topic_performance)s, %(correct_total)s, %(wrong_total)s,
                %(exams_taken)s, %(badges)s, %(parent_token)s, %(joined_at)s, %(last_question_date)s,
                %(last_explanation)s, %(chosen_subject)s, %(questions_this_week)s, %(week_start)s)
        ON CONFLICT (telegram_id) DO NOTHING
    """
    _execute(query, data)
    return data


def update_user(telegram_id: int, updates: dict) -> None:
    """Update user fields."""
    # Get current user
    current = get_user(telegram_id) or {}
    
    # Handle tier change
    if "tier" in updates:
        old_tier = normalize_tier(current.get("tier"))
        new_tier = normalize_tier(updates["tier"])
        if old_tier != new_tier:
            _tier_change_log(telegram_id, old_tier, new_tier)
    
    # Update fields
    allowed_fields = [
        "name", "language", "tier", "subscription_active", "subscription_expires_at",
        "subscription_expired_at", "tier_updated_at", "streak", "streak_freezes",
        "last_active_date", "questions_today", "questions_total", "questions_this_week",
        "week_start", "study_minutes_today", "study_minutes_total", "score_by_subject",
        "subject_correct", "subject_wrong", "subject_attempts", "topic_performance",
        "correct_total", "wrong_total", "exams_taken", "badges", "parent_token",
        "last_question_date", "last_explanation", "chosen_subject", "last_predict_at"
    ]
    
    set_clauses = []
    params = []
    
    for key, value in updates.items():
        if key in allowed_fields:
            set_clauses.append(f"{key} = %s")
            if isinstance(value, (dict, list)):
                params.append(Json(value))
            elif isinstance(value, datetime):
                params.append(value)
            else:
                params.append(value)
    
    if set_clauses:
        params.append(telegram_id)
        query = f"UPDATE users SET {', '.join(set_clauses)}, updated_at = NOW() WHERE telegram_id = %s"
        _execute(query, tuple(params))


def upgrade_user_tier(telegram_id: int, tier: str) -> None:
    """Upgrade user to a new tier."""
    tier = normalize_tier(tier)
    current = get_user(telegram_id) or {}
    old_tier = normalize_tier(current.get("tier"))
    
    expires_at = None
    if tier != "free":
        expires_at = _utcnow() + timedelta(days=30)  # Default 30 days
    
    update_user(telegram_id, {
        "tier": tier,
        "tier_updated_at": _now(),
        "subscription_active": tier != "free",
        "subscription_expires_at": expires_at,
    })
    
    if old_tier != tier:
        _tier_change_log(telegram_id, old_tier, tier, reason="manual upgrade")


def get_user_tier(telegram_id: int) -> str:
    user = get_user(telegram_id)
    return normalize_tier(user.get("tier") if user else None)


def is_subscription_active(telegram_id: int) -> bool:
    """Check if user's subscription is active with PROPER timezone handling."""
    user = get_user(telegram_id)
    if not user:
        return False
    
    tier = normalize_tier(user.get("tier"))
    if tier == "free":
        return True
    
    # Check if subscription_active flag is set
    if user.get("subscription_active") is False:
        return False
    
    # Check expiry with proper timezone handling
    expires_at = user.get("subscription_expires_at")
    if not expires_at:
        # No expiry set but tier is paid - give them 30 days from tier_updated_at
        tier_updated = user.get("tier_updated_at")
        if tier_updated:
            tier_updated_dt = _coerce_datetime(tier_updated)
            if tier_updated_dt:
                if tier_updated_dt.tzinfo is None:
                    tier_updated_dt = tier_updated_dt.replace(tzinfo=timezone.utc)
                # Give grace period of 30 days from tier update
                expires_at = tier_updated_dt + timedelta(days=30)
                return _utcnow() < expires_at
        return True  # No expiry but paid tier - assume active
    
    expires_dt = _coerce_datetime(expires_at)
    if not expires_dt:
        return True
    
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
    
    return _utcnow() < expires_dt


def is_premium(telegram_id: int) -> bool:
    return get_user_tier(telegram_id) in ("pro", "max") and is_subscription_active(telegram_id)


def get_or_create_user(telegram_id: int, name: str, language: str = "en") -> dict:
    user = get_user(telegram_id)
    if user is None:
        user = create_user(telegram_id, name, language)
    return user


# ============================================================================
# QUESTION TRACKING
# ============================================================================

def check_questions_limit_reached(telegram_id: int, tier: str) -> bool:
    if tier != "free":
        return False
    user = get_user(telegram_id)
    if not user:
        return False
    if user.get("last_question_date") != _today():
        return False
    limit = TIER_LIMITS.get(tier, 5)
    return user.get("questions_today", 0) >= limit


def check_and_increment_questions(telegram_id: int, tier: str, limit: int) -> bool:
    user = get_user(telegram_id) or {}
    today = _today()
    
    # Reset counter if new day
    if user.get("last_question_date") != today:
        user["questions_today"] = 0
        user["last_question_date"] = today
    
    # Check limit for free users
    if tier == "free" and user.get("questions_today", 0) >= limit:
        return False
    
    # Increment counters
    update_user(telegram_id, {
        "questions_today": user.get("questions_today", 0) + 1,
        "questions_total": user.get("questions_total", 0) + 1,
        "questions_this_week": user.get("questions_this_week", 0) + 1,
    })
    return True


# ============================================================================
# STREAK FUNCTIONS
# ============================================================================

def update_streak(telegram_id: int) -> dict:
    user = get_user(telegram_id) or {}
    today = _today()
    yesterday = (_utcnow() - timedelta(days=1)).date().isoformat()
    
    if user.get("last_active_date") == today:
        return {"streak": user.get("streak", 0), "freeze_earned": False}
    
    current_streak = user.get("streak", 0)
    freezes = user.get("streak_freezes", 0)
    last_active = user.get("last_active_date", "")
    
    if last_active == yesterday or last_active == "":
        new_streak = current_streak + 1
    else:
        if freezes > 0:
            update_user(telegram_id, {
                "streak_freezes": freezes - 1,
                "last_active_date": today
            })
            return {"streak": current_streak, "freeze_used": True, "freeze_earned": False}
        new_streak = 1
    
    freeze_earned = new_streak > 0 and new_streak % STREAK_FREEZE_EVERY == 0
    updates = {
        "streak": new_streak,
        "last_active_date": today,
    }
    if freeze_earned:
        updates["streak_freezes"] = freezes + 1
    
    update_user(telegram_id, updates)
    return {"streak": new_streak, "freeze_earned": freeze_earned}


# ============================================================================
# ANSWER TRACKING
# ============================================================================

def record_answer(telegram_id: int, subject: str, correct: bool, topic: str = "General", question_data: dict | None = None) -> None:
    user = get_user(telegram_id) or {}
    safe_topic = (topic or "General").replace(".", "-")
    
    # Update subject stats
    score_by_subject = user.get("score_by_subject", {}) or {}
    subject_correct = user.get("subject_correct", {}) or {}
    subject_wrong = user.get("subject_wrong", {}) or {}
    subject_attempts = user.get("subject_attempts", {}) or {}
    topic_perf = user.get("topic_performance", {}) or {}
    
    score_by_subject[subject] = score_by_subject.get(subject, 0) + (1 if correct else 0)
    subject_correct[subject] = subject_correct.get(subject, 0) + (1 if correct else 0)
    subject_wrong[subject] = subject_wrong.get(subject, 0) + (0 if correct else 1)
    subject_attempts[subject] = subject_attempts.get(subject, 0) + 1
    
    # Update topic performance
    subject_topic = topic_perf.setdefault(subject, {})
    topic_row = subject_topic.setdefault(safe_topic, {"correct": 0, "attempts": 0})
    topic_row["correct"] += 1 if correct else 0
    topic_row["attempts"] += 1
    
    update_user(telegram_id, {
        "score_by_subject": score_by_subject,
        "subject_correct": subject_correct,
        "subject_wrong": subject_wrong,
        "subject_attempts": subject_attempts,
        "topic_performance": topic_perf,
        "correct_total": user.get("correct_total", 0) + (1 if correct else 0),
        "wrong_total": user.get("wrong_total", 0) + (0 if correct else 1),
        "study_minutes_today": user.get("study_minutes_today", 0) + 2,
        "study_minutes_total": user.get("study_minutes_total", 0) + 2,
    })
    
    # Save wrong question for review
    if not correct and question_data:
        query = """
            INSERT INTO wrong_questions (telegram_id, subject, topic, question, options, answer, explanation)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        _execute(query, (
            telegram_id,
            subject,
            topic,
            question_data.get("question", ""),
            Json(question_data.get("options", {})),
            question_data.get("answer", ""),
            question_data.get("explanation", ""),
        ))


# ============================================================================
# LEADERBOARD
# ============================================================================

def get_leaderboard(limit: int = 10) -> list[dict]:
    query = "SELECT * FROM users ORDER BY correct_total DESC LIMIT %s"
    return _execute(query, (limit,), fetch="all") or []


# ============================================================================
# EXAM RESULTS
# ============================================================================

def save_exam_result(telegram_id: int, subject: str, score: int, total: int, weak_topics: list) -> None:
    percentage = round(score / total * 100, 1) if total else 0
    query = """
        INSERT INTO exam_results (telegram_id, subject, score, total, percentage, weak_topics)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    _execute(query, (telegram_id, subject, score, total, percentage, Json(weak_topics)))
    
    # Increment exams taken
    user = get_user(telegram_id) or {}
    update_user(telegram_id, {"exams_taken": user.get("exams_taken", 0) + 1})


def get_exam_results(telegram_id: int, limit: int = 5) -> list[dict]:
    query = """
        SELECT * FROM exam_results 
        WHERE telegram_id = %s 
        ORDER BY taken_at DESC 
        LIMIT %s
    """
    return _execute(query, (telegram_id, limit), fetch="all") or []


# ============================================================================
# CONFESSIONS
# ============================================================================

def save_confession(telegram_id: int, topic: str) -> None:
    query = "INSERT INTO confessions (telegram_id, topic) VALUES (%s, %s)"
    _execute(query, (telegram_id, topic[:500]))


# ============================================================================
# BATTLES
# ============================================================================

def create_battle(challenger_id: int, subject: str, question_data: dict) -> str:
    battle_id = str(uuid.uuid4())
    query = """
        INSERT INTO battles (battle_id, challenger_id, subject, question, options, correct_answer, explanation, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'waiting')
    """
    _execute(query, (
        battle_id,
        challenger_id,
        subject,
        question_data.get("question", ""),
        Json(question_data.get("options", {})),
        question_data.get("answer", ""),
        question_data.get("explanation", ""),
    ))
    return battle_id


def get_battle(battle_id: str) -> dict | None:
    query = "SELECT * FROM battles WHERE battle_id = %s"
    return _execute(query, (battle_id,), fetch="one")


def join_battle(battle_id: str, opponent_id: int) -> dict | None:
    battle = get_battle(battle_id)
    if not battle or battle.get("status") not in ("waiting", "active"):
        return None
    if battle.get("challenger_id") == opponent_id:
        return battle
    if battle.get("opponent_id") and battle.get("opponent_id") != opponent_id:
        return None
    
    query = "UPDATE battles SET opponent_id = %s, status = 'active' WHERE battle_id = %s"
    _execute(query, (opponent_id, battle_id))
    return get_battle(battle_id)


def submit_battle_answer(battle_id: str, user_id: int, answer: str, time_secs: float, is_correct: bool) -> dict:
    battle = get_battle(battle_id) or {}
    if not battle:
        return {}
    
    if battle.get("challenger_id") == user_id:
        query = "UPDATE battles SET challenger_answer = %s, challenger_time = %s, challenger_correct = %s WHERE battle_id = %s"
    else:
        query = "UPDATE battles SET opponent_answer = %s, opponent_time = %s, opponent_correct = %s WHERE battle_id = %s"
    
    _execute(query, (answer, time_secs, is_correct, battle_id))
    return get_battle(battle_id)


def finalize_battle(battle_id: str, winner_id: int | None, challenger_correct: bool, opponent_correct: bool) -> None:
    query = """
        UPDATE battles 
        SET winner_id = %s, challenger_correct = %s, opponent_correct = %s, status = 'done', finished_at = NOW()
        WHERE battle_id = %s
    """
    _execute(query, (winner_id, challenger_correct, opponent_correct, battle_id))


# ============================================================================
# BOSS FIGHTS
# ============================================================================

def get_boss_fight_week() -> dict | None:
    week = _utcnow().isocalendar()[1]
    year = _utcnow().year
    query = "SELECT * FROM boss_fights WHERE year = %s AND week = %s"
    return _execute(query, (year, week), fetch="one")


def save_boss_fight(question: str, subject: str, model_answer: str | None = None, explanation: str | None = None) -> None:
    week = _utcnow().isocalendar()[1]
    year = _utcnow().year
    id_key = f"{year}_{week}"
    
    query = """
        INSERT INTO boss_fights (id, year, week, subject, question, model_answer, explanation)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            subject = EXCLUDED.subject,
            question = EXCLUDED.question,
            model_answer = EXCLUDED.model_answer,
            explanation = EXCLUDED.explanation
    """
    _execute(query, (id_key, year, week, subject, question, model_answer, explanation))


def complete_boss_fight(telegram_id: int) -> None:
    week = _utcnow().isocalendar()[1]
    year = _utcnow().year
    id_key = f"{year}_{week}"
    
    # Add to completers
    battle = get_boss_fight_week() or {}
    completers = set(battle.get("completers", []) or [])
    completers.add(telegram_id)
    
    query = "UPDATE boss_fights SET completers = %s WHERE id = %s"
    _execute(query, (Json(list(completers)), id_key))
    
    # Add badge
    user = get_user(telegram_id) or {}
    badges = user.get("badges", []) or []
    if "🏆 Champion" not in badges:
        badges.append("🏆 Champion")
        update_user(telegram_id, {"badges": badges})


# ============================================================================
# PARENT LINK
# ============================================================================

def get_user_by_parent_token(token: str) -> dict | None:
    query = "SELECT * FROM users WHERE parent_token = %s"
    return _execute(query, (token,), fetch="one")


# ============================================================================
# DAILY TIPS
# ============================================================================

def save_daily_tip(tip: str) -> None:
    today = _today()
    query = """
        INSERT INTO daily_tips (date, tip) VALUES (%s, %s)
        ON CONFLICT (date) DO UPDATE SET tip = EXCLUDED.tip
    """
    _execute(query, (today, tip))


def get_daily_tip() -> str | None:
    today = _today()
    query = "SELECT tip FROM daily_tips WHERE date = %s"
    result = _execute(query, (today,), fetch="one")
    return result.get("tip") if result else None


# ============================================================================
# CONTENT CACHE
# ============================================================================

def get_cached_content(cache_key: str) -> dict | None:
    query = "SELECT data FROM content_cache WHERE cache_key = %s"
    result = _execute(query, (cache_key,), fetch="one")
    return result.get("data") if result else None


def set_cached_content(cache_key: str, data: dict) -> None:
    query = """
        INSERT INTO content_cache (cache_key, data) VALUES (%s, %s)
        ON CONFLICT (cache_key) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
    """
    _execute(query, (cache_key, Json(data)))


def clear_subject_notes_cache(subject: str) -> None:
    for lang_code in ("en", "am"):
        for key in (f"notes_{subject}_{lang_code}", f"audio_script_{subject}_{lang_code}"):
            query = "DELETE FROM content_cache WHERE cache_key = %s"
            _execute(query, (key,))


# ============================================================================
# PAYMENT FUNCTIONS
# ============================================================================

def user_telebirr_rate_limit_exceeded(telegram_id: int) -> bool:
    """Check if user has made too many payment attempts recently."""
    query = """
        SELECT submitted_at FROM payment_attempts 
        WHERE telegram_id = %s 
        ORDER BY submitted_at DESC 
        LIMIT 5
    """
    attempts = _execute(query, (telegram_id,), fetch="all") or []
    
    if len(attempts) < 5:
        return False
    
    last_attempt = attempts[4]
    submitted_at = _coerce_datetime(last_attempt.get("submitted_at"))
    if isinstance(submitted_at, datetime):
        hour_ago = _utcnow() - timedelta(hours=1)
        return submitted_at > hour_ago
    return False


def check_transaction_exists(tx_id: str) -> bool:
    query = "SELECT 1 FROM payment_attempts WHERE transaction_id = %s"
    result = _execute(query, (tx_id,), fetch="one")
    return result is not None


def save_payment_attempt(
    telegram_id: int,
    username: str,
    tx_id: str,
    plan_requested: str,
    screenshot_url: str,
    status: str = "PENDING",
    **extra_fields,
) -> bool:
    if check_transaction_exists(tx_id):
        return False
    
    query = """
        INSERT INTO payment_attempts 
        (transaction_id, telegram_id, username, plan_requested, screenshot_url, status, amount, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    _execute(query, (
        tx_id,
        telegram_id,
        username,
        plan_requested,
        screenshot_url,
        status.upper(),
        extra_fields.get("amount"),
        extra_fields.get("source", "telebirr"),
    ))
    return True


def get_payment_attempt(tx_id: str) -> dict | None:
    query = "SELECT * FROM payment_attempts WHERE transaction_id = %s"
    return _execute(query, (tx_id,), fetch="one")


def update_payment_attempt(tx_id: str, updates: dict) -> bool:
    if not check_transaction_exists(tx_id):
        return False
    
    set_clauses = []
    params = []
    
    for key, value in updates.items():
        if key in ["screenshot_url", "status", "approved_at", "approved_by"]:
            set_clauses.append(f"{key} = %s")
            params.append(value)
    
    if set_clauses:
        params.append(tx_id)
        query = f"UPDATE payment_attempts SET {', '.join(set_clauses)}, updated_at = NOW() WHERE transaction_id = %s"
        _execute(query, tuple(params))
    return True


def finalize_payment_attempt(tx_id: str, *, status: str = "APPROVED", **updates) -> bool:
    if check_transaction_exists(tx_id):
        update_payment_attempt(tx_id, {"status": status.upper(), **updates})
    else:
        # Create minimal record
        query = """
            INSERT INTO payment_attempts (transaction_id, status, submitted_at)
            VALUES (%s, %s, NOW())
        """
        _execute(query, (tx_id, status.upper()))
    return True


def get_pending_payments() -> list[dict]:
    query = "SELECT * FROM payment_attempts WHERE status = 'PENDING' ORDER BY submitted_at DESC"
    return _execute(query, fetch="all") or []


def approve_payment(tx_id: str) -> bool:
    """Approve a payment and upgrade the user."""
    data = get_payment_attempt(tx_id)
    if not data or str(data.get("status", "")).upper() != "PENDING":
        return False
    
    raw_plan = str(data.get("plan_requested", "pro")).lower().strip()
    tier = "max" if "max" in raw_plan else "pro"
    days = 365 if "yearly" in raw_plan else 30
    expires_at = _utcnow() + timedelta(days=days)
    
    try:
        t_id = int(data["telegram_id"])
    except (KeyError, ValueError, TypeError) as exc:
        logger.error("approve_payment: could not resolve telegram_id for tx %s: %s", tx_id, exc)
        return False
    
    # Verify user exists
    user = get_user(t_id)
    if not user:
        logger.error("approve_payment: user %s does not exist", t_id)
        return False
    
    old_tier = normalize_tier(user.get("tier"))
    
    # Update user tier
    update_user(t_id, {
        "tier": tier,
        "tier_updated_at": _now(),
        "subscription_expires_at": expires_at,
        "subscription_active": True,
    })
    
    _tier_change_log(t_id, old_tier, tier, reason="payment approved")
    finalize_payment_attempt(tx_id, status="APPROVED", approved_at=_now())
    
    # Verify write
    refreshed = get_user(t_id)
    new_tier = normalize_tier(refreshed.get("tier")) if refreshed else None
    if new_tier != tier:
        logger.error("approve_payment: tier write verification FAILED for user %s! Expected %s, got %s", t_id, tier, new_tier)
        return False
    
    logger.info("approve_payment: Success for user %s (Tier: %s, Expires: %s)", t_id, tier, expires_at)
    return True


def reject_payment(tx_id: str) -> bool:
    data = get_payment_attempt(tx_id)
    if not data:
        return False
    finalize_payment_attempt(tx_id, status="REJECTED")
    return True


# ============================================================================
# SUBSCRIPTION EXPIRY (CRITICAL FIX)
# ============================================================================

async def check_and_expire_subscriptions(application) -> None:
    """
    Mark subscriptions inactive when they expire WITHOUT reverting tier.
    This preserves the user's tier history while disabling premium features.
    """
    now = _utcnow()
    
    query = """
        SELECT telegram_id, tier, subscription_expires_at, tier_updated_at, language
        FROM users 
        WHERE tier != 'free' 
        AND (subscription_active = TRUE OR subscription_active IS NULL)
    """
    
    try:
        users = _execute(query, fetch="all") or []
    except Exception as exc:
        logger.error("check_and_expire_subscriptions query failed: %s", exc)
        return
    
    expired_count = 0
    
    for user_data in users:
        user_id = user_data["telegram_id"]
        old_tier = user_data.get("tier", "free")
        expires_at = user_data.get("subscription_expires_at")
        tier_updated = user_data.get("tier_updated_at")
        lang = user_data.get("language", "en")
        
        expiry_dt = None
        
        if expires_at:
            expiry_dt = _coerce_datetime(expires_at)
        elif tier_updated:
            updated_dt = _coerce_datetime(tier_updated)
            if isinstance(updated_dt, datetime):
                expiry_dt = updated_dt + timedelta(days=30)
        
        if not isinstance(expiry_dt, datetime):
            continue
        
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        
        # Check if expired
        if now < expiry_dt:
            continue
        
        # Mark subscription inactive but KEEP the tier
        try:
            update_user(user_id, {
                "subscription_active": False,
                "subscription_expired_at": now,
            })
            
            logger.info("User %s subscription expired (tier=%s), marked inactive.", user_id, old_tier)
            expired_count += 1
            
            # Notify user
            try:
                from keyboards import upgrade_keyboard
                
                if lang == "en":
                    msg = (
                        f"⌛ **Your {old_tier.upper()} Subscription has Expired**\n\n"
                        f"Your access to {old_tier.upper()} features has ended. "
                        f"Renew your plan to continue using premium tools. 🚀"
                    )
                else:
                    msg = (
                        f"⌛ **የ{old_tier.upper()} ደንበኝነት ምዝገባዎ አብቅቷል**\n\n"
                        f"የ{old_tier.upper()} አገልግሎቶች አጠቃቀምዎ አብቅቷል። "
                        f"አሁኑኑ ያሳድጉ እንዲቀጥሉ። 🚀"
                    )
                
                await application.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode="Markdown",
                    reply_markup=upgrade_keyboard()
                )
            except Exception as exc:
                logger.error("Failed to notify user %s of expiry: %s", user_id, exc)
                
        except Exception as exc:
            logger.error("Failed to expire subscription for user %s: %s", user_id, exc)
    
    logger.info("check_and_expire_subscriptions: expired=%s", expired_count)


# ============================================================================
# FEATURE SUGGESTIONS
# ============================================================================

def save_feature_suggestion(telegram_id: int, username: str, suggestion: str, language: str = "en") -> None:
    query = """
        INSERT INTO feature_suggestions (telegram_id, username, suggestion, language)
        VALUES (%s, %s, %s, %s)
    """
    _execute(query, (telegram_id, username, suggestion, language))


def get_feature_suggestions() -> list[dict]:
    query = "SELECT * FROM feature_suggestions ORDER BY submitted_at DESC"
    return _execute(query, fetch="all") or []


# ============================================================================
# FEATURE RATE LIMITING
# ============================================================================

def check_feature_rate_limit(telegram_id: int, feature_name: str, hours: int = 24) -> bool:
    user = get_user(telegram_id)
    if not user:
        return False
    
    field_name = f"last_{feature_name}_at"
    last_used = user.get(field_name)
    
    if last_used:
        last_dt = _coerce_datetime(last_used)
        if isinstance(last_dt, datetime):
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if _utcnow() - last_dt < timedelta(hours=hours):
                return False
    
    update_user(telegram_id, {field_name: _now()})
    return True


# ============================================================================
# WEAK SUBJECTS
# ============================================================================

def get_weak_subjects(telegram_id: int) -> dict:
    user = get_user(telegram_id)
    if not user:
        return {}
    
    attempts = user.get("subject_attempts", {}) or {}
    correct = user.get("subject_correct", {}) or {}
    
    result = {}
    for subj, total in attempts.items():
        c = correct.get(subj, 0)
        result[subj] = round(c / total * 100) if total > 0 else 0
    return result


def get_top_scorer_this_week() -> dict | None:
    query = "SELECT * FROM users ORDER BY questions_this_week DESC LIMIT 1"
    return _execute(query, fetch="one")


# ============================================================================
# TEXTBOOK CHUNKS (for RAG)
# ============================================================================

def get_chunks_for_subject(subject: str, limit: int = 5) -> list[str]:
    query = "SELECT text FROM textbook_chunks WHERE subject = %s LIMIT %s"
    results = _execute(query, (subject, limit), fetch="all") or []
    return [r.get("text", "") for r in results]


# ============================================================================
# REAL EXAM QUESTIONS
# ============================================================================

def get_random_real_question(subject: str) -> dict | None:
    query = """
        SELECT * FROM real_exam_questions 
        WHERE subject = %s 
        ORDER BY RANDOM() 
        LIMIT 1
    """
    return _execute(query, (subject,), fetch="one")


def add_real_question(subject: str, question_data: dict) -> bool:
    try:
        query = """
            INSERT INTO real_exam_questions (subject, question, options, answer, explanation, topic, year, source_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        _execute(query, (
            subject,
            question_data.get("question", ""),
            Json(question_data.get("options", {})),
            question_data.get("answer", ""),
            question_data.get("explanation", ""),
            question_data.get("topic", "General"),
            question_data.get("year"),
            question_data.get("source_url"),
        ))
        return True
    except Exception as exc:
        logger.error("Error adding real question: %s", exc)
        return False


# ============================================================================
# WRONG QUESTIONS
# ============================================================================

def get_wrong_questions(telegram_id: int, limit: int = 20) -> list[dict]:
    query = """
        SELECT * FROM wrong_questions 
        WHERE telegram_id = %s 
        ORDER BY timestamp DESC 
        LIMIT %s
    """
    return _execute(query, (telegram_id, limit), fetch="all") or []


# ============================================================================
# PANIC MODE
# ============================================================================

def is_panic_mode() -> bool:
    from config import EUEE_EXAM_DATE
    delta = (EUEE_EXAM_DATE - _utcnow().date()).days
    return 0 <= delta <= 7


def get_panic_kit_questions() -> list[str]:
    query = "SELECT question FROM panic_kit ORDER BY rank LIMIT 50"
    results = _execute(query, fetch="all") or []
    return [r.get("question", "") for r in results]


# ============================================================================
# INTERNAL FUNCTIONS
# ============================================================================

def _tier_change_log(telegram_id: int, old_tier: str, new_tier: str, reason: str | None = None) -> None:
    query = """
        INSERT INTO tier_change_log (telegram_id, old_tier, new_tier, reason)
        VALUES (%s, %s, %s, %s)
    """
    _execute(query, (telegram_id, old_tier, new_tier, reason))


# ============================================================================
# BACKWARD COMPATIBILITY: DocumentDB interface
# ============================================================================

class DocumentSnapshot:
    """Mock Firestore DocumentSnapshot for backward compatibility."""
    
    def __init__(self, data: dict | None, doc_id: str):
        self.data = data
        self.id = doc_id
        self._data = data  # for compatibility
    
    @property
    def exists(self) -> bool:
        return self.data is not None
    
    def to_dict(self) -> dict | None:
        return self.data


class CollectionRef:
    """Mock Firestore CollectionRef for backward compatibility."""
    
    def __init__(self, name: str):
        self.name = name
    
    def document(self, doc_id: str | None = None):
        return DocumentRef(self.name, doc_id or str(uuid.uuid4()))
    
    def add(self, data: dict):
        doc_ref = self.document()
        # Handle different collections
        if self.name == "users":
            telegram_id = data.get("telegram_id")
            if telegram_id:
                create_user(telegram_id, data.get("name"), data.get("language", "en"))
        elif self.name == "confessions":
            telegram_id = data.get("telegram_id")
            if telegram_id:
                save_confession(telegram_id, data.get("topic", ""))
        elif self.name == "exam_results":
            telegram_id = data.get("telegram_id")
            if telegram_id:
                save_exam_result(
                    telegram_id,
                    data.get("subject", ""),
                    data.get("score", 0),
                    data.get("total", 0),
                    data.get("weak_topics", [])
                )
        elif self.name == "feature_suggestions":
            telegram_id = data.get("telegram_id")
            if telegram_id:
                save_feature_suggestion(
                    telegram_id,
                    data.get("username", ""),
                    data.get("suggestion", "")
                )
        elif self.name == "tier_change_log":
            telegram_id = data.get("telegram_id")
            if telegram_id:
                _tier_change_log(
                    telegram_id,
                    data.get("old_tier", ""),
                    data.get("new_tier", ""),
                    data.get("reason")
                )
        elif self.name == "daily_tips":
            date = data.get("date")
            tip = data.get("tip")
            if date and tip:
                save_daily_tip(tip)
        elif self.name == "content_cache":
            key = data.get("cache_key")
            if key:
                set_cached_content(key, data.get("data", {}))
        
        return doc_ref, None
    
    def where(self, field: str, op: str, value: any):
        return Query(self.name, field, op, value)
    
    def order_by(self, field: str, direction: str = None):
        return Query(self.name, order_by=field, order_dir=direction)
    
    def limit(self, n: int):
        return Query(self.name, limit=n)
    
    def stream(self):
        """Return all documents in collection."""
        if self.name == "users":
            query = "SELECT telegram_id as doc_id, * FROM users"
            results = _execute(query, fetch="all") or []
            for r in results:
                doc_id = str(r.pop("telegram_id", r.get("doc_id", uuid.uuid4())))
                yield DocumentSnapshot(r, doc_id)
        elif self.name == "payment_attempts":
            query = "SELECT transaction_id as doc_id, * FROM payment_attempts"
            results = _execute(query, fetch="all") or []
            for r in results:
                doc_id = r.get("transaction_id", r.get("doc_id", uuid.uuid4()))
                yield DocumentSnapshot(r, str(doc_id))
        elif self.name == "exam_results":
            query = "SELECT id as doc_id, * FROM exam_results"
            results = _execute(query, fetch="all") or []
            for r in results:
                doc_id = str(r.get("id", r.get("doc_id", uuid.uuid4())))
                yield DocumentSnapshot(r, doc_id)
        elif self.name == "confessions":
            query = "SELECT id as doc_id, * FROM confessions"
            results = _execute(query, fetch="all") or []
            for r in results:
                doc_id = str(r.get("id", r.get("doc_id", uuid.uuid4())))
                yield DocumentSnapshot(r, doc_id)
        elif self.name == "battles":
            query = "SELECT battle_id as doc_id, * FROM battles"
            results = _execute(query, fetch="all") or []
            for r in results:
                doc_id = str(r.get("battle_id", r.get("doc_id", uuid.uuid4())))
                yield DocumentSnapshot(r, doc_id)
        elif self.name == "feature_suggestions":
            query = "SELECT id as doc_id, * FROM feature_suggestions"
            results = _execute(query, fetch="all") or []
            for r in results:
                doc_id = str(r.get("id", r.get("doc_id", uuid.uuid4())))
                yield DocumentSnapshot(r, doc_id)
        elif self.name == "tier_change_log":
            query = "SELECT id as doc_id, * FROM tier_change_log"
            results = _execute(query, fetch="all") or []
            for r in results:
                doc_id = str(r.get("id", r.get("doc_id", uuid.uuid4())))
                yield DocumentSnapshot(r, doc_id)
        else:
            return


class DocumentRef:
    """Mock Firestore DocumentRef for backward compatibility."""
    
    def __init__(self, collection: str, doc_id: str):
        self.collection_path = collection
        self.id = doc_id
    
    def get(self):
        if self.collection_path == "users":
            data = get_user(int(self.id))
            return DocumentSnapshot(data, self.id)
        elif self.collection_path == "payment_attempts":
            data = get_payment_attempt(self.id)
            return DocumentSnapshot(data, self.id)
        elif self.collection_path == "boss_fights":
            if "_" in self.id:
                data = get_boss_fight_week()
                return DocumentSnapshot(data, self.id)
        elif self.collection_path == "battles":
            data = get_battle(self.id)
            return DocumentSnapshot(data, self.id)
        elif self.collection_path == "daily_tips":
            tip = get_daily_tip()
            return DocumentSnapshot({"tip": tip, "date": _today()} if tip else None, self.id)
        elif self.collection_path == "content_cache":
            data = get_cached_content(self.id)
            return DocumentSnapshot(data, self.id)
        return DocumentSnapshot(None, self.id)
    
    def set(self, data: dict, merge: bool = False):
        if self.collection_path == "users":
            try:
                telegram_id = int(self.id)
                update_user(telegram_id, data)
            except ValueError:
                pass
        elif self.collection_path == "payment_attempts":
            if data.get("status") == "APPROVED":
                approve_payment(self.id)
            else:
                finalize_payment_attempt(self.id, **data)
        elif self.collection_path == "boss_fights":
            if data.get("question"):
                save_boss_fight(
                    data.get("question", ""),
                    data.get("subject", ""),
                    data.get("model_answer"),
                    data.get("explanation")
                )
        elif self.collection_path == "battles":
            # Handle battle updates
            pass
        elif self.collection_path == "content_cache":
            set_cached_content(self.id, data)
    
    def update(self, updates: dict):
        if self.collection_path == "users":
            try:
                telegram_id = int(self.id)
                update_user(telegram_id, updates)
            except ValueError:
                pass
        elif self.collection_path == "payment_attempts":
            update_payment_attempt(self.id, updates)
    
    def delete(self):
        if self.collection_path == "content_cache":
            query = "DELETE FROM content_cache WHERE cache_key = %s"
            _execute(query, (self.id,))
    
    def collection(self, name: str):
        return CollectionRef(f"{self.collection_path}/{self.id}/{name}")


class Query:
    """Mock Firestore Query for backward compatibility."""
    
    def __init__(self, collection: str, field: str = None, op: str = None, value: any = None, 
                 order_by: str = None, order_dir: str = None, limit: int = None):
        self.collection = collection
        self.field = field
        self.op = op
        self.value = value
        self.order_by_field = order_by
        self.order_dir = order_dir
        self.limit_n = limit
    
    def where(self, field: str, op: str, value: any):
        return Query(self.collection, field, op, value, self.order_by_field, self.order_dir, self.limit_n)
    
    def order_by(self, field: str, direction: str = None):
        return Query(self.collection, self.field, self.op, self.value, field, direction, self.limit_n)
    
    def limit(self, n: int):
        return Query(self.collection, self.field, self.op, self.value, self.order_by_field, self.order_dir, n)
    
    def start_after(self, snapshot):
        # Simplified - just return self for compatibility
        return self
    
    def stream(self):
        """Execute query and return results."""
        if self.collection == "users":
            if self.field == "parent_token" and self.op == "==":
                user = get_user_by_parent_token(self.value)
                if user:
                    yield DocumentSnapshot(user, str(user.get("telegram_id")))
            elif self.field == "tier" and self.op == "!=":
                # Get non-free users
                query = "SELECT telegram_id as doc_id, * FROM users WHERE tier != 'free'"
                if self.limit_n:
                    query += f" LIMIT {self.limit_n}"
                results = _execute(query, fetch="all") or []
                for r in results:
                    doc_id = str(r.pop("telegram_id", r.get("doc_id", uuid.uuid4())))
                    yield DocumentSnapshot(r, doc_id)
            else:
                # Return all users
                for doc in CollectionRef("users").stream():
                    yield doc
                    
        elif self.collection == "payment_attempts":
            if self.field == "status" and self.op == "==" and self.value == "PENDING":
                for payment in get_pending_payments():
                    yield DocumentSnapshot(payment, payment.get("transaction_id", str(uuid.uuid4())))
                    
        elif self.collection == "exam_results":
            if self.field == "telegram_id" and self.op == "==":
                results = get_exam_results(self.value, self.limit_n or 100)
                for r in results:
                    yield DocumentSnapshot(r, str(r.get("id", uuid.uuid4())))
                    
        elif self.collection == "parent_reports":
            if self.field == "parent_token" and self.op == "==":
                query = "SELECT id as doc_id, * FROM parent_reports WHERE parent_token = %s"
                results = _execute(query, (self.value,), fetch="all") or []
                for r in results:
                    doc_id = str(r.get("id", r.get("doc_id", uuid.uuid4())))
                    yield DocumentSnapshot(r, doc_id)
                    
        elif self.collection == "textbook_chunks":
            if self.field == "subject" and self.op == "==":
                query = "SELECT id as doc_id, * FROM textbook_chunks WHERE subject = %s"
                params = [self.value]
                if self.limit_n:
                    query += f" LIMIT {self.limit_n}"
                results = _execute(query, tuple(params), fetch="all") or []
                for r in results:
                    doc_id = str(r.get("id", r.get("doc_id", uuid.uuid4())))
                    yield DocumentSnapshot(r, doc_id)
                    
        elif self.collection == "real_exam_questions":
            if self.field == "subject" and self.op == "==":
                query = "SELECT id as doc_id, * FROM real_exam_questions WHERE subject = %s LIMIT 20"
                results = _execute(query, (self.value,), fetch="all") or []
                for r in results:
                    doc_id = str(r.get("id", r.get("doc_id", uuid.uuid4())))
                    yield DocumentSnapshot(r, doc_id)
        else:
            # Default: return empty
            return


class DocumentDB:
    """Mock Firestore client for backward compatibility."""
    
    def collection(self, name: str):
        return CollectionRef(name)


# Create global db instance for compatibility
db = DocumentDB()

# ============================================================================
# INITIALIZATION
# ============================================================================

def init_database():
    """Initialize database connection pool."""
    global _connection_pool
    if _connection_pool is None:
        try:
            # Just create the pool to test connection
            _get_pool()
            logger.info("✅ Database connection pool initialized")
        except Exception as exc:
            logger.error("❌ Failed to initialize database: %s", exc)
            raise


# Initialize on import
try:
    init_database()
except Exception as e:
    logger.warning("Database initialization deferred: %s", e)
