"""
db_stub.py — In-memory stub of database operations for local DEV_MODE
This implements a lightweight subset of the real `db.py` API so the bot and
server can be started locally without Firebase credentials.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
import uuid
from config import TIER_LIMITS, TIER_FEATURES

STORE = defaultdict(dict)

class DocumentSnapshot:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return self._data


class DocumentRef:
    def __init__(self, coll, doc_id):
        self.coll = coll
        self.id = str(doc_id)

    def set(self, data):
        STORE[self.coll][self.id] = data

    def update(self, updates):
        if self.id not in STORE[self.coll]:
            STORE[self.coll][self.id] = {}
        STORE[self.coll][self.id].update(updates)

    def get(self):
        data = STORE[self.coll].get(self.id)
        return DocumentSnapshot(data)


class DummyQuery:
    def __init__(self, name, filters=None, order=None, limit_n=None):
        self.name = name
        self.filters = filters or []
        self.order = order
        self.limit_n = limit_n

    def where(self, field, op, value):
        return DummyQuery(self.name, self.filters + [(field, op, value)], self.order, self.limit_n)

    def order_by(self, field, direction=None):
        return DummyQuery(self.name, self.filters, (field, direction), self.limit_n)

    def limit(self, n):
        return DummyQuery(self.name, self.filters, self.order, n)

    def _matches(self, data):
        for field, op, value in self.filters:
            current = data.get(field)
            if op == "==" and current != value:
                return False
            if op == "!=" and current == value:
                return False
            if op == "<" and not (current < value):
                return False
            if op == ">" and not (current > value):
                return False
        return True

    def stream(self):
        items = [DocumentSnapshot(data) for data in STORE[self.name].values() if self._matches(data)]
        if self.order:
            field, direction = self.order
            reverse = str(direction).lower().endswith("desc")
            items.sort(key=lambda snap: (snap.to_dict() or {}).get(field), reverse=reverse)
        if self.limit_n is not None:
            items = items[: self.limit_n]
        return iter(items)


class DummyCollection:
    def __init__(self, name):
        self.name = name

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = str(uuid.uuid4())
        return DocumentRef(self.name, doc_id)

    def add(self, data):
        doc_id = str(uuid.uuid4())
        STORE[self.name][doc_id] = data
        return (DocumentRef(self.name, doc_id), None)

    def stream(self):
        for _id, data in STORE[self.name].items():
            yield DocumentSnapshot(data)

    # Query-style chainables used in a few places — return self and ignore filters
    def where(self, field, op, value):
        return DummyQuery(self.name).where(field, op, value)

    def order_by(self, field, direction=None):
        return DummyQuery(self.name).order_by(field, direction)

    def limit(self, n):
        return DummyQuery(self.name).limit(n)


class DummyDB:
    def collection(self, name):
        return DummyCollection(name)


# Firestore-like helpers
class Increment:
    def __init__(self, n):
        self.n = n


class ArrayUnion:
    def __init__(self, arr):
        self.arr = arr


# Public API expected by the project
db = DummyDB()

def _today():
    return date.today().isoformat()


def _now():
    return datetime.utcnow().isoformat()


def _collection_dict(name: str) -> dict:
    return STORE[name]


def _get_collection_items(name: str) -> list[dict]:
    return list(STORE[name].values())


def get_or_create_user(telegram_id: int, name: str, language: str = "en"):
    return get_user(telegram_id) or create_user(telegram_id, name, language)


def upgrade_user_tier(telegram_id: int, tier: str):
    update_user(telegram_id, {"tier": normalize_tier(tier)})

def normalize_tier(raw: str | None) -> str:
    """Normalize tier values like 'pro_monthly', 'max_yearly' → 'pro', 'max'."""
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
    """Centralized check for feature access based on tier (Stub)."""
    tier = normalize_tier(tier)
    if tier == "max":
        return True
    allowed = TIER_FEATURES.get(tier, [])
    if feature in allowed:
        return True
    if tier == "pro" and feature in TIER_FEATURES["free"]:
        return True
    return False


def get_user(telegram_id: int):
    doc = STORE['users'].get(str(telegram_id))
    return doc


def create_user(telegram_id: int, name: str, language: str):
    data = {
        "telegram_id": telegram_id,
        "name": name[:100],
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
        "parent_token": str(uuid.uuid4()),
        "joined": _now(),
        "last_question_date": _today(),
        "last_explanation": "",
        "chosen_subject": "math",
        "questions_this_week": 0,
        "week_start": _today(),
    }
    STORE['users'][str(telegram_id)] = data
    return data


def update_user(telegram_id: int, updates: dict):
    uid = str(telegram_id)
    if "tier" in updates:
        updates["tier"] = normalize_tier(updates["tier"])
    if uid not in STORE['users']:
        STORE['users'][uid] = {}
    STORE['users'][uid].update(updates)


def get_cached_content(key: str):
    return STORE['cached_content'].get(key)


def set_cached_content(key: str, value: dict):
    STORE['cached_content'][key] = value


def is_panic_mode():
    return False


def get_daily_tip():
    if not STORE["daily_tips"]:
        return None
    latest_key = sorted(STORE["daily_tips"].keys())[-1]
    return STORE["daily_tips"][latest_key].get("tip")


def get_panic_kit_questions() -> list[str]:
    return ["What is your next best step?", "Which formula applies?", "Can you explain the concept simply?"]


def check_and_increment_questions(telegram_id: int, tier: str, limit: int) -> bool:
    user = STORE['users'].setdefault(str(telegram_id), create_user(telegram_id, "Student", "en"))
    today = _today()
    if user.get("last_question_date") != today:
        user["questions_today"] = 0
        user["last_question_date"] = today
        user["study_minutes_today"] = 0
    if tier == "free" and user.get("questions_today", 0) >= limit:
        return False
    user["questions_today"] = user.get("questions_today", 0) + 1
    user["questions_total"] = user.get("questions_total", 0) + 1
    user["questions_this_week"] = user.get("questions_this_week", 0) + 1
    return True


def update_streak(telegram_id: int):
    user = STORE['users'].setdefault(str(telegram_id), create_user(telegram_id, "Student", "en"))
    today = _today()
    if user.get("last_active_date") == today:
        return {"streak": user.get("streak", 0), "freeze_earned": False}
    user["streak"] = user.get("streak", 0) + 1
    user["last_active_date"] = today
    return {"streak": user["streak"], "freeze_earned": False}


def record_answer(telegram_id: int, subject: str, correct: bool, topic: str = "General", question_data: dict | None = None):
    user = STORE['users'].setdefault(str(telegram_id), create_user(telegram_id, "Student", "en"))
    user.setdefault("score_by_subject", {})
    user.setdefault("subject_correct", {})
    user.setdefault("subject_wrong", {})
    user.setdefault("subject_attempts", {})
    user.setdefault("topic_performance", {})
    
    tp = user["topic_performance"].setdefault(subject, {}).setdefault(topic, {"correct": 0, "attempts": 0})
    
    user["score_by_subject"][subject] = user["score_by_subject"].get(subject, 0) + (1 if correct else 0)
    user["subject_correct"][subject] = user["subject_correct"].get(subject, 0) + (1 if correct else 0)
    user["subject_wrong"][subject] = user["subject_wrong"].get(subject, 0) + (0 if correct else 1)
    user["subject_attempts"][subject] = user["subject_attempts"].get(subject, 0) + 1
    
    tp["correct"] += (1 if correct else 0)
    tp["attempts"] += 1
    
    if correct:
        user["correct_total"] = user.get("correct_total", 0) + 1
    else:
        user["wrong_total"] = user.get("wrong_total", 0) + 1
        # Save detailed wrong question
        if question_data:
            STORE["wrong_questions"][str(uuid.uuid4())] = {
                "telegram_id": telegram_id,
                "subject": subject,
                "topic": topic,
                "question": question_data.get("question", ""),
                "options": question_data.get("options", {}),
                "answer": question_data.get("answer", ""),
                "explanation": question_data.get("explanation", ""),
                "timestamp": _now()
            }


def get_chunks_for_subject(subject: str, limit: int = 5) -> list[str]:
    return [c.get("text", "") for c in _get_collection_items("textbook_chunks") if c.get("subject") == subject][:limit]

def add_real_question(subject: str, question_data: dict) -> bool:
    question_data["subject"] = subject
    STORE['real_exam_questions'][str(uuid.uuid4())] = question_data
    return True

def get_random_real_question(subject: str) -> dict | None:
    questions = [q for q in _get_collection_items("real_exam_questions") if q.get("subject") == subject]
    import random
    if questions:
        return random.choice(questions)
    return None


def save_exam_result(telegram_id: int, subject: str, score: int, total: int, weak_topics: list):
    STORE['exam_results'][str(uuid.uuid4())] = {
        "telegram_id": telegram_id,
        "subject": subject,
        "score": score,
        "total": total,
        "percentage": round(score / total * 100, 1) if total else 0,
        "weak_topics": weak_topics,
        "taken_at": _now(),
    }


def get_exam_results(telegram_id: int, limit: int = 5) -> list[dict]:
    results = [d for d in _get_collection_items("exam_results") if d.get("telegram_id") == telegram_id]
    return results[-limit:]


def get_weak_subjects(telegram_id: int) -> dict:
    user = get_user(telegram_id) or {}
    attempts = user.get("subject_attempts", {}) or {}
    correct = user.get("subject_correct", {}) or {}
    result = {}
    for subj, total in attempts.items():
        c = correct.get(subj, 0)
        result[subj] = round(c / total * 100) if total else 0
    return result


def get_leaderboard(limit: int = 10) -> list[dict]:
    users = list(_get_collection_items("users"))
    users.sort(key=lambda d: d.get("correct_total", 0), reverse=True)
    return users[:limit]


def save_daily_tip(tip: str):
    today = _today()
    STORE['daily_tips'][today] = {"tip": tip, "date": today}


def clear_subject_notes_cache(subject: str) -> None:
    prefix = f"notes_{subject}_"
    to_delete = [key for key in STORE["cached_content"].keys() if key.startswith(prefix)]
    for key in to_delete:
        del STORE["cached_content"][key]


def get_cached_content(cache_key: str) -> dict | None:
    return STORE["cached_content"].get(cache_key)


def set_cached_content(cache_key: str, data: dict):
    STORE["cached_content"][cache_key] = data


def get_user_by_parent_token(token: str):
    for user in _get_collection_items("users"):
        if user.get("parent_token") == token:
            return user
    return None


def save_confession(telegram_id: int, topic: str):
    STORE['confessions'][str(uuid.uuid4())] = {"telegram_id": telegram_id, "topic": topic[:500], "created_at": _now()}


def create_battle(challenger_id: int, subject: str, question_data: dict) -> str:
    battle_id = str(uuid.uuid4())
    STORE['battles'][battle_id] = {
        "battle_id": battle_id,
        "challenger_id": challenger_id,
        "opponent_id": None,
        "subject": subject,
        "question": question_data.get("question", ""),
        "options": question_data.get("options", {}),
        "correct_answer": question_data.get("answer", ""),
        "explanation": question_data.get("explanation", ""),
        "status": "waiting",
        "created_at": _now(),
    }
    return battle_id


def get_battle(battle_id: str):
    return STORE['battles'].get(battle_id)


def join_battle(battle_id: str, opponent_id: int):
    battle = STORE['battles'].get(battle_id)
    if not battle:
        return None
    battle["opponent_id"] = opponent_id
    battle["status"] = "active"
    return battle


def submit_battle_answer(battle_id: str, user_id: int, answer: str, time_secs: float, is_correct: bool):
    battle = STORE['battles'].get(battle_id)
    if not battle:
        return {}
    if battle.get("challenger_id") == user_id:
        battle.update({"challenger_answer": answer, "challenger_time": time_secs, "challenger_correct": is_correct})
    else:
        battle.update({"opponent_answer": answer, "opponent_time": time_secs, "opponent_correct": is_correct})
    return battle


def finalize_battle(battle_id: str, winner_id: int | None, challenger_correct: bool, opponent_correct: bool):
    battle = STORE['battles'].get(battle_id)
    if battle:
        battle.update({"winner_id": winner_id, "challenger_correct": challenger_correct, "opponent_correct": opponent_correct, "status": "done", "finished_at": _now()})


def get_boss_fight_week():
    key = f"{date.today().year}_{date.today().isocalendar()[1]}"
    return STORE['boss_fights'].get(key)


def save_boss_fight(question: str, subject: str, model_answer: str | None = None, explanation: str | None = None):
    key = f"{date.today().year}_{date.today().isocalendar()[1]}"
    STORE['boss_fights'][key] = {
        "question": question,
        "subject": subject,
        "model_answer": model_answer,
        "explanation": explanation,
        "completers": []
    }


def complete_boss_fight(telegram_id: int):
    key = f"{date.today().year}_{date.today().isocalendar()[1]}"
    fight = STORE['boss_fights'].setdefault(key, {})
    fight.setdefault("completers", []).append(telegram_id)


def check_feature_rate_limit(telegram_id: int, feature: str, hours: int = 24) -> bool:
    return True


def user_telebirr_rate_limit_exceeded(telegram_id: int) -> bool:
    return False


def check_transaction_exists(tx_id: str) -> bool:
    return tx_id in STORE['payment_attempts']


def save_payment_attempt(
    telegram_id: int,
    username: str,
    tx_id: str,
    plan_requested: str,
    screenshot_url: str | None = None,
    status: str = "PENDING",
    **kwargs,
):
    STORE['payment_attempts'][tx_id] = {
        "telegram_id": telegram_id,
        "username": username,
        "transaction_id": tx_id,
        "plan_requested": plan_requested,
        "screenshot_url": screenshot_url,
        "status": str(status).upper(),
        **kwargs,
    }
    return True


def get_payment_attempt(tx_id: str):
    return STORE['payment_attempts'].get(tx_id)


def update_payment_attempt(tx_id: str, updates: dict) -> bool:
    payment = STORE['payment_attempts'].get(tx_id)
    if not payment:
        return False
    payment.update(updates)
    return True


def finalize_payment_attempt(tx_id: str, status: str = "APPROVED", **updates) -> bool:
    payment = STORE['payment_attempts'].get(tx_id)
    if payment:
        payment.update({"status": str(status).upper(), **updates})
        return True

    STORE['payment_attempts'][tx_id] = {
        "transaction_id": tx_id,
        "status": str(status).upper(),
        **updates,
    }
    return True


def approve_payment(tx_id: str) -> bool:
    payment = STORE['payment_attempts'].get(tx_id)
    if not payment or str(payment.get("status", "")).upper() != "PENDING":
        return False
    
    payment["status"] = "APPROVED"
    
    # Normalize plan name (pro_monthly -> pro)
    raw_plan = str(payment.get("plan_requested", "pro")).lower()
    tier = "max" if "max" in raw_plan else "pro"
    days = 365 if "yearly" in raw_plan else 30
    
    # Actually update the user in the stub store
    raw_id = payment.get("telegram_id")
    if raw_id:
        try:
            t_id = int(raw_id)
        except (ValueError, TypeError):
            t_id = raw_id
            
        update_user(t_id, {
            "tier": tier,
            "tier_updated_at": _now(),
            "subscription_expires_at": (datetime.utcnow() + timedelta(days=days)).isoformat()
        })
    return True


def reject_payment(tx_id: str) -> bool:
    payment = STORE['payment_attempts'].get(tx_id)
    if not payment:
        return False
    payment["status"] = "REJECTED"
    return True


def get_pending_payments() -> list[dict]:
    return [p for p in STORE['payment_attempts'].values() if str(p.get("status", "")).lower() == "pending"]


def get_feature_suggestions() -> list[dict]:
    return list(_get_collection_items("feature_suggestions"))


def save_feature_suggestion(telegram_id: int, username: str, text: str):
    STORE['feature_suggestions'][str(uuid.uuid4())] = {
        "telegram_id": telegram_id,
        "username": username,
        "suggestion": text,
        "submitted_at": _now(),
    }


def get_top_scorer_this_week() -> dict | None:
    users = list(_get_collection_items("users"))
    users.sort(key=lambda d: d.get("questions_this_week", 0), reverse=True)
    return users[0] if users else None


async def check_and_expire_subscriptions(application):
    """Stub version of the expiration checker."""
    import datetime
    from telegram.constants import ParseMode
    from keyboards import upgrade_keyboard
    
    now = datetime.utcnow().isoformat()
    for uid, user in STORE['users'].items():
        if user.get("tier") == "free":
            continue
            
        expiry = user.get("subscription_expires_at")
        if expiry and now > expiry:
            old_tier = user.get("tier", "pro").upper()
            user["tier"] = "free"
            user["tier_updated_at"] = now
            
            try:
                msg = (
                    f"⚠️ **Subscription Expired (Stub)**\n\n"
                    f"Your **{old_tier}** plan has ended. You have been moved back to the Free tier.\n\n"
                    f"Don't lose your momentum! Upgrade again to keep enjoying all features. 🚀"
                )
                await application.bot.send_message(
                    chat_id=int(uid),
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=upgrade_keyboard()
                )
            except Exception:
                pass

def get_wrong_questions(telegram_id: int, limit: int = 20) -> list[dict]:
    """Fetch the most recent wrong questions for a user."""
    return [q for q in STORE["wrong_questions"].values() if q.get("telegram_id") == telegram_id][-limit:]

# Lightweight placeholders for firestore helpers used by the codebase
firestore = type("firestore", (), {"Increment": Increment, "ArrayUnion": ArrayUnion, "Query": object})
