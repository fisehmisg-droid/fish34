"""
helpers.py — Utility functions (sanitization, radar chart, formatting)
"""
import re
import html
from datetime import date
from config import MAX_INPUT_CHARS, EUEE_EXAM_DATE, SUBJECTS


def sanitize_input(text: str) -> str:
    """Sanitize user input: strip, limit length, escape HTML."""
    if not text:
        return ""
    text = text.strip()
    text = text[:MAX_INPUT_CHARS]
    text = html.escape(text)
    # Remove any control characters
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text


def days_until_euee() -> int:
    """Days remaining until EUEE exam."""
    delta = EUEE_EXAM_DATE - date.today()
    return max(delta.days, 0)


def format_countdown(lang: str = "en") -> str:
    """Format the exam countdown message."""
    days = days_until_euee()
    if lang == "en":
        if days == 0:
            return "🚨 EUEE IS TODAY! You've got this! 💪"
        elif days <= 7:
            return f"🔴 PANIC MODE: Only {days} days until EUEE! 🔴"
        elif days <= 30:
            return f"⚠️ {days} days until EUEE. Time to get serious!"
        else:
            return f"📅 {days} days until EUEE. Keep grinding!"
    else:
        if days == 0:
            return "🚨 EUEE ዛሬ ነው! ትችላለህ! 💪"
        elif days <= 7:
            return f"🔴 ድንጋጤ ሁነታ: EUEE {days} ቀን ቀረ! 🔴"
        elif days <= 30:
            return f"⚠️ EUEE {days} ቀን ቀረ። ጊዜው አሁን ነው!"
        else:
            return f"📅 EUEE {days} ቀን ቀረ። ቀጥል!"


def build_radar_chart(weak_subjects: dict) -> str:
    """Build a text-art radar chart showing weak/strong subjects."""
    if not weak_subjects:
        return "📊 No data yet — answer more questions!"

    lines = ["🎯 ═══ WEAK POINT RADAR ═══ 🎯", ""]
    sorted_subjects = sorted(weak_subjects.items(), key=lambda x: x[1])

    for subj, pct in sorted_subjects:
        name = SUBJECTS.get(subj, subj).ljust(12)
        bar_len = pct // 5  # scale 0–100 to 0–20 chars
        empty = 20 - bar_len

        if pct >= 80:
            emoji = "🟢"
            bar_char = "█"
        elif pct >= 60:
            emoji = "🟡"
            bar_char = "▓"
        elif pct >= 40:
            emoji = "🟠"
            bar_char = "▒"
        else:
            emoji = "🔴"
            bar_char = "░"

        bar = bar_char * bar_len + "·" * empty
        lines.append(f"{emoji} {name} [{bar}] {pct}%")

    lines.append("")
    lines.append("🔴 = Needs work  🟡 = OK  🟢 = Strong")
    lines.append("═" * 38)
    return "\n".join(lines)


def format_leaderboard(entries: list[dict], lang: str = "en") -> str:
    """Format the leaderboard for display."""
    if not entries:
        return "🏆 Leaderboard is empty — be the first!" if lang == "en" \
            else "🏆 ሰንጠረዥ ባዶ ነው — የመጀመሪያ ሁን!"

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    title = "🏆 ═══ NATIONAL LEADERBOARD ═══ 🏆" if lang == "en" \
        else "🏆 ═══ ብሔራዊ ሰንጠረዥ ═══ 🏆"
    lines = [title, ""]

    for i, entry in enumerate(entries[:10]):
        medal = medals[i] if i < len(medals) else f"#{i+1}"
        name = entry.get("name", "Student")[:15]
        correct = entry.get("correct_total", 0)
        streak = entry.get("streak", 0)
        badges = " ".join(entry.get("badges", [])[:3])
        lines.append(f"{medal} {name} — ✅{correct} | 🔥{streak}d {badges}")

    lines.append("")
    lines.append("═" * 36)
    return "\n".join(lines)


def format_progress(user: dict, lang: str = "en") -> str:
    """Format student progress summary."""
    name = user.get("name", "Student")
    streak = user.get("streak", 0)
    correct = user.get("correct_total", 0)
    wrong = user.get("wrong_total", 0)
    total = correct + wrong
    pct = round(correct / total * 100, 1) if total > 0 else 0
    exams = user.get("exams_taken", 0)
    tier = user.get("tier", "free").upper()
    freezes = user.get("streak_freezes", 0)
    badges = " ".join(user.get("badges", [])) or "None yet"
    study_hrs = round(user.get("study_minutes_total", 0) / 60, 1)

    countdown = format_countdown(lang)

    if lang == "en":
        return (
            f"📊 ═══ {name}'s Progress ═══ 📊\n\n"
            f"🔥 Streak: {streak} days\n"
            f"❄️ Streak Freezes: {freezes}\n"
            f"📚 Total Questions: {total}\n"
            f"✅ Correct: {correct} ({pct}%)\n"
            f"❌ Wrong: {wrong}\n"
            f"📝 Exams Taken: {exams}\n"
            f"⏱️ Study Hours: {study_hrs}h\n"
            f"🎖️ Badges: {badges}\n"
            f"👑 Tier: {tier}\n\n"
            f"{countdown}"
        )
    else:
        return (
            f"📊 ═══ {name} እድገት ═══ 📊\n\n"
            f"🔥 ስትሪክ: {streak} ቀን\n"
            f"❄️ ስትሪክ ጥበቃ: {freezes}\n"
            f"📚 ጠቅላላ ጥያቄዎች: {total}\n"
            f"✅ ትክክል: {correct} ({pct}%)\n"
            f"❌ ስህተት: {wrong}\n"
            f"📝 ፈተናዎች: {exams}\n"
            f"⏱️ ሰዓት: {study_hrs}h\n"
            f"🎖️ ባጅ: {badges}\n"
            f"👑 ደረጃ: {tier}\n\n"
            f"{countdown}"
        )


def subject_from_button(text: str) -> str | None:
    """Extract subject code from button press text."""
    mapping = {
        "math": ["math", "📐"],
        "physics": ["physics", "⚛️"],
        "chemistry": ["chemistry", "🧪"],
        "biology": ["biology", "🧬"],
        "english": ["english", "📖"],
        "civics": ["civics", "🏛️"],
        "history": ["history", "📜"],
        "geography": ["geography", "🌍"],
        "economics": ["economics", "💰"],
        "agriculture": ["agriculture", "🌾"],
        "it": ["it", "💻"],
    }
    text_lower = text.lower().strip()
    for code, keywords in mapping.items():
        for kw in keywords:
            if kw in text_lower:
                return code
    return None


def generate_download_signature(user_id: int) -> str:
    """Generate an HMAC signature for a user_id using the ADMIN_TOKEN (Section 3.3/4.2 Fix)."""
    from config import ADMIN_TOKEN
    import hmac
    import hashlib
    return hmac.new(
        key=ADMIN_TOKEN.encode('utf-8'),
        msg=str(user_id).encode('utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()


def verify_download_signature(user_id: int, signature: str) -> bool:
    """Verify that the provided signature matches the user_id."""
    from config import ADMIN_TOKEN
    import hmac
    import hashlib
    expected = generate_download_signature(user_id)
    return hmac.compare_digest(expected, signature)
