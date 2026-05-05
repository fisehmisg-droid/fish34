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
# Use Supabase database (new default)
import db_supabase as db
sys.modules["db"] = db
import ai
from handlers import (
    start, set_language, menu_handler, choose_subject, handle_question,
    button_callback, handle_confession, cmd_progress, cmd_leaderboard,
    cmd_radar, cmd_predict, error_handler, handle_boss_answer, handle_telebirr_tx, handle_telebirr_photo,
    handle_suggestion, AWAITING_TELEBIRR_TX, AWAITING_TELEBIRR_PHOTO, cmd_id, cmd_demo_upgrade,
    cmd_admin, cmd_manual_upgrade, handle_upgrade_button, cmd_admin_build, cmd_invite, cmd_review_sheet, cmd_plan,
    safe_handler,
)
from helpers import format_countdown

MENU_REGEX = (
    r"(?i)(Practice|Random Challenge|Mock Exam|Audio|Flashcard|Memory Trick|Progress|Leaderboard|"
    r"Battle|Confession|Boss|Predictor|Upgrade|Plan|Parent|Exam Tips|Weak Radar|Model Exam|Study Notes|E-Book|Textbooks|Invite Friend|Review Sheet|/menu|"
    r"ልምምድ|ለማዳ|የዘፈቀደ ጥያቄ|የሙከራ ፈተና|ሙሉ ፈተና|የኦዲዮ ትምህርት|ኦዲዮ|"
    r"ፍላሽ|የማስታወሻ ዘዴ|እድገቴ|ሰንጠረዥ|የውድድር ሁነታ|ውድድር|የምስጢር ሳጥን|ምስጢር|የቦስ ውጊያ|ቦስ|"
    r"ውጤት ትንቢት|ትንቢት|አሳድግ|የወላጅ ሊንክ|ወላጅ|የፈተና ምክሮች|ፈተና ምክር|የድክመት ራዳር|ድክመት ራዳር|ሞዴል ፈተና|ማስታወሻ|ማስታወቂያ|ኢ-መጽሐፍት|መጽሐፍት|ጓደኛ ይጋብዙ|የክለሳ ወረቀት|ተመለስ|"
    r"🎯|🎲|📝|📚|🎧|🗂️|🧠|📊|🏆|⚔️|🤫|👾|🔮|💡|📡|👑|👨‍👩‍👦|📒|🤝|🔙)"
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Validate env on startup ──────────────────────────────────────────────────
validate_env()


# ── Scheduled jobs ────────────────────────────────────────────────────────────
async def _batch_stream_users(batch_size=500):
    """FIX: Yield users in batches to avoid OOM when streaming 50k+ users."""
    # Use Supabase-compatible streaming
    count = 0
    for doc in db.db.collection("users").stream():
        yield doc
        count += 1
        if count >= batch_size:
            await asyncio.sleep(0)  # yield control back to event loop
            count = 0


async def daily_reminder(app):
    """Send daily study reminder + streak + countdown + Voice of the Topper tip."""
    # FIX: Process users in batches; never load entire collection into memory.
    # FIX: Wrap sync AI call in run_blocking so the scheduler never blocks the event loop.
    tip = None
    count = 0
    async for doc in _batch_stream_users(batch_size=500):
        user = doc.to_dict()
        tid = user.get("telegram_id")
        lang = user.get("language", "en")
        streak = user.get("streak", 0)

        # Generate tip once
        if tip is None:
            tip = await run_blocking(ai.generate_topper_tip, lang)
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
            count += 1
        except Exception:
            pass  # user may have blocked bot
    logger.info(f"📅 Daily reminder sent to {count} users.")


async def panic_reminder(app):
    """Send extra reminders only during the final panic-mode window."""
    if db.is_panic_mode():
        await daily_reminder(app)


async def weekly_parent_report(app):
    """Send Parent Shock Report every Sunday."""
    count = 0
    async for doc in _batch_stream_users(batch_size=500):
        user = doc.to_dict()
        token = user.get("parent_token")
        if not token:
            continue
        name = user.get("name", "Student")
        try:
            # FIX: Wrap sync AI call in run_blocking so the scheduler never blocks.
            report = await run_blocking(ai.generate_parent_shock_report, user, name)
            db.db.collection("parent_reports").add({
                "parent_token": token,
                "report": report,
                "week": datetime.now().isocalendar()[1],
                "created_at": db._now(),
            })
            count += 1
        except Exception:
            logger.exception("Parent report generation failed for user %s", user.get("telegram_id"))
    logger.info(f"📊 Parent reports generated for {count} users.")


async def reset_weekly_counters(app):
    """Reset weekly question counters every Monday."""
    count = 0
    async for doc in _batch_stream_users(batch_size=500):
        try:
            db.update_user(doc.to_dict().get("telegram_id"), {
                "questions_this_week": 0,
                "week_start": db._today(),
            })
            count += 1
        except Exception:
            logger.exception("Failed to reset weekly counters for user")
    logger.info(f"🔄 Weekly counters reset for {count} users.")


# ── Build application ────────────────────────────────────────────────────────
async def post_init(application):
    # FIX: Removed embedded uvicorn server start — Railway already runs server.py as the single web entry point.
    # Starting a second server here caused port-conflict crashes on deploy.
    from gemini_file_api import _ensure_worker
    await _ensure_worker()

    # FIX: Scheduler runs only in standalone mode (polling). When server.py is the entry point,
    # scheduler is started there to avoid duplicate jobs.
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("WEBHOOK_URL"):
        logger.info("🔧 Railway/webhook mode detected — scheduler will be started by server.py.")
        return

    scheduler = AsyncIOScheduler()
    scheduler.add_job(daily_reminder, "cron", hour=4, minute=0, args=[application])
    scheduler.add_job(panic_reminder, "cron", hour=9, minute=0, args=[application], id="panic_noon")
    scheduler.add_job(panic_reminder, "cron", hour=17, minute=0, args=[application], id="panic_evening")
    scheduler.add_job(weekly_parent_report, "cron", day_of_week="sun", hour=15, minute=0, args=[application])
    scheduler.add_job(reset_weekly_counters, "cron", day_of_week="mon", hour=21, minute=0, args=[application])
    scheduler.add_job(db.check_and_expire_subscriptions, "interval", hours=1, args=[application])
    scheduler.start()
    logger.info("📅 Scheduler started (cron reminders attached).")


def build_app():
    # Fix Windows console emoji/Unicode output
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # FIX: [global handler safety] — [ensure all user-facing handlers are exception-safe]
    def _guard(handler_func):
        return safe_handler(handler_func)

    def _safe(handler_func):
        return safe_handler(handler_func)

    # Conversation handler for registration + subject selection + Q&A
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", _safe(start)),
            CommandHandler("menu", _safe(start)),
            CallbackQueryHandler(_safe(handle_upgrade_button), pattern="^upgrade_"),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.Regex(MENU_REGEX),
                _safe(menu_handler)
            )
        ],
        states={
            CHOOSE_LANGUAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _safe(set_language))
            ],
            CHOOSE_SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _safe(choose_subject))
            ],
            ASKING_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _guard(handle_question))
            ],
            CONFESSION_BOX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _guard(handle_confession))
            ],
            BOSS_FIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _guard(handle_boss_answer))
            ],
            AWAITING_TELEBIRR_TX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _guard(handle_telebirr_tx))
            ],
            AWAITING_TELEBIRR_PHOTO: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, _guard(handle_telebirr_photo))
            ],
            AWAITING_FEATURE_SUGGESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _guard(handle_suggestion))
            ],
        },
        fallbacks=[CommandHandler("start", _safe(start)), CommandHandler("menu", _safe(start))],
        per_user=True,
        per_chat=True,
    )

    # Route menu text before state-specific text handlers so buttons work from any state.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(MENU_REGEX), _safe(menu_handler)), group=-1)

    # Add a global message logger
    async def log_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            print(f"📩 [MSG] From {update.effective_user.first_name} ({update.effective_user.id}): {update.message.text}")
        elif update.callback_query:
            print(f"🔘 [BTN] From {update.effective_user.first_name}: {update.callback_query.data}")

    app.add_handler(MessageHandler(filters.ALL, log_messages), group=-1)

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(_safe(button_callback)))
    # Ensure these commands work even if stuck in a state
    app.add_handler(CommandHandler("start", _safe(start)))
    app.add_handler(CommandHandler("menu", _safe(start)))
    app.add_handler(CommandHandler("progress", _safe(cmd_progress)))
    app.add_handler(CommandHandler("leaderboard", _safe(cmd_leaderboard)))
    app.add_handler(CommandHandler("radar", _safe(cmd_radar)))
    app.add_handler(CommandHandler("predict", _safe(cmd_predict)))
    app.add_handler(CommandHandler("id", _safe(cmd_id)))
    app.add_handler(CommandHandler("demo_upgrade", _safe(cmd_demo_upgrade)))
    app.add_handler(CommandHandler("admin", _safe(cmd_admin)))
    app.add_handler(CommandHandler("manualupgrade", _safe(cmd_manual_upgrade)))
    app.add_handler(CommandHandler("admin_build", _safe(cmd_admin_build)))
    app.add_handler(CommandHandler("invite", _safe(cmd_invite)))
    app.add_handler(CommandHandler("review", _safe(cmd_review_sheet)))
    app.add_handler(CommandHandler("plan", _safe(cmd_plan)))
    app.add_handler(CommandHandler("status", _safe(cmd_plan)))

    app.add_error_handler(error_handler)
    return app

def main():
    app = build_app()
    print("🎓 ═══════════════════════════════════════")
    print("🎓  ABEBE EUEE BOT — READY!")
    print("🎓 ═══════════════════════════════════════")

    # Python 3.14 no longer guarantees a default event loop in the main thread.
    # PTB's polling/webhook runners still expect one to be present.
    asyncio.set_event_loop(asyncio.new_event_loop())

    # FIX: SIGTERM handling for zero-downtime Railway redeploys.
    import signal
    def _handle_sigterm(signum, frame):
        logger.info("Received SIGTERM — shutting down gracefully...")
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    # FIX: Force polling mode when DEV_MODE is enabled
    dev_mode = os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")
    if dev_mode:
        print("🔧 DEV_MODE enabled - forcing POLLING mode")
        app.run_polling(drop_pending_updates=True)
        return
    
    # FIX: On Railway (or any container), webhook mode is mandatory.
    # Polling keeps an open connection and will be killed by the platform.
    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    is_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_NAME"))
    
    # Detect placeholder/fake webhook URLs and fallback to polling
    is_valid_webhook = webhook_url and not any(placeholder in webhook_url.lower() for placeholder in [
        "your-domain", "example.com", "localhost", "127.0.0.1", "placeholder", "change-me"
    ])

    if webhook_url and is_valid_webhook:
        port = int(os.getenv("PORT", "8080"))
        print(f"🚀 Running in WEBHOOK mode on port {port}. URL: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            secret_token=os.getenv("WEBHOOK_SECRET")
        )
    else:
        # Allow polling for local development
        print("📡 Running in POLLING mode...")
        if is_railway:
            logger.warning("RAILWAY_ENVIRONMENT detected but WEBHOOK_URL is missing. Using polling (not recommended for production).")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
