"""Database layer for the Abebe EUEE bot.

This module keeps the existing Firestore-shaped API used by the bot, but stores
all documents in a SQL backend instead. PostgreSQL is preferred in production.
SQLite is used as a local fallback when DATABASE_URL is not provided.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from config import STREAK_FREEZE_EVERY, TIER_FEATURES, TIER_LIMITS

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> str:
    return date.today().isoformat()


def _now() -> datetime:
    return _utcnow()


def to_serializable(data: Any):
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
    if tier == "pro" and feature in TIER_FEATURES["free"]:
        return True
    return False


class Increment:
    def __init__(self, n: int | float):
        self.n = n


class ArrayUnion:
    def __init__(self, arr: Iterable[Any]):
        self.arr = list(arr)


class DocumentSnapshot:
    def __init__(self, collection_path: str, doc_id: str, data: dict | None):
        self._collection_path = collection_path
        self.id = doc_id
        self._data = copy.deepcopy(data) if data is not None else None

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        return copy.deepcopy(self._data)


def _field_get(data: dict, field: str):
    parts = field.split(".")
    current = data
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _apply_increment(existing: Any, delta: Any):
    base = existing if isinstance(existing, (int, float)) else 0
    return base + delta


def _apply_array_union(existing: Any, values: Iterable[Any]):
    current = list(existing) if isinstance(existing, list) else []
    for item in values:
        if item not in current:
            current.append(item)
    return current


def _normalize_update_value(value: Any):
    cls_name = value.__class__.__name__
    if cls_name.lower().endswith("servertimestamp") or "sentinel" in cls_name.lower():
        return _now()
    if hasattr(value, "n") and cls_name.lower().endswith("increment"):
        return ("__increment__", value.n)
    if hasattr(value, "arr") and cls_name.lower().endswith("arrayunion"):
        return ("__array_union__", list(value.arr))
    return value


def _parse_backend_row(raw_data: Any) -> dict:
    if raw_data is None:
        return {}
    if isinstance(raw_data, dict):
        return copy.deepcopy(raw_data)
    if isinstance(raw_data, str):
        try:
            return json.loads(raw_data)
        except Exception:
            return {}
    return dict(raw_data)


class Increment:
    def __init__(self, n):
        self.n = n


class ArrayUnion:
    def __init__(self, arr):
        self.arr = arr


@dataclass
class DocumentSnapshot:
    data: dict | None
    id: str

    @property
    def exists(self):
        return self.data is not None

    def to_dict(self):
        return _deep_copy_document(self.data)


class _BaseBackend:
    def ensure_schema(self) -> None:
        raise NotImplementedError

    def get_document(self, collection_path: str, doc_id: str) -> dict | None:
        raise NotImplementedError

    def list_documents(self, collection_path: str) -> list[dict]:
        raise NotImplementedError

    def upsert_document(self, collection_path: str, doc_id: str, data: dict) -> None:
        raise NotImplementedError

    def delete_document(self, collection_path: str, doc_id: str) -> None:
        raise NotImplementedError


class _SQLiteBackend(_BaseBackend):
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    collection_path TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (collection_path, doc_id)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection_path)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents(updated_at)"
            )
            self._conn.commit()

    def get_document(self, collection_path: str, doc_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM documents WHERE collection_path = ? AND doc_id = ?",
                (collection_path, doc_id),
            ).fetchone()
        if not row:
            return None
        return _parse_backend_row(row["data"])

    def list_documents(self, collection_path: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc_id, data, created_at, updated_at FROM documents WHERE collection_path = ?",
                (collection_path,),
            ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "doc_id": row["doc_id"],
                    "data": _parse_backend_row(row["data"]),
                    "created_at": _coerce_datetime(row["created_at"]),
                    "updated_at": _coerce_datetime(row["updated_at"]),
                }
            )
        return result

    def upsert_document(self, collection_path: str, doc_id: str, data: dict) -> None:
        payload = json.dumps(to_serializable(data), default=_json_default, ensure_ascii=False)
        now = _utcnow().isoformat()
        with self._lock:
            existing = self._conn.execute(
                "SELECT created_at FROM documents WHERE collection_path = ? AND doc_id = ?",
                (collection_path, doc_id),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            self._conn.execute(
                """
                INSERT INTO documents (collection_path, doc_id, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(collection_path, doc_id)
                DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
                """,
                (collection_path, doc_id, payload, created_at, now),
            )
            self._conn.commit()

    def delete_document(self, collection_path: str, doc_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM documents WHERE collection_path = ? AND doc_id = ?",
                (collection_path, doc_id),
            )
            self._conn.commit()


class _PostgresBackend(_BaseBackend):
    def __init__(self, url: str):
        try:
            from psycopg_pool import ConnectionPool
        except Exception as exc:
            raise RuntimeError("psycopg_pool is required when DATABASE_URL is set") from exc

        self._pool = ConnectionPool(conninfo=url, min_size=1, max_size=5, open=True)

    def ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS documents (
                        collection_path TEXT NOT NULL,
                        doc_id TEXT NOT NULL,
                        data JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (collection_path, doc_id)
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection_path)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents(updated_at DESC)")
            conn.commit()

    def get_document(self, collection_path: str, doc_id: str) -> dict | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM documents WHERE collection_path = %s AND doc_id = %s",
                    (collection_path, doc_id),
                )
                row = cur.fetchone()
        if not row:
            return None
        return _parse_backend_row(row[0])

    def list_documents(self, collection_path: str) -> list[dict]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT doc_id, data, created_at, updated_at FROM documents WHERE collection_path = %s",
                    (collection_path,),
                )
                rows = cur.fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "doc_id": row[0],
                    "data": _parse_backend_row(row[1]),
                    "created_at": row[2],
                    "updated_at": row[3],
                }
            )
        return result

    def upsert_document(self, collection_path: str, doc_id: str, data: dict) -> None:
        payload = json.dumps(to_serializable(data), default=_json_default, ensure_ascii=False)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (collection_path, doc_id, data, created_at, updated_at)
                    VALUES (%s, %s, %s::jsonb, NOW(), NOW())
                    ON CONFLICT (collection_path, doc_id)
                    DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                    """,
                    (collection_path, doc_id, payload),
                )
            conn.commit()

    def delete_document(self, collection_path: str, doc_id: str) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM documents WHERE collection_path = %s AND doc_id = %s",
                    (collection_path, doc_id),
                )
            conn.commit()


def _build_backend() -> _BaseBackend:
    if DATABASE_URL:
        logger.info("Using PostgreSQL backend for bot data.")
        backend = _PostgresBackend(DATABASE_URL)
    else:
        if not DEV_MODE:
            raise RuntimeError(
                "DATABASE_URL is required in production. Set it to your Railway PostgreSQL connection string."
            )
        logger.info("DATABASE_URL missing in DEV_MODE — using local SQLite fallback.")
        backend = _SQLiteBackend(SQLITE_PATH)

    backend.ensure_schema()
    return backend


_BACKEND = _build_backend()


class DocumentRef:
    def __init__(self, collection_path: str, doc_id: str):
        self.collection_path = collection_path
        self.id = str(doc_id)

    def get(self) -> DocumentSnapshot:
        data = _BACKEND.get_document(self.collection_path, self.id)
        return DocumentSnapshot(data, self.id)

    def set(self, data: dict, merge: bool = False):
        if merge:
            current = self.get().to_dict() or {}
            current.update(_deep_copy_document(data) or {})
            data = current
        _BACKEND.upsert_document(self.collection_path, self.id, _deep_copy_document(data) or {})

    def update(self, updates: dict):
        current = self.get().to_dict() or {}
        for field, raw_value in updates.items():
            value = _normalize_update_value(raw_value)
            if isinstance(value, tuple) and value[0] == "__increment__":
                existing = _get_nested_value(current, field)
                _set_nested_value(current, field, _apply_increment(existing, value[1]))
            elif isinstance(value, tuple) and value[0] == "__array_union__":
                existing = _get_nested_value(current, field)
                _set_nested_value(current, field, _apply_array_union(existing, value[1]))
            else:
                _set_nested_value(current, field, value)
        _BACKEND.upsert_document(self.collection_path, self.id, current)

    def delete(self):
        _BACKEND.delete_document(self.collection_path, self.id)

    def collection(self, name: str):
        return CollectionRef(f"{self.collection_path}/{self.id}/{name}")


class Query:
    def __init__(self, collection_path: str, filters=None, order=None, limit_n=None, start_after_id=None):
        self.collection_path = collection_path
        self.filters = list(filters or [])
        self.order = order
        self.limit_n = limit_n
        self.start_after_id = start_after_id

    def where(self, field, op, value):
        return Query(self.collection_path, self.filters + [(field, op, value)], self.order, self.limit_n, self.start_after_id)

    def order_by(self, field, direction=None):
        return Query(self.collection_path, self.filters, (field, direction), self.limit_n, self.start_after_id)

    def limit(self, n):
        return Query(self.collection_path, self.filters, self.order, n, self.start_after_id)

    def start_after(self, snapshot):
        cursor = snapshot.id if hasattr(snapshot, "id") else str(snapshot)
        return Query(self.collection_path, self.filters, self.order, self.limit_n, cursor)

    def _matches(self, data: dict) -> bool:
        for field, op, value in self.filters:
            current = _get_nested_value(data, field)
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
        docs = _BACKEND.list_documents(self.collection_path)
        items = []
        for row in docs:
            data = row["data"]
            if self._matches(data):
                items.append(DocumentSnapshot(data, row["doc_id"]))

        if self.order:
            field, direction = self.order
            reverse = str(direction).lower().endswith("desc")
            items.sort(key=lambda snap: (_get_nested_value(snap.to_dict() or {}, field), snap.id), reverse=reverse)
        else:
            items.sort(key=lambda snap: snap.id)

        if self.start_after_id:
            passed = False
            filtered = []
            for snap in items:
                if passed:
                    filtered.append(snap)
                elif snap.id == self.start_after_id:
                    passed = True
            items = filtered

        if self.limit_n is not None:
            items = items[: self.limit_n]
        return iter(items)


class CollectionRef(Query):
    def __init__(self, collection_path: str):
        super().__init__(collection_path)

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = str(uuid.uuid4())
        return DocumentRef(self.collection_path, str(doc_id))

    def add(self, data):
        doc = self.document()
        doc.set(data)
        return doc, None

    def collection(self, name: str):
        return CollectionRef(f"{self.collection_path}/{name}")


class DocumentDB:
    def collection(self, name: str):
        return CollectionRef(name)


db = DocumentDB()


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
    if tier == "pro" and feature in TIER_FEATURES["free"]:
        return True
    return False


def _tier_change_log(telegram_id: int, old_tier: str, new_tier: str, reason: str | None = None):
    db.collection("tier_change_log").add(
        {
            "telegram_id": telegram_id,
            "old_tier": old_tier,
            "new_tier": new_tier,
            "reason": reason,
            "changed_at": _now(),
        }
    )


def get_user(telegram_id: int, use_cache: bool = True) -> dict | None:
    doc = db.collection("users").document(str(telegram_id)).get()
    return doc.to_dict() if doc.exists else None


def create_user(telegram_id: int, name: str | None, language: str) -> dict:
    safe_name = (name or "Student")[:100]
    parent_token = secrets.token_urlsafe(16)
    data = {
        "telegram_id": telegram_id,
        "name": safe_name,
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
    ref = db.collection("users").document(str(telegram_id))
    current = ref.get().to_dict() or {}
    if "tier" in updates:
        updates = dict(updates)
        updates["tier"] = normalize_tier(updates["tier"])
        old_tier = normalize_tier(current.get("tier"))
        new_tier = normalize_tier(updates["tier"])
        if old_tier != new_tier:
            logger.info("TIER_CHANGE user=%s old=%s new=%s", telegram_id, old_tier, new_tier)
            _tier_change_log(telegram_id, old_tier, new_tier)
    current.update({k: _normalize_update_value(v) for k, v in updates.items()})
    ref.set(current)


def upgrade_user_tier(telegram_id: int, tier: str):
    tier = normalize_tier(tier)
    current = get_user(telegram_id) or {}
    old_tier = normalize_tier(current.get("tier"))
    current["tier"] = tier
    current["tier_updated_at"] = _now()
    current["subscription_active"] = tier != "free"
    if tier == "free":
        current["subscription_expires_at"] = None
    update_user(telegram_id, current)
    if old_tier != tier:
        _tier_change_log(telegram_id, old_tier, tier, reason="manual upgrade")


def get_user_tier(telegram_id: int) -> str:
    user = get_user(telegram_id, use_cache=False)
    return normalize_tier(user.get("tier") if user else None)


def is_subscription_active(telegram_id: int) -> bool:
    user = get_user(telegram_id, use_cache=False)
    if not user:
        return False
    tier = normalize_tier(user.get("tier"))
    if tier == "free":
        return True
    if user.get("subscription_active") is False:
        return False
    expires_at = user.get("subscription_expires_at")
    if not expires_at:
        return True
    expires_at = _coerce_datetime(expires_at)
    if isinstance(expires_at, _dt.datetime):
        return _utcnow() < expires_at
    return True


def is_premium(telegram_id: int) -> bool:
    return get_user_tier(telegram_id) in ("pro", "max") and is_subscription_active(telegram_id)


def get_or_create_user(telegram_id: int, name: str, language: str = "en") -> dict:
    user = get_user(telegram_id)
    if user is None:
        user = create_user(telegram_id, name, language)
    return user


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
    ref = db.collection("users").document(str(telegram_id))
    user = ref.get().to_dict() or {}
    today = _today()
    if user.get("last_question_date") != today:
        user["questions_today"] = 0
        user["last_question_date"] = today
    if tier == "free" and user.get("questions_today", 0) >= limit:
        return False
    user["questions_today"] = user.get("questions_today", 0) + 1
    user["questions_total"] = user.get("questions_total", 0) + 1
    user["questions_this_week"] = user.get("questions_this_week", 0) + 1
    ref.set(user)
    return True


def update_streak(telegram_id: int) -> dict:
    ref = db.collection("users").document(str(telegram_id))
    user = ref.get().to_dict() or {}
    today = _today()
    yesterday = (_utcnow() - _dt.timedelta(days=1)).date().isoformat()
    if user.get("last_active_date") == today:
        return {"streak": user.get("streak", 0), "freeze_earned": False}
    current_streak = user.get("streak", 0)
    freezes = user.get("streak_freezes", 0)
    last_active = user.get("last_active_date", "")
    if last_active == yesterday or last_active == "":
        new_streak = current_streak + 1
    else:
        if freezes > 0:
            user["streak_freezes"] = freezes - 1
            user["last_active_date"] = today
            ref.set(user)
            return {"streak": current_streak, "freeze_used": True, "freeze_earned": False}
        new_streak = 1
    freeze_earned = new_streak > 0 and new_streak % STREAK_FREEZE_EVERY == 0
    user["streak"] = new_streak
    user["last_active_date"] = today
    if freeze_earned:
        user["streak_freezes"] = freezes + 1
    ref.set(user)
    return {"streak": new_streak, "freeze_earned": freeze_earned}


def record_answer(telegram_id: int, subject: str, correct: bool, topic: str = "General", question_data: dict | None = None):
    ref = db.collection("users").document(str(telegram_id))
    user = ref.get().to_dict() or {}
    safe_topic = (topic or "General").replace(".", "-")
    score_by_subject = user.get("score_by_subject", {}) or {}
    subject_correct = user.get("subject_correct", {}) or {}
    subject_wrong = user.get("subject_wrong", {}) or {}
    subject_attempts = user.get("subject_attempts", {}) or {}
    topic_perf = user.get("topic_performance", {}) or {}

    score_by_subject[subject] = score_by_subject.get(subject, 0) + (1 if correct else 0)
    subject_correct[subject] = subject_correct.get(subject, 0) + (1 if correct else 0)
    subject_wrong[subject] = subject_wrong.get(subject, 0) + (0 if correct else 1)
    subject_attempts[subject] = subject_attempts.get(subject, 0) + 1

    subject_topic = topic_perf.setdefault(subject, {})
    topic_row = subject_topic.setdefault(safe_topic, {"correct": 0, "attempts": 0})
    topic_row["correct"] += 1 if correct else 0
    topic_row["attempts"] += 1

    user["score_by_subject"] = score_by_subject
    user["subject_correct"] = subject_correct
    user["subject_wrong"] = subject_wrong
    user["subject_attempts"] = subject_attempts
    user["topic_performance"] = topic_perf
    user["correct_total"] = user.get("correct_total", 0) + (1 if correct else 0)
    user["wrong_total"] = user.get("wrong_total", 0) + (0 if correct else 1)
    user["study_minutes_today"] = user.get("study_minutes_today", 0) + 2
    user["study_minutes_total"] = user.get("study_minutes_total", 0) + 2

    ref.set(user)

    if not correct and question_data:
        db.collection("users").document(str(telegram_id)).collection("wrong_questions").add(
            {
                "subject": subject,
                "topic": topic,
                "question": question_data.get("question", ""),
                "options": question_data.get("options", {}),
                "answer": question_data.get("answer", ""),
                "explanation": question_data.get("explanation", ""),
                "timestamp": _now(),
            }
        )


def get_leaderboard(limit: int = 10) -> list[dict]:
    docs = db.collection("users").stream()
    users = [doc.to_dict() for doc in docs]
    users.sort(key=lambda d: d.get("correct_total", 0), reverse=True)
    return users[:limit]


def get_chunks_for_subject(subject: str, limit: int = 5) -> list[str]:
    docs = db.collection("textbook_chunks").where("subject", "==", subject).limit(limit).stream()
    return [d.to_dict().get("text", "") for d in docs]


def save_exam_result(telegram_id: int, subject: str, score: int, total: int, weak_topics: list):
    db.collection("exam_results").add(
        {
            "telegram_id": telegram_id,
            "subject": subject,
            "score": score,
            "total": total,
            "percentage": round(score / total * 100, 1) if total else 0,
            "weak_topics": weak_topics,
            "taken_at": _now(),
        }
    )
    user_ref = db.collection("users").document(str(telegram_id))
    user = user_ref.get().to_dict() or {}
    user["exams_taken"] = user.get("exams_taken", 0) + 1
    user_ref.set(user)


def get_exam_results(telegram_id: int, limit: int = 5) -> list[dict]:
    docs = db.collection("exam_results").where("telegram_id", "==", telegram_id).stream()
    results = [d.to_dict() for d in docs]
    results.sort(key=lambda d: str(d.get("taken_at", "")), reverse=True)
    return results[:limit]


def save_confession(telegram_id: int, topic: str):
    db.collection("confessions").add(
        {
            "telegram_id": telegram_id,
            "topic": topic[:500],
            "created_at": _now(),
        }
    )


def create_battle(challenger_id: int, subject: str, question_data: dict) -> str:
    doc_ref = db.collection("battles").document()
    doc_ref.set(
        {
            "battle_id": doc_ref.id,
            "challenger_id": challenger_id,
            "opponent_id": None,
            "subject": subject,
            "question": question_data.get("question", ""),
            "options": question_data.get("options", {}),
            "correct_answer": question_data.get("answer", ""),
            "explanation": question_data.get("explanation", ""),
            "status": "waiting",
            "challenger_answer": None,
            "opponent_answer": None,
            "challenger_correct": None,
            "opponent_correct": None,
            "challenger_time": None,
            "opponent_time": None,
            "winner_id": None,
            "created_at": _now(),
        }
    )
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
    battle["opponent_id"] = opponent_id
    battle["status"] = "active"
    ref.set(battle)
    return battle


def submit_battle_answer(battle_id: str, user_id: int, answer: str, time_secs: float, is_correct: bool) -> dict:
    ref = db.collection("battles").document(battle_id)
    battle = ref.get().to_dict() or {}
    if not battle:
        return {}
    if battle.get("challenger_id") == user_id:
        battle["challenger_answer"] = answer
        battle["challenger_time"] = time_secs
        battle["challenger_correct"] = is_correct
    else:
        battle["opponent_answer"] = answer
        battle["opponent_time"] = time_secs
        battle["opponent_correct"] = is_correct
    battle["status"] = "active"
    ref.set(battle)
    return battle


def finalize_battle(battle_id: str, winner_id: int | None, challenger_correct: bool, opponent_correct: bool):
    ref = db.collection("battles").document(battle_id)
    battle = ref.get().to_dict() or {}
    battle.update(
        {
            "winner_id": winner_id,
            "challenger_correct": challenger_correct,
            "opponent_correct": opponent_correct,
            "status": "done",
            "finished_at": _now(),
        }
    )
    ref.set(battle)


def get_boss_fight_week() -> dict | None:
    week = _utcnow().isocalendar()[1]
    year = _utcnow().year
    doc = db.collection("boss_fights").document(f"{year}_{week}").get()
    return doc.to_dict() if doc.exists else None


def save_boss_fight(question: str, subject: str, model_answer: str | None = None, explanation: str | None = None):
    week = _utcnow().isocalendar()[1]
    year = _utcnow().year
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
    week = _utcnow().isocalendar()[1]
    year = _utcnow().year
    ref = db.collection("boss_fights").document(f"{year}_{week}")
    boss = ref.get().to_dict() or {}
    completers = set(boss.get("completers", []) or [])
    completers.add(telegram_id)
    boss["completers"] = list(completers)
    ref.set(boss)
    user_ref = db.collection("users").document(str(telegram_id))
    user = user_ref.get().to_dict() or {}
    badges = user.get("badges", []) or []
    if "🏆 Champion" not in badges:
        badges.append("🏆 Champion")
    user["badges"] = badges
    user_ref.set(user)


def get_user_by_parent_token(token: str) -> dict | None:
    docs = db.collection("users").where("parent_token", "==", token).limit(1).stream()
    for doc in docs:
        return doc.to_dict()
    return None


def get_top_scorer_this_week() -> dict | None:
    docs = db.collection("users").stream()
    users = [doc.to_dict() for doc in docs]
    users.sort(key=lambda d: d.get("questions_this_week", 0), reverse=True)
    return users[0] if users else None


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


def save_daily_tip(tip: str):
    today = _today()
    db.collection("daily_tips").document(today).set({"tip": tip, "date": today})


def get_daily_tip() -> str | None:
    today = _today()
    doc = db.collection("daily_tips").document(today).get()
    data = doc.to_dict() if doc.exists else None
    return data.get("tip") if data else None


def get_panic_kit_questions() -> list[str]:
    docs = db.collection("panic_kit").order_by("rank").limit(50).stream()
    return [d.to_dict().get("question", "") for d in docs]


def is_panic_mode() -> bool:
    from config import EUEE_EXAM_DATE

    delta = (EUEE_EXAM_DATE - _utcnow().date()).days
    return 0 <= delta <= 7


def get_cached_content(cache_key: str) -> dict | None:
    doc = db.collection("content_cache").document(cache_key).get()
    return doc.to_dict() if doc.exists else None


def set_cached_content(cache_key: str, data: dict):
    db.collection("content_cache").document(cache_key).set(data)


def clear_subject_notes_cache(subject: str) -> None:
    for lang_code in ("en", "am"):
        for key in (f"notes_{subject}_{lang_code}", f"audio_script_{subject}_{lang_code}"):
            db.collection("content_cache").document(key).delete()


def user_telebirr_rate_limit_exceeded(telegram_id: int) -> bool:
    docs = db.collection("payment_attempts").where("telegram_id", "==", telegram_id).stream()
    attempts = [doc.to_dict() for doc in docs]
    attempts.sort(key=lambda x: str(x.get("submitted_at", "")), reverse=True)
    if len(attempts) < 5:
        return False
    last_attempt = attempts[4]
    submitted_at = _coerce_datetime(last_attempt.get("submitted_at"))
    if isinstance(submitted_at, _dt.datetime):
        hour_ago = _utcnow() - _dt.timedelta(hours=1)
        return submitted_at > hour_ago
    return False


def check_transaction_exists(tx_id: str) -> bool:
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
    ref = db.collection("payment_attempts").document(tx_id)
    doc = ref.get()
    if not doc.exists:
        return False
    data = doc.to_dict() or {}
    data.update({k: _normalize_update_value(v) for k, v in updates.items()})
    ref.set(data)
    return True


def finalize_payment_attempt(tx_id: str, *, status: str = "APPROVED", **updates) -> bool:
    ref = db.collection("payment_attempts").document(tx_id)
    doc = ref.get()
    payload = {"status": str(status).upper(), **updates}
    if doc.exists:
        data = doc.to_dict() or {}
        data.update({k: _normalize_update_value(v) for k, v in payload.items()})
        ref.set(data)
    else:
        ref.set({"transaction_id": tx_id, "submitted_at": _now(), **payload})
    return True


def get_pending_payments() -> list[dict]:
    docs = db.collection("payment_attempts").where("status", "==", "PENDING").stream()
    results = [to_serializable(doc.to_dict()) for doc in docs]
    results.sort(key=lambda x: str(x.get("submitted_at", "")), reverse=True)
    return results


def approve_payment(tx_id: str) -> bool:
    data = get_payment_attempt(tx_id)
    if not data or str(data.get("status", "")).upper() != "PENDING":
        return False

    raw_plan = str(data.get("plan_requested", "pro")).lower().strip()
    tier = "max" if "max" in raw_plan else "pro"
    days = 365 if "yearly" in raw_plan else 30
    expires_at = _utcnow() + _dt.timedelta(days=days)

    try:
        t_id = str(data["telegram_id"]).strip()
    except (KeyError, ValueError, TypeError) as exc:
        logger.error("approve_payment: could not resolve telegram_id for tx %s: %s", tx_id, exc)
        return False

    user_ref = db.collection("users").document(str(t_id))
    if not user_ref.get().exists:
        logger.error("approve_payment: user document '%s' does not exist — cannot upgrade.", t_id)
        return False

    user = user_ref.get().to_dict() or {}
    old_tier = normalize_tier(user.get("tier"))
    user["tier"] = tier
    user["tier_updated_at"] = _now()
    user["subscription_expires_at"] = expires_at
    user["subscription_active"] = True
    user_ref.set(user)
    _tier_change_log(int(t_id), old_tier, tier, reason="payment approved")
    finalize_payment_attempt(tx_id, status="APPROVED")

    updated_doc = user_ref.get().to_dict() or {}
    if normalize_tier(updated_doc.get("tier")) != normalize_tier(tier):
        logger.error("approve_payment: tier write verification FAILED for user %s!", t_id)
        return False

    logger.info("✅ approve_payment: Success for user %s (Tier: %s)", t_id, tier)
    return True


async def check_and_expire_subscriptions(application):
    """Mark subscriptions inactive without reverting the stored tier."""
    now = _utcnow()
    try:
        query = db.collection("users").where("tier", "!=", "free").limit(500)
        last_doc = None
        processed = 0
        expired = 0
        while True:
            if last_doc:
                query = query.start_after(last_doc)
            docs = list(query.stream())
            if not docs:
                break
            for doc in docs:
                user_data = doc.to_dict() or {}
                user_id = doc.id
                old_tier = user_data.get("tier", "free")
                expires_at = user_data.get("subscription_expires_at")
                tier_updated = user_data.get("tier_updated_at")
                expiry_dt = None
                if expires_at:
                    expiry_dt = _coerce_datetime(expires_at)
                elif tier_updated:
                    updated_dt = _coerce_datetime(tier_updated)
                    if isinstance(updated_dt, _dt.datetime):
                        expiry_dt = updated_dt + _dt.timedelta(days=30)
                if not isinstance(expiry_dt, _dt.datetime):
                    continue
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=_dt.timezone.utc)
                if now < expiry_dt:
                    continue

                user_data["subscription_active"] = False
                user_data["subscription_expired_at"] = _now()
                db.collection("users").document(user_id).set(user_data)
                logger.info("User %s subscription expired (tier=%s), marked inactive.", user_id, old_tier)
                expired += 1

                lang = user_data.get("language", "en")
                old_tier_upper = old_tier.upper()
                try:
                    from keyboards import upgrade_keyboard

                    if lang == "en":
                        msg = (
                            f"⌛ **Your {old_tier_upper} Subscription has Expired**\n\n"
                            f"Your access to {old_tier_upper} features has ended. Renew your plan to continue using premium tools. 🚀"
                        )
                    else:
                        msg = (
                            f"⌛ **የ{old_tier_upper} ደንበኝነት ምዝገባዎ አብቅቷል**\n\n"
                            f"የ{old_tier_upper} አገልግሎቶች አጠቃቀምዎ አብቅቷል። አሁኑኑ ያሳድጉ እንዲቀጥሉ። 🚀"
                        )
                    await application.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown", reply_markup=upgrade_keyboard())
                except Exception as exc:
                    logger.error("Failed to notify user %s of expiry: %s", user_id, exc)
            processed += len(docs)
            last_doc = docs[-1]
            await asyncio.sleep(0)
        logger.info("check_and_expire_subscriptions: processed=%s expired=%s", processed, expired)
    except Exception as exc:
        logger.error("check_and_expire_subscriptions query failed: %s", exc)


def save_feature_suggestion(telegram_id: int, username: str, text: str):
    db.collection("feature_suggestions").add(
        {
            "telegram_id": telegram_id,
            "username": username,
            "suggestion": text,
            "submitted_at": _now(),
        }
    )


def get_feature_suggestions() -> list[dict]:
    docs = db.collection("feature_suggestions").stream()
    results = [to_serializable(doc.to_dict()) for doc in docs]
    results.sort(key=lambda x: str(x.get("submitted_at", "")), reverse=True)
    return results


def reject_payment(tx_id: str) -> bool:
    doc = get_payment_attempt(tx_id)
    if not doc:
        return False
    finalize_payment_attempt(tx_id, status="REJECTED")
    return True


def check_feature_rate_limit(telegram_id: int, feature_name: str, hours: int = 24) -> bool:
    ref = db.collection("users").document(str(telegram_id))
    user = ref.get().to_dict()
    if not user:
        return False
    last_used = user.get(f"last_{feature_name}_at")
    if last_used:
        now = _utcnow()
        last_dt = _coerce_datetime(last_used)
        if isinstance(last_dt, _dt.datetime):
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=_dt.timezone.utc)
            if now - last_dt < _dt.timedelta(hours=hours):
                return False
    user[f"last_{feature_name}_at"] = _now()
    ref.set(user)
    return True


def get_random_real_question(subject: str) -> dict | None:
    try:
        docs = db.collection("real_exam_questions").where("subject", "==", subject).limit(20).stream()
        results = [doc.to_dict() for doc in docs]
        if not results:
            return None
        import random

        return random.choice(results)
    except Exception as exc:
        logger.error("Error fetching real question: %s", exc)
        return None


def add_real_question(subject: str, question_data: dict) -> bool:
    try:
        doc_ref = db.collection("real_exam_questions").document()
        question_data = dict(question_data)
        question_data["subject"] = subject
        question_data["created_at"] = _now()
        doc_ref.set(question_data)
        return True
    except Exception as exc:
        logger.error("Error adding real question: %s", exc)
        return False


def get_wrong_questions(telegram_id: int, limit: int = 20) -> list[dict]:
    try:
        docs = (
            db.collection("users")
            .document(str(telegram_id))
            .collection("wrong_questions")
            .order_by("timestamp", direction="DESC")
            .limit(limit)
            .stream()
        )
        return [doc.to_dict() for doc in docs]
    except Exception as exc:
        logger.error("Error fetching wrong questions: %s", exc)
        return []
