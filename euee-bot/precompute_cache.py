"""
precompute_cache.py — Pre-generate AI content and Broadcast to all users
"""
import asyncio
import sys
import db_supabase as db
import notes
from config import SUBJECTS, BOT_TOKEN
from telegram import Bot

# Fix Windows console emoji/Unicode output
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

async def broadcast_new_content(bot: Bot, subject_name: str):
    """Notify all registered users about new content."""
    users = db.db.collection("users").stream()
    count = 0
    for doc in users:
        user = doc.to_dict()
        tid = user.get("telegram_id")
        lang = user.get("language", "en")
        
        msg = (
            f"🚀 NEW CONTENT ALERT: {subject_name}!\n"
            f"Abebe has just finished analyzing the full textbook. "
            f"New interactive Study Notes and Flashcards are ready for you! 📚"
            if lang == "en" else
            f"🚀 አዲስ ትምህርት: {subject_name}!\n"
            f"አቤቤ ሙሉውን መጽሐፍ አጥንቶ ጨርሷል። "
            f"አዲስ ማስታወሻዎች እና ፍላሽ ካርዶች ተዘጋጅተዋል! 📚"
        )
        
        try:
            await bot.send_message(chat_id=tid, text=msg)
            count += 1
            await asyncio.sleep(0.05) # Avoid Telegram rate limits
        except Exception:
            continue
    print(f"  📢 Broadcasted to {count} users.")

async def precompute_all():
    print("🚀 Starting Precomputation with GEMINI engine...")
    bot = Bot(token=BOT_TOKEN)
    languages = ["en", "am"]
    
    for subj_code in SUBJECTS.keys():
        subj_name = SUBJECTS[subj_code].upper()
        print(f"\n📚 Processing: {subj_name}")
        
        for lang in languages:
            print(f"  🌐 Language: {lang}")
            
            print("    📝 Generating Study Notes...")
            await notes.generate_study_notes(subj_code, lang)
            
            print("    🃏 Generating Flashcards...")
            notes.generate_flashcards(subj_code, count=5, lang=lang)
            
            print("    📋 Generating Exam Tips...")
            notes.generate_exam_tips(subj_code, lang)
            
            print("    🎧 Generating Audio Lesson Script...")
            notes.generate_audio_script(subj_code, lang)
            
            print(f"  ✅ {lang.upper()} Done.")

        # Broadcast after each subject is fully precomputed
        print(f"  📣 Broadcasting {subj_name} update...")
        await broadcast_new_content(bot, subj_name)

    print("\n✨ ALL PRECOMPUTATION & BROADCAST COMPLETE!")

if __name__ == "__main__":
    asyncio.run(precompute_all())
