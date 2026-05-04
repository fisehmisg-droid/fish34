"""
main.py — EUEE Abebe Bot Entry Point
=====================================
Wires all handlers, schedulers, and starts polling.
Run: python main.py
"""
import logging
import sys
import asyncio
from datetime import datetime
import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler, filters,
    ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (
    BOT_TOKEN, CHOOSE_LANGUAGE, CHOOSE_SUBJECT, ASKING_QUESTION, 
    CONFESSION_BOX, BOSS_FIGHT, AWAITING_FEATURE_SUGGESTION, 
    validate_env
)
if os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes"):
    import db_stub as db
    sys.modules["db"] = db
else:
    import db
import ai
from handlers import (
    start, set_language, menu_handler, choose_subject, handle_question,
    button_callback, handle_confession, cmd_progress, cmd_leaderboard,
    cmd_radar, cmd_predict, error_handler, handle_boss_answer, handle_telebirr_tx, handle_telebirr_photo,
    handle_suggestion, AWAITING_TELEBIRR_TX, AWAITING_TELEBIRR_PHOTO, cmd_id, cmd_demo_upgrade,
    cmd_admin, handle_upgrade_button, cmd_admin_build, cmd_invite, cmd_review_sheet
)
from helpers import format_countdown

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Validate env on startup ──────────────────────────────────────────────────
validate_env()


# ── Scheduled jobs ────────────────────────────────────────────────────────────
async def daily_reminder(app):
    """Send daily study reminder + streak + countdown + Voice of the Topper tip."""
    users = db.db.collection("users").stream()
    tip = None
    for doc in users:
        user = doc.to_dict()
        tid = user.get("telegram_id")
        lang = user.get("language", "en")
        streak = user.get("streak", 0)

        # Generate tip once
        if tip is None:
            tip = ai.generate_topper_tip(lang)
            db.save_daily_tip(tip)

        countdown = format_countdown(lang)
        if lang == "en":
            msg = (
                f"🌅 Good morning, {user.get('name', 'Student')}!\n\n"
                f"🔥 Streak: {streak} days — don't break it!\n"
                f"{countdown}\n\n"
                f"💡 Voice of the Topper:\n\"{tip}\"\n\n"
                "Press /start to study now! 📚"
            )
        else:
            msg = (
                f"🌅 እንደምን አደርክ {user.get('name', 'ተማሪ')}!\n\n"
                f"🔥 ስትሪክ: {streak} ቀን — አታቋርጥ!\n"
                f"{countdown}\n\n"
                f"💡 ከምርጥ ተማሪ:\n\"{tip}\"\n\n"
                "ለመማር /start ጫን 📚"
            )

        # Check panic mode (7 days before EUEE)
        if db.is_panic_mode():
            panic_msg = ("\n\n🚨 PANIC MODE ACTIVATED 🚨\n"
                        "EUEE is in less than 7 days!\n"
                        "Abebe is sending you 3 reminders today!\n"
                        "Use /start → Practice to study NOW!"
                        if lang == "en" else
                        "\n\n🚨 ድንጋጤ ሁነታ 🚨\n"
                        "EUEE 7 ቀን ቀረ!\n"
                        "አቤቤ ዛሬ 3 ጊዜ ያስታውስሃል!\n"
                        "/start ጫን!")
            msg += panic_msg

        try:
            await app.bot.send_message(chat_id=tid, text=msg)
        except Exception:
            pass  # user may have blocked bot


async def panic_reminder(app):
    """Send extra reminders only during the final panic-mode window."""
    if db.is_panic_mode():
        await daily_reminder(app)


async def weekly_parent_report(app):
    """Send Parent Shock Report every Sunday."""
    users = db.db.collection("users").stream()
    for doc in users:
        user = doc.to_dict()
        token = user.get("parent_token")
        if not token:
            continue
        name = user.get("name", "Student")
        report = ai.generate_parent_shock_report(user, name)
        # Store report for web access
        db.db.collection("parent_reports").add({
            "parent_token": token,
            "report": report,
            "week": datetime.now().isocalendar()[1],
            "created_at": db._now(),
        })


async def reset_weekly_counters(app):
    """Reset weekly question counters every Monday."""
    users = db.db.collection("users").stream()
    for doc in users:
        db.update_user(doc.to_dict().get("telegram_id"), {
            "questions_this_week": 0,
            "week_start": db._today(),
        })


# ── Build application ────────────────────────────────────────────────────────
async def post_init(application):
    # Pre-warm the Gemini File API async queue worker so it is ready
    # before the first user request triggers a PDF processing job.
    from gemini_file_api import _ensure_worker
    await _ensure_worker()

    # Start the web server (FastAPI) in the background
    import uvicorn
    from server import app as web_app
    import os

    async def run_web_server():
        try:
            config = uvicorn.Config(web_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
        except SystemExit:
            logger.error("🚫 Web server failed to start (Port 8080 is busy). The Telegram Bot will continue running without the web dashboard.")
        except Exception as e:
            logger.error(f"🌐 Web server error: {e}")

    asyncio.create_task(run_web_server())
    logger.info("🌐 Web Server task initialized.")

    # AsyncIOScheduler requires a running event loop — start jobs here, not in main().
    scheduler = AsyncIOScheduler()
    scheduler.add_job(daily_reminder, "cron", hour=4, minute=0, args=[application])
    scheduler.add_job(panic_reminder, "cron", hour=9, minute=0, args=[application], id="panic_noon")
    scheduler.add_job(panic_reminder, "cron", hour=17, minute=0, args=[application], id="panic_evening")
    scheduler.add_job(weekly_parent_report, "cron", day_of_week="sun", hour=15, minute=0, args=[application])
    scheduler.add_job(reset_weekly_counters, "cron", day_of_week="mon", hour=21, minute=0, args=[application])
    scheduler.add_job(db.check_and_expire_subscriptions, "interval", hours=1, args=[application])
    scheduler.start()
    logger.info("📅 Scheduler started (cron reminders attached).")


def main():
    # Fix Windows console emoji/Unicode output
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Conversation handler for registration + subject selection + Q&A
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("menu", start),
            CallbackQueryHandler(handle_upgrade_button, pattern="^upgrade_"),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.Regex(
                    r"(?i)(Practice|Random Challenge|Mock Exam|Audio|Flashcard|Memory Trick|Progress|Leaderboard|"
                    r"Battle|Confession|Boss|Predictor|Upgrade|Parent|Exam Tips|Weak Radar|Model Exam|Study Notes|E-Book|Textbooks|Invite Friend|Review Sheet|/menu|"
                    r"ልምምድ|ለማዳ|የዘፈቀደ ጥያቄ|የሙከራ ፈተና|ሙሉ ፈተና|የኦዲዮ ትምህርት|ኦዲዮ|"
                    r"ፍላሽ|የማስታወሻ ዘዴ|እድገቴ|ሰንጠረዥ|የውድድር ሁነታ|ውድድር|የምስጢር ሳጥን|ምስጢር|የቦስ ውጊያ|ቦስ|"
                    r"ውጤት ትንቢት|ትንቢት|አሳድግ|የወላጅ ሊንክ|ወላጅ|የፈተና ምክሮች|ፈተና ምክር|የድክመት ራዳር|ድክመት ራዳር|ሞዴል ፈተና|ማስታወሻ|ማስታወቂያ|ኢ-መጽሐፍት|መጽሐፍት|ጓደኛ ይጋብዙ|የክለሳ ወረቀት|ተመለስ|"
                    r"🎯|🎲|📝|📚|🎧|🗂️|🧠|📊|🏆|⚔️|🤫|👾|🔮|💡|📡|👑|👨‍👩‍👦|📒|🤝|🔙)"
                ),
                menu_handler
            )
        ],
        states={
            CHOOSE_LANGUAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_language)
            ],
            CHOOSE_SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_subject)
            ],
            ASKING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question)
            ],
            CONFESSION_BOX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession)
            ],
            BOSS_FIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_boss_answer)
            ],
            AWAITING_TELEBIRR_TX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telebirr_tx)
            ],
            AWAITING_TELEBIRR_PHOTO: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_telebirr_photo)
            ],
            AWAITING_FEATURE_SUGGESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_suggestion)
            ],
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("menu", start)],
        per_user=True,
        per_chat=True,
    )

    # Add a global message logger
    async def log_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            print(f"📩 [MSG] From {update.effective_user.first_name} ({update.effective_user.id}): {update.message.text}")
        elif update.callback_query:
            print(f"🔘 [BTN] From {update.effective_user.first_name}: {update.callback_query.data}")

    app.add_handler(MessageHandler(filters.ALL, log_messages), group=-1)

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_callback))
    # Ensure these commands work even if stuck in a state
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("progress", cmd_progress))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("radar", cmd_radar))
    app.add_handler(CommandHandler("predict", cmd_predict))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("demo_upgrade", cmd_demo_upgrade))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("admin_build", cmd_admin_build))
    app.add_handler(CommandHandler("invite", cmd_invite))
    app.add_handler(CommandHandler("review", cmd_review_sheet))

    # Menu text handler (catches all main menu button presses)

    # Error handler

    app.add_error_handler(error_handler)

    print("🎓 ═══════════════════════════════════════")
    print("🎓  ABEBE EUEE BOT — RUNNING!")
    print("🎓  Your AI tutor is ready to help!")
    print("🎓 ═══════════════════════════════════════")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
