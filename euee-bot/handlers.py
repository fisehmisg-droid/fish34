"""Telegram bot handlers for Abebe."""

from __future__ import annotations

import asyncio
from functools import wraps
import logging
import os
import sys
import time

logger = logging.getLogger(__name__)


# FIX: Global safe-handler wrapper — catches ANY unhandled exception in a handler,
# logs full traceback, and sends the user a friendly message. Never crashes the process.
def safe_handler(func):
    @wraps(func)
    async def _wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(update, ctx, *args, **kwargs)
        except Exception as exc:
            import traceback

            # Log full traceback locally
            tb = traceback.format_exc()
            logger.error("Unhandled exception in %s: %s", func.__name__, exc, exc_info=True)

            # Notify the user with a friendly message
            try:
                if update and update.effective_message:
                    await update.effective_message.reply_text("Something went wrong, please try again.")
                elif update and update.callback_query:
                    await update.callback_query.answer("Something went wrong, please try again.", show_alert=False)
            except Exception:
                pass

            # Send traceback to configured admins for faster debugging (truncate to safe size)
            try:
                from config import ADMIN_IDS
                admin_ids = ADMIN_IDS if isinstance(ADMIN_IDS, list) else [ADMIN_IDS]
                if admin_ids:
                    notif = (
                        f"⚠️ Unhandled exception in handler `{func.__name__}`\n"
                        f"User: `{getattr(update.effective_user, 'id', 'N/A')}`\n"
                        f"Error: {str(exc)}\n\n```")
                    # Truncate traceback to 3500 chars to avoid Telegram limits
                    notif += tb[:3500] + "\n```"
                    for aid in admin_ids:
                        try:
                            if aid and aid > 0:
                                await ctx.bot.send_message(chat_id=aid, text=notif, parse_mode="Markdown")
                        except Exception:
                            pass
            except Exception:
                # If admin notification fails, continue silently
                pass

            # Clear processing flag so user is not stuck
            if ctx and hasattr(ctx, "user_data") and ctx.user_data is not None:
                ctx.user_data["is_processing"] = False
    return _wrapper

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, ConversationHandler
# Removed Firebase dependency - using Supabase PostgreSQL

from async_util import run_blocking

import ai
import db_supabase as db
sys.modules["db"] = db
import keyboards as kb
import notes
from review_pdf import generate_personalized_review_pdf
from helpers import *
from config import (
    ALLOW_DEMO_UPGRADE,
    ASKING_QUESTION,
    BASE_WEB_URL,
    BOSS_FIGHT,
    CHAPA_SECRET_KEY,
    CHOOSE_LANGUAGE,
    CHOOSE_SUBJECT,
    CONFESSION_BOX,
    SUBJECTS,
    TIER_LIMITS,
    ADMIN_ID,
    ADMIN_ID_2,
    ADMIN_IDS,
    TELEBIRR_NUMBER,
    AWAITING_FEATURE_SUGGESTION,
)

from payments import validate_telebirr_tx_id, is_valid_image
# State definitions for ConversationHandler (add to existing state constants visually)
AWAITING_TELEBIRR_TX = 100
AWAITING_TELEBIRR_PHOTO = 101




def _sync_qna_pipeline(
    telegram_id: int, tier: str, limit: int, question: str, subject: str, lang: str
) -> str | None:
    """Runs Firestore + RAG + Gemini/Groq off the asyncio loop."""
    # Check question limit
    if not db.check_and_increment_questions(telegram_id, tier, limit):
        return None
    
    # Get chunks for context
    chunks = db.get_chunks_for_subject(subject, limit=3)
    if not chunks:
        chunks = [notes._get_source_material(subject, char_limit=4_000)]
    
    # Generate AI response
    response = ai.ask_abebe(question, subject, lang, context_chunks=chunks)
    
    # Update user data
    db.update_user(telegram_id, {"last_explanation": response[:1000]})
    db.update_streak(telegram_id)
    return response


def _is_amharic_choice(choice: str) -> bool:
    return "አማርኛ" in choice or "Amharic" in choice


def _subject_name(subject: str) -> str:
    return SUBJECTS.get(subject, subject.title())


def _main_menu_text(lang: str, name: str, streak_info: dict | None = None) -> str:
    streak_info = streak_info or {}
    streak = streak_info.get("streak", 0)
    if lang == "en":
        parts = [f"Welcome back {name}! Streak: {streak} day(s)."]
        if streak_info.get("freeze_used"):
            parts.append("A streak freeze protected your progress today.")
        if streak_info.get("freeze_earned"):
            parts.append("You just earned a new streak freeze.")
        parts.append("Choose what you want to do next from the menu below.")
        return "\n".join(parts)

    parts = [f"እንኳን ደህና መጣህ {name}! ስትሪክ: {streak} ቀን."]
    if streak_info.get("freeze_used"):
        parts.append("የስትሪክ ጥበቃ ዛሬ ተጠቅመሃል።")
    if streak_info.get("freeze_earned"):
        parts.append("አዲስ የስትሪክ ጥበቃ አግኝተሃል።")
    parts.append("ከታች ያለውን ምናሌ ተጠቀም።")
    return "\n".join(parts)


def _format_question(q: dict, prefix: str | None = None) -> str:
    lines = []
    if prefix:
        lines.append(prefix)
        lines.append("")
    lines.append(q.get("question", "Question not ready."))
    options = q.get("options", {})
    for key in ["A", "B", "C", "D"]:
        if key in options:
            lines.append(f"{key}. {options[key]}")
    return "\n".join(lines)


def _battle_payload_from_record(battle: dict) -> dict:
    return {
        "question": battle.get("question", ""),
        "options": battle.get("options", {}) or {},
        "answer": battle.get("correct_answer", ""),
        "explanation": battle.get("explanation", ""),
    }


def _clear_exam_state(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ["exam_active", "exam_total", "exam_score", "exam_current", "exam_start", "exam_subject"]:
        ctx.user_data.pop(key, None)


def _clear_battle_state(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ["active_battle", "battle_start"]:
        ctx.user_data.pop(key, None)


async def _open_pending_battle(update: Update, ctx: ContextTypes.DEFAULT_TYPE, battle_id: str) -> int:
    user = db.get_user(update.effective_user.id)
    if not user:
        return CHOOSE_LANGUAGE

    battle = db.join_battle(battle_id, update.effective_user.id)
    if not battle:
        await update.message.reply_text("That battle invite is no longer available.")
        return ConversationHandler.END

    if battle.get("challenger_id") == update.effective_user.id and not battle.get("opponent_id"):
        await update.message.reply_text("This is your own battle invite. Share it with a friend to begin.")
        return ConversationHandler.END

    q = _battle_payload_from_record(battle)
    ctx.user_data["active_battle"] = battle_id
    ctx.user_data["battle_start"] = time.time()
    ctx.user_data["current_q"] = q
    await update.message.reply_text(
        _format_question(q, "Battle joined. Answer using the buttons below."),
        reply_markup=kb.mcq_keyboard(q.get("options", {})),
    )
    return ConversationHandler.END


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pending_battle = None
    if ctx.args:
        first_arg = ctx.args[0].strip()
        if first_arg.startswith("battle_"):
            pending_battle = first_arg.replace("battle_", "", 1)
            ctx.user_data["pending_battle_id"] = pending_battle

    user = update.effective_user
    existing = db.get_user(user.id)
    if existing:
        lang = existing.get("language", "en")
        streak_info = await run_blocking(db.update_streak, user.id)
        await update.message.reply_text(
            _main_menu_text(lang, user.first_name, streak_info),
            reply_markup=kb.main_menu_keyboard(lang),
        )
        if pending_battle:
            return await _open_pending_battle(update, ctx, pending_battle)
        return ConversationHandler.END

    await update.message.reply_text(
        "Welcome. Choose your language to get started:",
        reply_markup=kb.lang_keyboard(),
    )
    return CHOOSE_LANGUAGE


async def set_language(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    choice = update.message.text or ""
    lang = "am" if _is_amharic_choice(choice) else "en"
    await run_blocking(db.create_user, user.id, user.first_name, lang)

    welcome = (
        "Language set to English.\n\n"
        "I am Abebe, your EUEE study partner. Use the menu below to practice, revise, and track your progress."
        if lang == "en"
        else "ቋንቋ አማርኛ ሆኗል።\n\nእኔ አቤቤ ነኝ፣ የEUEE የጥናት አጋርህ። ከታች ያለውን ምናሌ ተጠቀም።"
    )
    await update.message.reply_text(welcome, reply_markup=kb.main_menu_keyboard(lang))

    pending_battle = ctx.user_data.pop("pending_battle_id", None)
    if pending_battle:
        return await _open_pending_battle(update, ctx, pending_battle)
    return ConversationHandler.END


async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return ConversationHandler.END

    lang = user.get("language", "en")
    # FIX: Check subscription status - if expired, treat as free tier but don't block free features
    effective_tier = db.normalize_tier(user.get("tier"))
    if effective_tier in ("pro", "max") and not db.is_subscription_active(update.effective_user.id):
        # Subscription expired - user keeps their tier label but loses premium access
        # They can still use free features (practice limited, leaderboard, confessions, exam tips)
        effective_tier = "free"

    if "Practice" in text or "ለማዳ" in text:
        ctx.user_data["awaiting_subject"] = True
        ctx.user_data["notes_mode"] = "practice"
        await update.message.reply_text("Pick a subject:", reply_markup=kb.subject_keyboard(lang))
        return CHOOSE_SUBJECT

    if "Mock Exam" in text or "ሙሉ ፈተና" in text:
        # Pass 3.6/4.1 Hardening: ensure even mock exams have access logic
        if not db.has_access(effective_tier, "practice_unlimited"):
            # Check daily limit for free users
            if db.check_questions_limit_reached(update.effective_user.id, "free"):
                 await update.message.reply_text("You have reached your daily free limit for Mock Exams. Upgrade for unlimited access!")
                 await cmd_upgrade(update, ctx)
                 return ConversationHandler.END
                 
        ctx.user_data["notes_mode"] = "mock_exam"
        ctx.user_data["awaiting_subject"] = True
        await update.message.reply_text("Pick a subject for your mock exam:", reply_markup=kb.subject_keyboard(lang))
        return CHOOSE_SUBJECT

    if "E-Book" in text or "Textbooks" in text or "መጽሐፍት" in text or "ኢ-መጽሐፍት" in text:
        if not db.has_access(effective_tier, "textbooks"):
            await update.message.reply_text("Textbooks and E-books are for Pro and Max members.")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        await cmd_textbooks(update, ctx)
        return ConversationHandler.END

    if "Memory Trick" in text or "የማስታወሻ ዘዴ" in text:
        if not db.has_access(effective_tier, "mnemonic"):
            await update.message.reply_text("Memory tricks are for Pro and Max members.")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        ctx.user_data["notes_mode"] = "memory_trick"
        await update.message.reply_text("Pick a subject for Memory Tricks:", reply_markup=kb.subject_keyboard(lang))
        return CHOOSE_SUBJECT

    if "Study Notes" in text or "ማስታወሻ" in text or "ማስታወቂያ" in text:
        if not db.has_access(effective_tier, "notes"):
            await update.message.reply_text("Study notes are for Pro and Max members.")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        ctx.user_data["notes_mode"] = "notes"
        ctx.user_data["awaiting_subject"] = True
        await update.message.reply_text("Pick a subject for notes:", reply_markup=kb.subject_keyboard(lang))
        return CHOOSE_SUBJECT

    if "Model Exam" in text or "ሞዴል ፈተና" in text:
        if not db.has_access(effective_tier, "model_exam_5"):
            await update.message.reply_text("Model Exams are for Pro and Max members.")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        ctx.user_data["notes_mode"] = "model_exam"
        ctx.user_data["awaiting_subject"] = True
        await update.message.reply_text("Pick a subject for your Model Exam (100 Questions):", reply_markup=kb.subject_keyboard(lang))
        return CHOOSE_SUBJECT

    if "Audio" in text or "ኦዲዮ" in text:
        if not db.has_access(effective_tier, "audio"):
            await update.message.reply_text("Audio lessons are for Pro and Max members.")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        ctx.user_data["notes_mode"] = "audio"
        ctx.user_data["awaiting_subject"] = True
        await update.message.reply_text("Pick a subject for audio:", reply_markup=kb.subject_keyboard(lang))
        return CHOOSE_SUBJECT

    if "Flashcard" in text or "ፍላሽ" in text:
        if not db.has_access(effective_tier, "flashcards"):
            await update.message.reply_text("Flashcards are for Max members.")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        ctx.user_data["notes_mode"] = "flashcards"
        ctx.user_data["awaiting_subject"] = True
        await update.message.reply_text("Pick a subject for flashcards:", reply_markup=kb.subject_keyboard(lang))
        return CHOOSE_SUBJECT

    # Duplicate Memory block removed to prevent routing collisions (Finding #4.1 Fix)

    if "Progress" in text or "እድገቴ" in text:
        await cmd_progress(update, ctx)
        return ConversationHandler.END

    if "Leaderboard" in text or "ሰንጠረዥ" in text:
        await cmd_leaderboard(update, ctx)
        return ConversationHandler.END

    if "Battle" in text or "ውድድር" in text:
        await cmd_battle(update, ctx)
        return ASKING_QUESTION

    if "Confession" in text or "ምስጢር" in text:
        return await cmd_confession(update, ctx)

    if "Boss" in text or "ቦስ" in text:
        if not db.has_access(effective_tier, "boss_fight"):
            await update.message.reply_text("Friday Boss Fight is for Max members only! Upgrade to challenge the ultimate EUEE questions. 👾")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        return await cmd_boss_fight(update, ctx)

    if "Predictor" in text or "ትንቢት" in text:
        if not db.has_access(effective_tier, "score_predictor"):
            await update.message.reply_text("Score Predictor is a Max exclusive feature. Upgrade to see your predicted EUEE score! 🔮")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        await cmd_predict(update, ctx)
        return ConversationHandler.END

    if "Review Sheet" in text or "የክለሳ ወረቀት" in text:
        if not db.has_access(effective_tier, "review_sheet"):
            await update.message.reply_text("Personalized Review Sheets are for Pro and Max members.")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        await cmd_review_sheet(update, ctx)
        return ConversationHandler.END

    if "Exam Tips" in text or "የፈተና ምክሮች" in text:
        ctx.user_data["notes_mode"] = "examtips"
        await update.message.reply_text("Pick a subject for Exam Tips:", reply_markup=kb.subject_keyboard(lang))
        return CHOOSE_SUBJECT

    if "Weak Radar" in text or "ድክመት" in text:
        if not db.has_access(effective_tier, "weak_radar"):
            await update.message.reply_text("Weakness Radar analysis is for Max members. Upgrade to identify your study gaps! 📡")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        await cmd_radar(update, ctx)
        return ConversationHandler.END

    if "Parent" in text or "ወላጅ" in text:
        if not db.has_access(effective_tier, "parent_link"):
            await update.message.reply_text("Parent Monitoring Links are for Max members. Upgrade to share your progress with your parents! 👨‍👩‍👦")
            await cmd_upgrade(update, ctx)
            return ConversationHandler.END
        parent_token = user.get("parent_token", "N/A")
        from config import BASE_WEB_URL
        link = f"{BASE_WEB_URL}/parent/{parent_token}"
        msg = f"👨‍👩‍👦 **Parent Monitoring Link**\n\nShare this link with your parents to show them your progress:\n{link}"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return ConversationHandler.END

    if "Upgrade" in text or "አሳድግ" in text or "/plan" in text or "Plan" in text:
        await cmd_plan(update, ctx)
        return ConversationHandler.END

    if "Invite Friend" in text or "ጓደኛ ይጋብዙ" in text:
        await cmd_invite(update, ctx)
        return ConversationHandler.END

    if "Feature Suggest" in text or "አዲስ ሀሳብ" in text:
        await update.message.reply_text("What features would you like to see? Type it below:")
        return AWAITING_FEATURE_SUGGESTION

    if "/menu" in text.lower():
        await update.message.reply_text(
            _main_menu_text(lang, update.effective_user.first_name),
            reply_markup=kb.main_menu_keyboard(lang),
        )
        return ConversationHandler.END

    if "Random Challenge" in text or "የዘፈቀደ ጥያቄ" in text:
        import random

        subject = random.choice(list(SUBJECTS.keys()))
        db.update_user(update.effective_user.id, {"chosen_subject": subject})
        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        q = await run_blocking(ai.generate_exam_question, subject, lang=lang)
        ctx.user_data["current_q"] = q
        await update.message.reply_text(
            _format_question(q, f"Random challenge: {_subject_name(subject)}"),
            reply_markup=kb.mcq_keyboard(q.get("options", {})),
        )
        return ASKING_QUESTION

    return ConversationHandler.END


async def choose_subject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "/menu" in text.lower():
        user = db.get_user(update.effective_user.id)
        lang = user.get("language", "en") if user else "en"
        await update.message.reply_text(
            _main_menu_text(lang, update.effective_user.first_name),
            reply_markup=kb.main_menu_keyboard(lang),
        )
        ctx.user_data.pop("notes_mode", None)
        ctx.user_data["awaiting_subject"] = False
        return ConversationHandler.END

    subject = subject_from_button(text)
    if not subject:
        await update.message.reply_text("Please pick a subject from the buttons.")
        return CHOOSE_SUBJECT

    user = db.get_user(update.effective_user.id)
    lang = user.get("language", "en") if user else "en"
    mode = ctx.user_data.get("notes_mode")
    db.update_user(update.effective_user.id, {"chosen_subject": subject})
    ctx.user_data["awaiting_subject"] = False
    ctx.user_data["notes_mode"] = None
    try:
        if mode == "notes":
            await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            # Priority 1: check the notes/ folder for pre-made PDFs
            local_notes_pdf = notes.get_local_notes_pdf(subject)
            if local_notes_pdf:
                note_caption = notes.study_notes_document_caption(subject, lang)
                with open(local_notes_pdf, "rb") as file_handle:
                    await update.message.reply_document(
                        document=file_handle,
                        caption=note_caption[:1024],
                        reply_markup=kb.main_menu_keyboard(lang),
                    )
                return ConversationHandler.END
            # Priority 2: check euee_notes/ for generated notes
            files = await run_blocking(notes.ensure_subject_notes_generated, subject)
            note_caption = notes.study_notes_document_caption(subject, lang)
            if files.get("pdf"):
                with open(files["pdf"], "rb") as file_handle:
                    await update.message.reply_document(
                        document=file_handle,
                        caption=note_caption[:1024],
                        reply_markup=kb.main_menu_keyboard(lang),
                    )
                return ConversationHandler.END
            if files.get("md"):
                with open(files["md"], "rb") as file_handle:
                    await update.message.reply_document(
                        document=file_handle,
                        caption=(note_caption + " (Markdown)")[:1024],
                        reply_markup=kb.main_menu_keyboard(lang),
                    )
                return ConversationHandler.END
            await update.message.reply_text("I could not prepare notes for that subject yet.", reply_markup=kb.main_menu_keyboard(lang))
            return ConversationHandler.END

        if mode == "audio":
            cache_key = f"audio_file_{subject}_{lang}"
            cached = db.get_cached_content(cache_key)
            if cached and cached.get("file_id"):
                await update.message.reply_audio(audio=cached["file_id"], reply_markup=kb.main_menu_keyboard(lang))
                return ConversationHandler.END

            local_audio = notes.get_local_audio_file(subject)
            if local_audio:
                with open(local_audio, "rb") as file_handle:
                    sent = await update.message.reply_audio(
                        audio=file_handle,
                        title=f"{_subject_name(subject)} lesson",
                        reply_markup=kb.main_menu_keyboard(lang),
                    )
                if sent.audio:
                    db.set_cached_content(cache_key, {"file_id": sent.audio.file_id})
                return ConversationHandler.END

            await update.message.reply_text("Preparing your audio lesson. This can take a few seconds.")
            await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            script = await run_blocking(notes.generate_audio_script, subject, lang)
            try:
                audio_path = await notes.generate_real_audio(script, lang)
                with open(audio_path, "rb") as file_handle:
                    sent = await update.message.reply_audio(
                        audio=file_handle,
                        title=f"{_subject_name(subject)} lesson",
                        caption=notes.audio_lesson_caption(lang),
                        reply_markup=kb.main_menu_keyboard(lang),
                    )
                if sent.audio:
                    db.set_cached_content(cache_key, {"file_id": sent.audio.file_id})
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception:
                await update.message.reply_text(
                    "Audio generation is unavailable right now, so I am sending the lesson script instead."
                )
                await update.message.reply_text(script, reply_markup=kb.main_menu_keyboard(lang))
            return ConversationHandler.END

        if mode == "flashcards":
            await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            # Increased to 20 flashcards as requested
            cards = await run_blocking(notes.generate_flashcards, subject, 20, lang)
            if not cards:
                await update.message.reply_text("No flashcards are ready for that subject yet.", reply_markup=kb.main_menu_keyboard(lang))
                return ConversationHandler.END
            ctx.user_data["flashcards"] = cards
            first = cards[0]
            await update.message.reply_text(
                f"Card 1/{len(cards)}\n\nQuestion:\n{first['question']}",
                reply_markup=kb.flashcard_keyboard(0, len(cards)),
            )
            return ConversationHandler.END

        if mode == "mnemonic":
            await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            result = await run_blocking(
                notes.generate_mnemonic, f"key ideas in {_subject_name(subject)}", lang
            )
            await update.message.reply_text(result, reply_markup=kb.main_menu_keyboard(lang))
            return ConversationHandler.END

        if mode == "examtips":
            await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
            result = await run_blocking(notes.generate_exam_tips, subject, lang)
            await update.message.reply_text(result, reply_markup=kb.main_menu_keyboard(lang))
            return ConversationHandler.END

        if mode == "model_exam":
            tier = db.normalize_tier(user.get("tier"))
            if not db.has_access(tier, "model_exam_5"):
                await update.message.reply_text("Model Exams are for Pro and Max members.")
                await cmd_upgrade(update, ctx)
                return ConversationHandler.END
            
            ctx.user_data["exam_subject"] = subject
            model_count = "5" if tier == "pro" else "50"
            await update.message.reply_text(
                f"Select a Model Exam for {_subject_name(subject)} ({model_count} Models available for your {tier.capitalize()} tier):",
                reply_markup=kb.model_selection_keyboard(subject, lang, tier=tier),
            )
            return ConversationHandler.END

        if mode == "mock_exam":
            ctx.user_data["exam_subject"] = subject
            await update.message.reply_text(
                f"Mock Exam subject set to {_subject_name(subject)}. Choose exam length:",
                reply_markup=kb.exam_options_keyboard(lang),
            )
            return ConversationHandler.END

        # Practice mode: generate one question and enter Q&A loop
        if mode == "practice":
            ctx.user_data["current_q"] = await run_blocking(ai.generate_exam_question, subject, lang=lang)
            ctx.user_data["practice_subject"] = subject
            q = ctx.user_data["current_q"]
            await update.message.reply_text(
                _format_question(q, f"Practice — {_subject_name(subject)}"),
                reply_markup=kb.mcq_keyboard(q.get("options", {})),
            )
            return ASKING_QUESTION

        await update.message.reply_text(
            f"Subject set to {_subject_name(subject)}. Ask me anything or use the menu to practice.",
            reply_markup=kb.main_menu_keyboard(lang),
        )
        return ASKING_QUESTION

    except Exception as e:
        logger.error(f"Error in choose_subject: {e}", exc_info=True)
        await update.message.reply_text(
            "I hit a small snag while preparing that. Let's try again or pick another subject!",
            reply_markup=kb.main_menu_keyboard(lang)
        )
        return ConversationHandler.END


async def _handle_battle_text_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user: dict, answer_text: str):
    answer = answer_text.strip().upper()[:1]
    if answer not in {"A", "B", "C", "D"}:
        await update.message.reply_text("For this battle, answer with A, B, C, or D.")
        return ASKING_QUESTION

    battle_id = ctx.user_data.get("active_battle")
    battle = db.get_battle(battle_id) if battle_id else None
    if not battle or battle.get("status") == "done":
        _clear_battle_state(ctx)
        await update.message.reply_text("That battle is no longer active.", reply_markup=kb.main_menu_keyboard(user.get("language", "en")))
        return ConversationHandler.END

    await _resolve_battle_answer(update.effective_user.id, answer, battle, ctx)
    return ASKING_QUESTION


async def handle_question(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if "/menu" in text.lower():
        user = db.get_user(update.effective_user.id)
        lang = user.get("language", "en") if user else "en"
        await update.message.reply_text(
            _main_menu_text(lang, update.effective_user.first_name),
            reply_markup=kb.main_menu_keyboard(lang),
        )
        return ConversationHandler.END

    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return ConversationHandler.END

    if ctx.user_data.get("awaiting_feature"):
        ctx.user_data["awaiting_feature"] = False
        idea = sanitize_input(update.message.text or "")
        await update.message.reply_text("Analyzing your suggestion...")
        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        report = await run_blocking(ai.generate_feature_proposal, idea)
        await update.message.reply_text(f"Feature Proposal Report\n\n{report}")
        return ASKING_QUESTION

    if ctx.user_data.get("active_battle"):
        return await _handle_battle_text_answer(update, ctx, user, update.message.text or "")

    lang = user.get("language", "en")
    tier = db.normalize_tier(user.get("tier"))
    limit = TIER_LIMITS.get(tier, 5)

    question = sanitize_input(update.message.text or "")
    subject = user.get("chosen_subject", "math")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    # If we're in a practice session and a question was sent, treat the user's
    # message as an answer instead of a new question prompt.
    if ctx.user_data.get("practice_subject") and ctx.user_data.get("current_q"):
        q = ctx.user_data.get("current_q", {})
        ans = sanitize_input(update.message.text or "").strip().upper()[:1]
        if ans not in {"A", "B", "C", "D"}:
            await update.message.reply_text("Please answer with A, B, C, or D (or press a button).")
            return ASKING_QUESTION

        correct = q.get("answer", "")
        is_correct = ans == correct
        subj = ctx.user_data.get("practice_subject") or subject
        topic = q.get("topic", "General")
        db.record_answer(update.effective_user.id, subj, is_correct, topic, question_data=q)
        explanation = q.get("explanation", "No explanation available.")
        tip_text = (
            "💡 **Exam Tip:** Read the question carefully to identify exactly what is being asked before jumping to calculations."
            if lang == "en"
            else "💡 **የፈተና ምክር:** ወደ ስሌት ከመዝለልዎ በፊት በትክክል ምን እየተጠየቀ እንደሆነ ለመለየት ጥያቄውን በጥንቃቄ ያንብቡ።"
        )
        result_text = "✅ Correct." if is_correct else f"❌ Not quite. The answer was {correct}."
        result_text = f"{result_text}\n\n**Explanation:**\n{explanation}\n\n{tip_text}"
        db.update_user(update.effective_user.id, {"last_explanation": result_text[:1000]})
        # Clear current question; user can press Next Question to continue.
        ctx.user_data.pop("current_q", None)
        try:
            await update.message.reply_text(result_text, reply_markup=kb.after_answer_keyboard(lang), parse_mode="Markdown")
        except Exception:
            # Fallback if Markdown fails
            await update.message.reply_text(result_text, reply_markup=kb.after_answer_keyboard(lang))
        return ASKING_QUESTION

    # Normal Q&A: treat user message as a question for the bot to answer
    response = await run_blocking(
        _sync_qna_pipeline,
        update.effective_user.id,
        tier,
        limit,
        question,
        subject,
        lang,
    )
    if response is None:
        await update.message.reply_text("Daily question limit reached. Upgrade for more access.")
        return ASKING_QUESTION

    await update.message.reply_text(response, reply_markup=kb.after_answer_keyboard(lang))

    total = user.get("questions_total", 0) + 1
    if total % 10 == 0:
        weak = await run_blocking(db.get_weak_subjects, update.effective_user.id)
        await update.message.reply_text(build_radar_chart(weak))
        if weak:
            analysis = await run_blocking(ai.generate_weak_radar_analysis, weak, lang)
            await update.message.reply_text(analysis)
    return ASKING_QUESTION


async def _resolve_exam_answer(query, ctx: ContextTypes.DEFAULT_TYPE, user: dict, answer: str):
    q = ctx.user_data.get("current_q", {})
    subject = ctx.user_data.get("exam_subject") or user.get("chosen_subject", "math")
    correct = q.get("answer", "")
    is_correct = answer == correct
    topic = q.get("topic", "General")
    db.record_answer(query.from_user.id, subject, is_correct, topic, question_data=q)

    exam_score = ctx.user_data.get("exam_score", 0) + (1 if is_correct else 0)
    current_index = ctx.user_data.get("exam_current", 0) + 1
    total = ctx.user_data.get("exam_total", 0)

    ctx.user_data["exam_score"] = exam_score
    ctx.user_data["exam_current"] = current_index

    feedback = "Correct." if is_correct else f"Not quite. The correct answer was {correct}."
    explanation = q.get("explanation", "")

    if current_index >= total:
        percentage = round((exam_score / total) * 100, 1) if total else 0
        weak_topics = [] if percentage >= 70 else [subject]
        db.save_exam_result(query.from_user.id, subject, exam_score, total, weak_topics)
        _clear_exam_state(ctx)
        await query.edit_message_text(
            f"{feedback}\n\n{explanation}\n\nMock exam complete.\nScore: {exam_score}/{total} ({percentage}%)."
        )
        await query.message.reply_text("Use Progress to review your overall performance.", reply_markup=kb.main_menu_keyboard(user.get("language", "en")))
        return

    model_idx = ctx.user_data.get("model_index")
    try:
        next_q = await run_blocking(
            ai.generate_exam_question, subject, lang=user.get("language", "en"), model_index=model_idx
        )
        ctx.user_data["current_q"] = next_q
        
        # Safe edit
        try:
            await query.edit_message_text(f"{feedback}\n\n{explanation}")
        except Exception:
            # If edit fails, just send as new message or ignore if same
            pass
            
        await query.message.reply_text(
            _format_question(next_q, f"Question {current_index + 1}/{total}"),
            reply_markup=kb.mcq_keyboard(next_q.get("options", {})),
        )
    except Exception as e:
        logger.error(f"Exam question generation failed: {e}")
        await query.message.reply_text("I'm having a little trouble finding the next question. Let's try once more!", reply_markup=kb.after_answer_keyboard(user.get("language", "en")))


async def _resolve_battle_answer(user_id: int, answer: str, battle: dict, ctx: ContextTypes.DEFAULT_TYPE):
    if battle.get("status") == "done":
        _clear_battle_state(ctx)
        await ctx.bot.send_message(chat_id=user_id, text="That battle has already finished.")
        return

    correct = (battle.get("correct_answer") or "").upper()[:1]
    is_correct = answer == correct
    time_taken = round(time.time() - ctx.user_data.get("battle_start", time.time()), 2)
    updated = db.submit_battle_answer(battle["battle_id"], user_id, answer, time_taken, is_correct)

    challenger_answered = updated.get("challenger_answer") is not None
    opponent_answered = updated.get("opponent_answer") is not None

    if not challenger_answered or not opponent_answered:
        await ctx.bot.send_message(
            chat_id=user_id,
            text=f"Answer locked in. {'Correct' if is_correct else f'Wrong, the answer was {correct}.'} Waiting for the other student.",
        )
        return

    challenger_correct = bool(updated.get("challenger_correct"))
    opponent_correct = bool(updated.get("opponent_correct"))
    challenger_time = updated.get("challenger_time") or 999999
    opponent_time = updated.get("opponent_time") or 999999

    winner_id = None
    if challenger_correct and not opponent_correct:
        winner_id = updated.get("challenger_id")
    elif opponent_correct and not challenger_correct:
        winner_id = updated.get("opponent_id")
    elif challenger_correct and opponent_correct:
        winner_id = updated.get("challenger_id") if challenger_time <= opponent_time else updated.get("opponent_id")

    db.finalize_battle(updated["battle_id"], winner_id, challenger_correct, opponent_correct)
    _clear_battle_state(ctx)
    summary_lines = [
        "Battle finished.",
        f"Correct answer: {correct}",
        f"Explanation: {updated.get('explanation', '')}",
    ]
    summary_lines.append("Result: Draw." if winner_id is None else f"Winner: {winner_id}")
    summary = "\n".join(summary_lines)

    for participant in [updated.get("challenger_id"), updated.get("opponent_id")]:
        if participant:
            await ctx.bot.send_message(chat_id=participant, text=summary)


async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Prevent double-click processing
    if ctx.user_data.get("is_processing"):
        return
        
    data = query.data
    user = db.get_user(query.from_user.id)
    if not user:
        await query.edit_message_text("Please use /start first.")
        return

    lang = user.get("language", "en")

    if data == "eli10":
        last = user.get("last_explanation", "")
        if not last:
            await query.edit_message_text("There is no previous explanation to simplify yet.")
            return
        ctx.user_data["is_processing"] = True
        try:
            await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
            simplified = await run_blocking(ai.eli10_explain, last, lang)
            await query.edit_message_text(simplified)
        finally:
            ctx.user_data["is_processing"] = False
        return

    if data == "read_aloud":
        last = user.get("last_explanation", "")
        if not last:
            await query.answer("Nothing to read yet.")
            return
        
        await query.answer("Generating audio...")
        ctx.user_data["is_processing"] = True
        try:
            # Clean text for better TTS (remove some symbols, markdown)
            clean_text = notes._clean_for_audio(last, limit=1000)
            audio_path = await notes.generate_real_audio(clean_text, lang)
            with open(audio_path, "rb") as audio_file:
                await ctx.bot.send_audio(
                    chat_id=query.from_user.id,
                    audio=audio_file,
                    title="Abebe's Voice",
                    caption="🔊 Here is the audio explanation."
                )
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception as exc:
            logger.error("Read aloud failed: %s", exc)
            await query.message.reply_text("I'm sorry, I couldn't generate the audio right now.")
        finally:
            ctx.user_data["is_processing"] = False
        return

    if data == "mnemonic_last":
        last = user.get("last_explanation", "") or "general study ideas"
        ctx.user_data["is_processing"] = True
        try:
            await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
            mnemonic = await run_blocking(notes.generate_mnemonic, last[:200], lang)
            await query.edit_message_text(mnemonic)
        finally:
            ctx.user_data["is_processing"] = False
        return

    if data == "next_q":
        if ctx.user_data.get("exam_active"):
            await _resolve_exam_answer(query, ctx, user, "SKIP")
            return
            
        if ctx.user_data.get("active_battle"):
            await query.answer("You cannot skip questions in Battle Mode!", show_alert=True)
            return
            
        ctx.user_data["is_processing"] = True
        try:
            subject = user.get("chosen_subject", "math")
            await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
            q = await run_blocking(ai.generate_exam_question, subject, lang=lang)
            ctx.user_data["current_q"] = q
            try:
                await query.edit_message_text(_format_question(q), reply_markup=kb.mcq_keyboard(q.get("options", {})))
            except Exception as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    await query.message.reply_text(_format_question(q), reply_markup=kb.mcq_keyboard(q.get("options", {})))
        finally:
            ctx.user_data["is_processing"] = False
        return

    if data.startswith("mcq_"):
        answer = data.replace("mcq_", "").upper()
        if ctx.user_data.get("exam_active"):
            await _resolve_exam_answer(query, ctx, user, answer)
            return

        if ctx.user_data.get("active_battle"):
            battle_id = ctx.user_data.get("active_battle")
            battle = db.get_battle(battle_id) if battle_id else None
            if not battle or battle.get("status") == "done":
                _clear_battle_state(ctx)
                await query.edit_message_text("That battle is no longer active.")
                return
            await _resolve_battle_answer(query.from_user.id, answer, battle, ctx)
            await query.edit_message_text("Your battle answer has been submitted.")
            return

        q = ctx.user_data.get("current_q", {})
        subject = user.get("chosen_subject", "math")
        correct = q.get("answer", "")
        is_correct = answer == correct
        topic = q.get("topic", "General")
        db.record_answer(query.from_user.id, subject, is_correct, topic, question_data=q)
        explanation = q.get("explanation", "")
        
        # Hardcoded fast Exam Tip (for extreme performance and to fulfill 'write it yourself' request)
        tip_text = "💡 **Exam Tip:** Read the question carefully to identify exactly what is being asked before jumping to calculations." if lang == "en" else "💡 **የፈተና ምክር:** ወደ ስሌት ከመዝለልዎ በፊት በትክክል ምን እየተጠየቀ እንደሆነ ለመለየት ጥያቄውን በጥንቃቄ ያንብቡ።"
        
        result_text = "✅ Correct." if is_correct else f"❌ Not quite. The answer was {correct}."
        result_text = f"{result_text}\n\n**Explanation:**\n{explanation}\n\n{tip_text}"
        db.update_user(query.from_user.id, {"last_explanation": result_text[:1000]})
        try:
            await query.edit_message_text(result_text, reply_markup=kb.after_answer_keyboard(lang), parse_mode="Markdown")
        except Exception:
            # Fallback to no markdown if parsing fails (common with AI symbols)
            await query.edit_message_text(result_text, reply_markup=kb.after_answer_keyboard(lang))
        return

    if data.startswith("exam_"):
        count = int(data.replace("exam_", ""))
        subject = ctx.user_data.get("exam_subject") or user.get("chosen_subject", "math")
        ctx.user_data["exam_active"] = True
        ctx.user_data["exam_total"] = count
        ctx.user_data["exam_score"] = 0
        ctx.user_data["exam_current"] = 0
        ctx.user_data["exam_start"] = time.time()
        ctx.user_data["exam_subject"] = subject
        await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
        # Mock Exam should not use a model_index from user_data (ensure randomness)
        q = await run_blocking(ai.generate_exam_question, subject, lang=lang)
        ctx.user_data["current_q"] = q
        await query.edit_message_text(
            _format_question(q, f"🚀 **Mock Exam Started** ({count} Questions)\nSubject: {_subject_name(subject)}\nQuestion 1/{count}"),
            reply_markup=kb.mcq_keyboard(q.get("options", {})),
            parse_mode="Markdown"
        )
        return

    # upgrade_ logic moved to handle_upgrade_button

    if data.startswith("join_battle_"):
        battle_id = data.replace("join_battle_", "")
        battle = db.join_battle(battle_id, query.from_user.id)
        if not battle:
            await query.edit_message_text("This battle is no longer available.")
            return
        q = _battle_payload_from_record(battle)
        ctx.user_data["active_battle"] = battle_id
        ctx.user_data["battle_start"] = time.time()
        ctx.user_data["current_q"] = q
        await query.edit_message_text(
            _format_question(q, "Battle joined. Answer using the buttons below."),
            reply_markup=kb.mcq_keyboard(q.get("options", {})),
        )
        return

    if data.startswith("flip_"):
        index = int(data.replace("flip_", ""))
        cards = ctx.user_data.get("flashcards", [])
        if 0 <= index < len(cards):
            card = cards[index]
            await query.edit_message_text(
                f"Card {index + 1}/{len(cards)}\n\nQuestion:\n{card['question']}\n\nAnswer:\n{card['answer']}",
                reply_markup=kb.flashcard_keyboard(index, len(cards)),
            )
        return

    if data.startswith("fc_next_"):
        index = int(data.replace("fc_next_", "")) + 1
        cards = ctx.user_data.get("flashcards", [])
        if 0 <= index < len(cards):
            card = cards[index]
            await query.edit_message_text(
                f"Card {index + 1}/{len(cards)}\n\nQuestion:\n{card['question']}",
                reply_markup=kb.flashcard_keyboard(index, len(cards)),
            )
        return

    if data.startswith("fc_prev_"):
        index = int(data.replace("fc_prev_", "")) - 1
        cards = ctx.user_data.get("flashcards", [])
        if 0 <= index < len(cards):
            card = cards[index]
            await query.edit_message_text(
                f"Card {index + 1}/{len(cards)}\n\nQuestion:\n{card['question']}",
                reply_markup=kb.flashcard_keyboard(index, len(cards)),
            )
        return

    if data.startswith("chapter_"):
        subject, chapter = data.replace("chapter_", "").rsplit("_", 1)
        await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
        summary = await run_blocking(notes.generate_chapter_summary, subject, int(chapter), lang)
        await query.edit_message_text(summary)
        return

    if data.startswith("fullnotes_"):
        subject = data.replace("fullnotes_", "")
        await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
        notes_text = await notes.generate_study_notes(subject, lang)
        preview = (notes_text or "")[:3800]
        if len(notes_text) > 3800:
            preview += "\n\nOpen Study Notes from the menu to get the full PDF."
        await query.edit_message_text(preview)
        return

    if data.startswith("model_"):
        parts = data.split("_")
        subject = parts[1]
        model_index = int(parts[2])
        user = db.get_user(query.from_user.id)
        tier = db.normalize_tier(user.get("tier")) if user else "free"
        
        limit = 5 if tier == "pro" else 50 if tier == "max" else 0
        if model_index > limit:
            await query.answer(f"Model {model_index} is not available on your {tier.capitalize()} tier. Upgrade for more!")
            return
            
        ctx.user_data["exam_active"] = True
        ctx.user_data["exam_total"] = 100
        ctx.user_data["exam_score"] = 0
        ctx.user_data["exam_current"] = 0
        ctx.user_data["exam_start"] = time.time()
        ctx.user_data["exam_subject"] = subject
        ctx.user_data["model_index"] = model_index
        # Consolidated start message + question 1 for better UX
        await query.edit_message_text(f"⏳ Preparing Model Exam {model_index} for {_subject_name(subject)}...")
        
        q = await run_blocking(ai.generate_exam_question, subject, lang=lang, model_index=model_index)
        ctx.user_data["current_q"] = q
        
        start_msg = f"🏆 **Starting Model Exam {model_index}** for {_subject_name(subject)}\nThis full-length exam has 100 questions. Good luck!\n\nQuestion 1/100"
        await query.edit_message_text(
            _format_question(q, start_msg),
            reply_markup=kb.mcq_keyboard(q.get("options", {})),
            parse_mode="Markdown"
        )
        return

    if data.startswith("admin_approve_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("⛔ You are not authorized.", show_alert=True)
            return
        tx_id = data.replace("admin_approve_", "")
        attempt_data = db.get_payment_attempt(tx_id)
        if not attempt_data:
            await query.answer("Transaction not found.")
            return
        
        if attempt_data.get("status") != "PENDING":
            await query.answer(f"Already {attempt_data.get('status')}")
            return

        success = db.approve_payment(tx_id)
        if success:
            # Try editing the caption (works if message has a photo)
            try:
                await query.edit_message_caption(
                    f"{query.message.caption or ''}\n\n✅ APPROVED by {query.from_user.first_name}"
                )
            except Exception:
                try:
                    await query.edit_message_text(
                        f"✅ APPROVED by {query.from_user.first_name}\nTX: {tx_id}"
                    )
                except Exception:
                    pass

            # Notify student with correct expiry date and duration label
            student_id = attempt_data.get("telegram_id")
            raw_plan = str(attempt_data.get("plan_requested", "pro")).lower()
            plan = "MAX" if "max" in raw_plan else "PRO"
            from datetime import datetime, timedelta
            days = 365 if "yearly" in raw_plan else 30
            duration_label = "1 Year" if days == 365 else "30 Days"
            expiry_date = (datetime.now() + timedelta(days=days)).strftime("%B %d, %Y")
            try:
                await ctx.bot.send_message(
                    chat_id=student_id,
                    text=(
                        f"🎊 **CONGRATULATIONS!**\n\n"
                        f"Your upgrade to **{plan}** has been approved!\n"
                        f"You now have full access to all {plan} features.\n\n"
                        f"📅 **Your plan expires:** {expiry_date}\n"
                        f"_({duration_label} from today)_\n\n"
                        f"Enjoy your studies! 🚀"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify student {student_id}: {e}")
        else:
            await query.answer("Approval failed.")
        return

    if data.startswith("admin_reject_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("⛔ You are not authorized.", show_alert=True)
            return
        tx_id = data.replace("admin_reject_", "")
        db.reject_payment(tx_id)
        # FIX: Fallback to edit_message_text if caption is unavailable (prevents crash on text-only messages).
        try:
            if query.message and query.message.caption:
                await query.edit_message_caption(
                    f"{query.message.caption}\n\n❌ REJECTED by {query.from_user.first_name}"
                )
            else:
                await query.edit_message_text(
                    f"❌ REJECTED by {query.from_user.first_name}\nTX: {tx_id}"
                )
        except Exception:
            pass
        return

    if data == "admin_view_stats":
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("⛔ You are not authorized.", show_alert=True)
            return
        await query.answer("Fetching stats...")
        # FIX: Batch-process users to avoid OOM with 50k+ users.
        total = free = pro = max_tier = 0
        try:
            query = db.db.collection("users").limit(500)
            last_doc = None
            while True:
                if last_doc:
                    query = query.start_after(last_doc)
                docs = list(query.stream())
                if not docs:
                    break
                for doc in docs:
                    total += 1
                    t = doc.to_dict().get("tier", "free")
                    if t == "free": free += 1
                    elif t == "pro": pro += 1
                    elif t == "max": max_tier += 1
                last_doc = docs[-1]
                await asyncio.sleep(0)  # yield control
        except Exception as exc:
            logger.error("admin_view_stats failed: %s", exc)
            await query.edit_message_text("❌ Failed to fetch stats. Check logs.", reply_markup=kb.telegram_admin_keyboard())
            return
        
        pending = len(db.get_pending_payments())
        revenue = (pro * 100) + (max_tier * 200)
        
        stats_msg = (
            f"📊 **BOT STATISTICS**\n\n"
            f"👥 **Total Students:** {total}\n"
            f"🆓 **Free Tier:** {free}\n"
            f"⭐ **Pro Tier:** {pro}\n"
            f"💎 **Max Tier:** {max_tier}\n"
            f"💰 **Est. Monthly Revenue:** {revenue} ETB\n"
            f"⏳ **Pending Upgrades:** {pending}\n"
        )
        await query.edit_message_text(stats_msg, parse_mode="Markdown", reply_markup=kb.telegram_admin_keyboard())
        return

    if data == "admin_view_pending":
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("⛔ You are not authorized.", show_alert=True)
            return
        await query.answer("Fetching pending upgrades...")
        pending = db.get_pending_payments()
        if not pending:
            await query.edit_message_text("✅ No pending upgrades.", reply_markup=kb.telegram_admin_keyboard())
            return
        
        for p in pending[:5]: # Show top 5
            tx_id = p.get('transaction_id')
            user_name = p.get('username')
            plan = p.get('plan_requested', 'unknown').upper()
            msg = (
                f"🔔 **PENDING UPGRADE**\n"
                f"👤 {user_name} (`{p.get('telegram_id')}`)\n"
                f"💎 Plan: {plan}\n"
                f"🧾 TX: `{tx_id}`\n"
            )
            await ctx.bot.send_message(
                chat_id=query.from_user.id,
                text=msg,
                parse_mode="Markdown",
                reply_markup=kb.admin_approval_keyboard(tx_id)
            )
        
        text = f"Showing {min(5, len(pending))} of {len(pending)} pending requests above."
        await query.edit_message_text(text, reply_markup=kb.telegram_admin_keyboard())
        return

    if data == "admin_view_suggestions":
        # FIX: Allow both configured admins to inspect feature suggestions for parity with other admin actions.
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("⛔ You are not authorized.", show_alert=True)
            return
        await query.answer("Fetching suggestions...")
        suggs = db.get_feature_suggestions()
        if not suggs:
            await query.edit_message_text("No suggestions yet.", reply_markup=kb.telegram_admin_keyboard())
            return
        
        lines = ["💡 **RECENT SUGGESTIONS**\n"]
        for s in suggs[:10]:
            lines.append(f"👤 **{s.get('username')}**: {s.get('suggestion')}\n")
        
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb.telegram_admin_keyboard())
        return


async def cmd_progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return
    
    lang = user.get("language", "en")
    tier = db.normalize_tier(user.get("tier"))
    msg = format_progress(user, lang)
    
    if tier != "free":
        extra = (
            "\n\n💎 **Premium Feature Available:**\n"
            "You can now download a **Personalized Review PDF** of questions you've missed! Use /review to get your study sheet."
            if lang == "en" else
            "\n\n💎 **ልዩ አገልግሎት:**\n"
            "የተሳሳቷቸውን ጥያቄዎች በ PDF ማውረድ ይችላሉ! /review የሚለውን ትዕዛዝ ይጠቀሙ።"
        )
        msg += extra
        
    await update.message.reply_text(msg)


async def cmd_review_sheet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return
        
    lang = user.get("language", "en")
    tier = db.normalize_tier(user.get("tier"))
    
    if tier == "free":
        await update.message.reply_text(
            "❌ **Premium Only**\n\nPersonalized Review Sheets (PDF) are only available for **Pro** and **Max** students. Upgrade now to get yours!" if lang == "en" else
            "❌ **ለፕሪሚየም ተማሪዎች ብቻ**\n\nየግል ክለሳ ማስታወሻዎች (PDF) ለ **Pro** እና **Max** ተማሪዎች ብቻ የተፈቀዱ ናቸው። አሁኑኑ አካውንትዎን ያሳድጉ!",
            reply_markup=kb.upgrade_keyboard()
        )
        return

    await update.message.reply_text("📝 Generating your personalized review sheet... This may take a moment.")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
    
    wrong_qs = db.get_wrong_questions(update.effective_user.id, limit=30)
    if not wrong_qs:
        await update.message.reply_text(
            "You haven't missed any questions yet! Keep practicing and come back when you have some errors to review." if lang == "en" else
            "እስካሁን የተሳሳቱት ጥያቄ የለም! ጠንክረው ይለማመዱ እና ሲሳሳቱ ተመልሰው ይምጡ።"
        )
        return
        
    pdf_path = await run_blocking(generate_personalized_review_pdf, update.effective_user.id, user.get("name", "Student"), wrong_qs, lang)
    
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            await ctx.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=os.path.basename(pdf_path),
                caption="✅ Here is your Personalized Review Sheet. Study hard!" if lang == "en" else "✅ የግል ክለሳ ማስታወሻዎ ይኸውና። በደንብ ያጥኑ!"
            )
        # Cleanup
        try: os.remove(pdf_path)
        except: pass
    else:
        await update.message.reply_text("Sorry, I hit a snag while generating your PDF. Please try again in a moment.")


async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    lang = user.get("language", "en") if user else "en"
    await update.message.reply_text(format_leaderboard(db.get_leaderboard(10), lang))


async def cmd_battle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return

    subject = user.get("chosen_subject", "math")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    q = await run_blocking(ai.generate_exam_question, subject, lang=user.get("language", "en"))
    battle_id = db.create_battle(update.effective_user.id, subject, q)
    ctx.user_data["active_battle"] = battle_id
    ctx.user_data["battle_start"] = time.time()
    ctx.user_data["current_q"] = q

    await update.message.reply_text(
        _format_question(q, f"Battle created for {_subject_name(subject)}. Answer whenever you are ready."),
        reply_markup=kb.mcq_keyboard(q.get("options", {})),
    )
    await update.message.reply_text(
        f"Invite a friend to join battle {battle_id}.",
        reply_markup=kb.battle_keyboard(battle_id),
    )


async def cmd_confession(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    lang = user.get("language", "en") if user else "en"
    message = (
        "Tell me the topic that still feels confusing. This stays private."
        if lang == "en"
        else "እስካሁን የማይገባህን ርእስ ጻፍ። ይህ የግል ነው።"
    )
    await update.message.reply_text(message)
    return CONFESSION_BOX


async def handle_confession(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    lang = user.get("language", "en") if user else "en"
    topic = sanitize_input(update.message.text or "")
    db.save_confession(update.effective_user.id, topic)
    await update.message.reply_text("Preparing your private explanation...")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    lesson = await run_blocking(ai.generate_confession_lesson, topic, lang)
    await update.message.reply_text(lesson, reply_markup=kb.main_menu_keyboard(lang))
    return ConversationHandler.END


async def cmd_boss_fight(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return ConversationHandler.END

    from datetime import date

    lang = user.get("language", "en")
    # Allow everyday access during development/testing for user
    # if date.today().weekday() not in (4, 6):
    #     await update.message.reply_text(
    #         "Boss Fight opens every Friday and Sunday." if lang == "en" else "Boss Fight በየአርብ እና እሁድ ይከፈታል።"
    #     )
    #     return ConversationHandler.END

    existing = db.get_boss_fight_week()
    if existing:
        question = existing["question"]
    else:
        import random

        await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        subject = random.choice(list(SUBJECTS.keys()))
        question = await run_blocking(ai.generate_boss_fight_question, _subject_name(subject))
        # Also generate a model answer and short explanation to improve auto-judgement
        try:
            prompt = (
                f"Provide a concise model answer and a short explanation for the following boss-level question:\n\n{question}\n\n"
                "Format exactly:\nANSWER: [one-line answer]\nEXPLANATION: [brief explanation]"
            )
            raw = await run_blocking(ai._chat_gemini, "Boss fight answer generator.", prompt)
            model_answer = ""
            explanation = ""
            for line in raw.splitlines():
                if line.upper().startswith("ANSWER:"):
                    model_answer = line.split(":", 1)[1].strip()
                elif line.upper().startswith("EXPLANATION:"):
                    explanation = line.split(":", 1)[1].strip()
            db.save_boss_fight(question, subject, model_answer=model_answer or None, explanation=explanation or None)
        except Exception:
            db.save_boss_fight(question, subject)

    await update.message.reply_text(f"Boss Fight\n\n{question}\n\nType your answer:")
    ctx.user_data["in_boss_fight"] = True
    return BOSS_FIGHT


async def handle_boss_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    lang = user.get("language", "en") if user else "en"
    answer = sanitize_input(update.message.text or "")
    await update.message.reply_text("Checking your answer...")

    existing = db.get_boss_fight_week()
    question = existing["question"] if existing else "the current boss fight question"
    # Use stored model answer (if available) to improve judgement
    model_answer = existing.get("model_answer") if existing else None
    judge_prompt = (
        f"Question: {question}\nModel answer: {model_answer or 'N/A'}\nStudent answer: {answer}\n\n"
        "Judge whether the student's answer is correct or very close to the model answer. Reply with YES or NO first, then give a short explanation."
    )
    verdict = await run_blocking(ai._chat_gemini, "Boss fight judge.", judge_prompt)

    if verdict.upper().startswith("YES"):
        db.complete_boss_fight(update.effective_user.id)
        await update.message.reply_text(
            "You defeated the boss and earned the Champion badge." if lang == "en" else "ቦሱን አሸንፈሃል፣ Champion ባጅ አግኝተሃል።",
            reply_markup=kb.main_menu_keyboard(lang),
        )
        return ConversationHandler.END

    fail_msg = (
        f"Not quite. The correct answer was:\n\n{model_answer or 'N/A'}\n\nExplanation: {existing.get('explanation', 'No explanation available.')}\n\nStudy the idea once more and try again next Friday!"
        if lang == "en"
        else f"አልተሳካም። ትክክለኛው መልስ፡\n\n{model_answer or 'N/A'}\n\nማብራሪያ፡ {existing.get('explanation', 'ምንም ማብራሪያ አልተገኘም።')}\n\nሀሳቡን ደግመህ ተመልከት እና በሚቀጥለው አርብ ሞክር።"
    )
    await update.message.reply_text(
        fail_msg,
        reply_markup=kb.main_menu_keyboard(lang),
    )
    return ConversationHandler.END


async def cmd_predict(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return
    if not db.check_feature_rate_limit(update.effective_user.id, "predict", hours=24):
        await update.message.reply_text("⏳ Abebe is resting his crystal ball! You can use the Score Predictor once every 24 hours.")
        return

    await update.message.reply_text("Analyzing your study record...")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    prediction = await run_blocking(ai.predict_euee_score, user, user.get("language", "en"))
    await update.message.reply_text(prediction)


async def cmd_textbooks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    lang = user.get("language", "en") if user else "en"
    parent_token = user.get("parent_token", "N/A")
    from config import BASE_WEB_URL
    parent_link = f"{BASE_WEB_URL}/parent/{parent_token}"

    textbooks_dir = os.path.join(os.path.dirname(__file__), "textbooks")
    if not os.path.exists(textbooks_dir):
        os.makedirs(textbooks_dir)
        
    files = [f for f in os.listdir(textbooks_dir) if os.path.isfile(os.path.join(textbooks_dir, f))]
    
    if lang == "en":
        msg = "📚 **E-Book & Study Resources**\n\n"
        msg += f"👨‍👩‍👦 **Your Parent Link:**\n{parent_link}\n(Share this with your parents to show your progress!)\n\n"
        msg += "💡 **Study Tips:** Use the 'Exam Tips' button in the main menu for subject-specific advice.\n\n"
        msg += "📖 **Official Textbooks & Notes:**\n"
    else:
        msg = "📚 **ኢ-መጽሐፍት እና የጥናት ግብዓቶች**\n\n"
        msg += f"👨‍👩‍👦 **የወላጅ ሊንክ:**\n{parent_link}\n(ወላጆችህ እድገትህን እንዲያዩ ይህን ሊንክ አካፍላቸው!)\n\n"
        msg += "💡 **የጥናት ምክሮች:** ለእያንዳንዱ ትምህርት ምክር ለማግኘት በዋናው ማውጫ ላይ 'የፈተና ምክሮች' የሚለውን ይጠቀሙ።\n\n"
        msg += "📖 **ኦፊሴላዊ መጽሐፍት እና ማስታወሻዎች:**\n"

    if not files:
        msg += "No textbooks uploaded yet. Abebe is working on it!"
    else:
        for i, f in enumerate(files, 1):
            sig = generate_download_signature(update.effective_user.id)
            link = f"{BASE_WEB_URL}/api/textbooks/download/{f}?user_id={update.effective_user.id}&sig={sig}"
            msg += f"{i}. {f}\n🔗 [Download]({link})\n\n"
        
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb.main_menu_keyboard(lang))

async def cmd_suggest_feature(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Tell me your idea for a new feature:")
    ctx.user_data["awaiting_feature"] = True
    return ASKING_QUESTION

async def handle_upgrade_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    plan_id = data.replace("upgrade_", "")
    if plan_id not in {"pro_monthly", "pro_yearly", "max_monthly", "max_yearly"}:
        await query.message.reply_text("Invalid plan.")
        return ConversationHandler.END

    # Allowed upgrading before current plan expires
    user = db.get_user(query.from_user.id)

    ctx.user_data["pending_tier"] = plan_id
    from config import TIER_PRICES
    price = TIER_PRICES.get(plan_id, 100)
    duration_label = "1 Year" if "yearly" in plan_id else "30 Days"

    tx_ref = f"MAN_{query.from_user.id}_{int(time.time())}"
    saved = db.save_payment_attempt(
        telegram_id=query.from_user.id,
        username=query.from_user.first_name or query.from_user.username or "Student",
        tx_id=tx_ref,
        plan_requested=plan_id,
        screenshot_url="",
        status="PENDING",
        source="manual_review",
        amount=price,
    )
    if not saved:
        await query.edit_message_text(
            "⚠️ Could not create a payment record. Please try again or contact admin.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Store the tx_ref so handle_telebirr_photo can attach the screenshot to it
    ctx.user_data["pending_tx_ref"] = tx_ref

    plan_label = plan_id.replace("_", " ").title()
    msg = (
        f"💳 **{plan_label} — {price} ETB / {duration_label}**\n\n"
        f"To complete your upgrade, follow these steps:\n\n"
        f"1️⃣ Send **{price} ETB** via Telebirr, CBE Birr, or any mobile payment\n"
        f"2️⃣ Take a **screenshot** of your payment receipt\n"
        f"3️⃣ Send the screenshot **here** (to this bot) ⬇️\n"
        f"4️⃣ Also send it directly to **@Fish212424** for faster processing\n\n"
        f"Once verified, your account will be upgraded instantly! 🚀\n"
        f"_Your reference: `{tx_ref}`_"
    )
    await query.edit_message_text(msg, parse_mode="Markdown")
    await query.message.reply_text(
        f"💳 **Payment Details**\n"
        f"Telebirr Number: `{TELEBIRR_NUMBER}`\n\n"
        "📸 Now send your payment receipt screenshot here as a **photo**:",
        parse_mode="Markdown"
    )
    return AWAITING_TELEBIRR_PHOTO

async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return

    tier = db.normalize_tier(user.get("tier"))
    lang = user.get("language", "en")
    
    expires_at = user.get("subscription_expires_at")
    expiry_str = "Never"
    if expires_at:
        import datetime
        try:
            if isinstance(expires_at, str):
                dt = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            elif hasattr(expires_at, "to_datetime"):
                dt = expires_at.to_datetime()
            elif isinstance(expires_at, datetime.datetime):
                dt = expires_at
            elif hasattr(expires_at, "timestamp"):
                dt = datetime.datetime.fromtimestamp(expires_at.timestamp())
            else:
                dt = None
            
            if dt:
                expiry_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            expiry_str = "Error reading date"

    if lang == "en":
        msg = (
            f"👤 **Your Account Status**\n\n"
            f"🌟 **Current Tier:** {tier.upper()}\n"
            f"⏳ **Expires On:** {expiry_str}\n\n"
            f"✅ **Features Included:**\n"
        )
        if tier == "free":
            msg += (
                "- 5 Daily Practice Questions\n"
                "- Public Leaderboard\n"
                "- Community Confessions\n\n"
                "🚀 Upgrade to **Pro** or **Max** for unlimited questions and study materials!"
            )
        elif tier == "pro":
            msg += (
                "- Unlimited Questions\n"
                "- Full Study Notes (PDF)\n"
                "- Lesson Audio Narration\n"
                "- Official Textbooks & E-Books\n"
                "- Memory Tricks & Mnemonics\n"
                "- Personalized Review Sheets\n"
                "- Model Exams (5 full versions)\n\n"
                "👑 Upgrade to **Max** for flashcards, radar tools, and parent reports!"
            )
        else: # max
            msg += (
                "- Everything in Pro\n"
                "- Interactive Flashcards\n"
                "- Weekly Friday Boss Fight\n"
                "- Weakness Radar Analysis\n"
                "- Score Predictor Tool\n"
                "- Parent Monitoring Link\n"
                "- Model Exams (50 full versions)\n"
                "- Priority Feature Requests\n\n"
                "🔥 You have the ULTIMATE plan. Go study and make us proud!"
            )
    else: # am
        msg = (
            f"👤 **የአካውንትዎ ሁኔታ**\n\n"
            f"🌟 **የአሁኑ ደረጃ:** {tier.upper()}\n"
            f"⏳ **የሚያበቃበት ቀን:** {expiry_str}\n\n"
            f"✅ **የተካተቱ ጥቅሞች:**\n"
        )
        if tier == "free":
            msg += (
                "- በቀን 5 የልምምድ ጥያቄዎች\n"
                "- የደረጃ ሰንጠረዥ\n"
                "- የምስጢር ሳጥን\n\n"
                "🚀 ወደ **Pro** ወይም **Max** በማሳደግ ገደብ የለሽ ጥያቄዎችን እና ትምህርቶችን ያግኙ!"
            )
        elif tier == "pro":
            msg += (
                "- ገደብ የለሽ ጥያቄዎች\n"
                "- ሙሉ ማስታወሻዎች (PDF)\n"
                "- የኦዲዮ ትምህርቶች\n"
                "- የትምህርት መጽሐፍት (E-Books)\n"
                "- የማስታወሻ ዘዴዎች\n"
                "- የግል የክለሳ ወረቀት\n"
                "- ሞዴል ፈተናዎች (5 ሙሉ)\n\n"
                "👑 ወደ **Max** በማሳደግ ፍላሽ ካርዶችን እና የራዳር ትንተናን ያግኙ!"
            )
        else: # max
            msg += (
                "- ሁሉንም በ Pro ያለ\n"
                "- ፍላሽ ካርዶች\n"
                "- የአርብ የቦስ ውጊያ\n"
                "- የድክመት ራዳር ትንተና\n"
                "- የውጤት ትንቢት\n"
                "- የወላጅ ሊንክ\n"
                "- ሞዴል ፈተናዎች (50 ሙሉ)\n\n"
                "🔥 ሙሉው ጥቅል አለዎት። ጠንክረው ይማሩ!"
            )

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb.main_menu_keyboard(lang))


async def cmd_upgrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    tier = db.normalize_tier(user.get("tier")) if user else "free"
    lang = user.get("language", "en") if user else "en"

    # Show active plan info with expiry
    plan_info = ""
    if tier != "free":
        import datetime
        expires_at = user.get("subscription_expires_at")
        expiry_str = "Unknown"
        if expires_at:
            try:
                if isinstance(expires_at, str):
                    dt = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                elif hasattr(expires_at, "to_datetime"):
                    dt = expires_at.to_datetime()
                elif isinstance(expires_at, datetime.datetime):
                    dt = expires_at
                elif hasattr(expires_at, "timestamp"):
                    dt = datetime.datetime.fromtimestamp(expires_at.timestamp())
                else:
                    dt = None
                
                if dt:
                    expiry_str = dt.strftime("%B %d, %Y")
            except Exception:
                pass

        if lang == "en":
            plan_info = (
                f"🌟 **Active Plan:** You are on the **{tier.upper()}** plan.\n"
                f"📅 **Expires:** {expiry_str}\n"
                f"You can upgrade now to extend your plan or change your tier. Your new plan will start today. ⏳\n\n"
            )
        else:
            plan_info = (
                f"🌟 **አሁን ያለ ዕቅድ:** **{tier.upper()}** ዕቅድ ላይ ነዎት።\n"
                f"📅 **ሚያበቃበት ቀን:** {expiry_str}\n"
                f"አሁን በማሳደግ ዕቅድዎን ማራዘም ወይም መቀየር ይችላሉ። አዲሱ ዕቅድዎ ዛሬ ይጀምራል። ⏳\n\n"
            )

    msg = plan_info + (
        "👑 **Upgrade Your Plan**\n\n"
        "**Pro** (100 Br/month or 1200 Br/year):\n"
        "✅ Unlimited questions, study notes, audio lessons\n\n"
        "**Max** (200 Br/month or 2200 Br/year):\n"
        "✅ Everything in Pro + flashcards, Boss Fight, parent reports, radar tools\n\n"
        "📌 **How to pay:**\n"
        "1. Pick a plan below\n"
        f"2. Send payment to Telebirr: `{TELEBIRR_NUMBER}`\n"
        "3. Send the screenshot to this bot\n\n"
        "Your account will be upgraded once approved! 🚀"
    )

    await update.message.reply_text(
        msg,
        reply_markup=kb.upgrade_keyboard(),
        parse_mode="Markdown",
    )


async def handle_telebirr_tx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tx_id = (update.message.text or "").strip()
    
    # 1. Validation (Anti-Abuse)
    if not validate_telebirr_tx_id(tx_id):
        await update.message.reply_text("❌ Invalid Transaction ID format. It must be alphanumeric (e.g. AGH123XYZ45). Please try again:")
        return AWAITING_TELEBIRR_TX
        
    # 2. Rate Limiting (DOS Prevention)
    if db.user_telebirr_rate_limit_exceeded(update.effective_user.id):
        await update.message.reply_text("🚨 Too many payment attempts. Please wait an hour before trying again.")
        return ConversationHandler.END
        
    # 3. Duplicate check (Idempotency)
    if db.check_transaction_exists(tx_id):
        await update.message.reply_text("❌ This transaction block has already been submitted or processed. Please submit a valid new payment ID:")
        return AWAITING_TELEBIRR_TX
        
    ctx.user_data["pending_tx_id"] = tx_id
    await update.message.reply_text("✅ Transaction ID accepted. Now, please upload a SCREENSHOT of the Telebirr payment receipt (as a Photo).")
    return AWAITING_TELEBIRR_PHOTO


async def handle_telebirr_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Accept both photo messages and document images
    if not update.message.photo and not (update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/")):
        await update.message.reply_text("❌ Please send a valid PHOTO of your payment receipt.")
        return AWAITING_TELEBIRR_PHOTO

    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Prefer the tx_id already created by handle_upgrade_button; fall back to generating one
    existing_tx_id = ctx.user_data.pop("pending_tx_ref", None)
    tier = ctx.user_data.pop("pending_tier", "pro_monthly")

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id

    if existing_tx_id:
        # Update the already-pending record with the screenshot
        db.update_payment_attempt(existing_tx_id, {"screenshot_url": file_id})
        tx_id = existing_tx_id
        saved = True
    else:
        # New submission (came from /upgrade → photo without handle_upgrade_button path)
        import random, string
        rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        tx_id = f"MAN_{update.effective_user.id}_{rand}"
        saved = db.save_payment_attempt(
            telegram_id=update.effective_user.id,
            username=update.effective_user.first_name or "",
            tx_id=tx_id,
            plan_requested=tier,
            screenshot_url=file_id,
        )

    if not saved:
        await update.message.reply_text("❌ Error saving your request. Please try again or contact @Fish212424.")
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ **Payment Screenshot Received!**\n\n"
        "Your receipt has been sent to the admin for review.\n"
        "📬 For **faster processing**, also send your screenshot directly to **@Fish212424**\n\n"
        "⏳ You will receive a confirmation here as soon as your account is upgraded!",
        parse_mode="Markdown"
    )

    # Notify both admins with photo + approve/reject buttons
    plan_label = tier.replace("_", " ").upper()
    for target_admin in ADMIN_IDS:
        if not target_admin or target_admin == 0:
            continue
        try:
            admin_msg = (
                f"🔔 **NEW UPGRADE REQUEST**\n\n"
                f"👤 **Student:** {update.effective_user.first_name} (@{update.effective_user.username or 'N/A'})\n"
                f"🆔 **Telegram ID:** `{update.effective_user.id}`\n"
                f"💎 **Plan Requested:** {plan_label}\n"
                f"🧾 **Reference ID:** `{tx_id}`\n\n"
                f"✅ Tap Approve to upgrade this student instantly."
            )
            await ctx.bot.send_photo(
                chat_id=target_admin,
                photo=file_id,
                caption=admin_msg,
                parse_mode="Markdown",
                reply_markup=kb.admin_approval_keyboard(tx_id)
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {target_admin}: {e}")

    return ConversationHandler.END


async def handle_suggestion(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Suggestion from {update.effective_user.id}: {update.message.text}")
    text = update.message.text or ""
    if "/menu" in text.lower():
        user = db.get_user(update.effective_user.id)
        lang = user.get("language", "en") if user else "en"
        await update.message.reply_text(
            _main_menu_text(lang, update.effective_user.first_name),
            reply_markup=kb.main_menu_keyboard(lang),
        )
        return ConversationHandler.END
    
    # Save the suggestion
    suggestion = sanitize_input(text)
    user = db.get_user(update.effective_user.id)
    
    try:
        # Store suggestion in database
        db.save_feature_suggestion(
            telegram_id=update.effective_user.id,
            username=user.get("name", "Anonymous"),
            suggestion=suggestion,
            language=user.get("language", "en")
        )
        
        lang = user.get("language", "en")
        if lang == "en":
            msg = (
                "💡 **Thank you for your suggestion!**\n\n"
                "Your idea has been recorded and will be reviewed by our team. "
                "We're always working to make Abebe better for you!\n\n"
                "Keep studying hard! 🚀"
            )
        else:
            msg = (
                "💡 **ሀሳብዎን ስለሰጉ እናመሰግናለሕ!**\n\n"
                "ሀሳብዎ ተቀምጧል እና በቡድናችን ይመለከታል። "
                "አቤቤን ለእርስዎ የበለጠ ጥሩ ለማድረግ ሁልጊዜ እየሰራን ነን!\n\n"
                "በጣም ትጋቡ! 🚀"
            )
        
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb.main_menu_keyboard(lang))
        
        # Notify admins
        if ADMIN_IDS:
            admin_msg = (
                f"💡 **New Feature Suggestion**\n\n"
                f"👤 From: {user.get('name', 'Anonymous')} ({update.effective_user.id})\n"
                f"💭 Suggestion: {suggestion}\n"
                f"🌐 Language: {lang}"
            )
            for admin_id in ADMIN_IDS:
                try:
                    await ctx.bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="Markdown")
                except Exception:
                    pass
    
    except Exception as e:
        logger.error(f"Failed to save suggestion: {e}")
        await update.message.reply_text(
            "Sorry, I couldn't save your suggestion. Please try again!" if user.get("language", "en") == "en"
            else "ይቅር! ሀሳብዎን ማስቀመጥ አልተቻልም። እባክዎ ይሞክሩ!"
        )
    
    return ConversationHandler.END


async def cmd_parent_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return
    
    lang = user.get("language", "en")
    
    # Generate or retrieve parent token
    parent_token = user.get("parent_token")
    if not parent_token:
        import uuid
        parent_token = str(uuid.uuid4())[:8]
        db.update_user(update.effective_user.id, {"parent_token": parent_token})
    
    from config import BASE_WEB_URL
    if not BASE_WEB_URL:
        await update.message.reply_text(
            "👨‍👩‍👦 **Parent Monitoring**\n\nParent dashboard is currently being set up. Please try again later!" if lang == "en" 
            else "👨‍👩‍👦 **የወላጅ ክትባና**\n\nየወላጅ ዳሽቦርድ በማዋቀር ላይ ነው። እባክዎ ቆይተው ይሞክሩ!"
        )
        return
    
    link = f"{BASE_WEB_URL}/parent/{parent_token}"
    
    if lang == "en":
        msg = (
            f"👨‍👩‍👦 **Parent Monitoring Link**\n\n"
            f"Share this link with your parents to show them your progress:\n"
            f"{link}\n\n"
            f"📊 They can see your study progress, streak, and performance!"
        )
    else:
        msg = (
            f"👨‍👩‍👦 **የወላጅ ክትባና ሊንክ**\n\n"
            f"ይህንን ሊንክ ለወላጆችዎ ያጋሩ እድገትዎን ለማሳየት:\n"
            f"{link}\n\n"
            f"📊 የጥናት እድገትዎን፣ ስትሪክ እና አፈፃፋትዎን ማየት ይችላሉ!"
        )
    
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_radar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please use /start first.")
        return
    
    lang = user.get("language", "en")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    
    # Get weakness data
    weak = db.get_weak_subjects(update.effective_user.id)
    
    if not weak:
        msg = "📡 **Weakness Radar**\n\nNo data yet — answer more questions to see your weakness analysis!" if lang == "en" else "📡 **የድክመት ራዳር**\n\nዳታ የለም — የድክመት ትንበያትን ለማየት ተጨማማር ጥያቄዎችን መልስ!"
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    # Show radar chart
    await update.message.reply_text(build_radar_chart(weak))
    
    # Generate AI analysis
    analysis = await run_blocking(
        ai.generate_weak_radar_analysis, 
        weak, 
        lang
    )
    await update.message.reply_text(analysis)


async def cmd_invite(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Generate a shareable invite link for the bot."""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    lang = user.get("language", "en") if user else "en"
    
    from config import PUBLIC_BOT_USERNAME
    bot_username = PUBLIC_BOT_USERNAME or "EUEEMaster_Bot"
    
    # Deep link for referral tracking in the future (currently just a direct link)
    invite_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    share_url = f"https://t.me/share/url?url={invite_link}&text="
    
    if lang == "en":
        share_text = "Hey! I'm using Abebe to study for my EUEE exams. It's awesome! Join me here: "
        msg = (
            "🤝 **Invite your friends to study with Abebe!**\n\n"
            "Sharing is caring. Help your classmates succeed too.\n\n"
            f"Your personal invite link:\n`{invite_link}`"
        )
        share_btn_text = "📲 Share with Friends"
    else:
        share_text = "ሰላም! ለኢዩኢዩ (EUEE) ፈተና በአቤቤ እየተጠቀምኩ ነው። በጣም ምርጥ ነው! አንተም ተቀላቀለኝ፡ "
        msg = (
            "🤝 **ጓደኞችዎን ከአቤቤ ጋር እንዲያጠኑ ይጋብዙ!**\n\n"
            "ማካፈል ደግነት ነው። የክፍል ጓደኞችዎ እንዲሳካላቸው ይርዱ።\n\n"
            f"የእርስዎ የግል መጋበዣ ሊንክ፡\n`{invite_link}`"
        )
        share_btn_text = "📲 ለጓደኞች ያጋሩ"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(share_btn_text, url=f"{share_url}{share_text}")]
    ])
    
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)


async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your Telegram ID is: `{update.effective_user.id}`", parse_mode="Markdown")


async def cmd_demo_upgrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # FIX: Guard demo path so non-admin users cannot create synthetic upgrade requests in production.
    if not ALLOW_DEMO_UPGRADE and update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Demo upgrades are disabled.")
        return

    user = update.effective_user
    tx_id = f"DEMO_{user.id}_{int(time.time())}"
    db.save_payment_attempt(
        telegram_id=user.id,
        username=user.first_name or "Demo User",
        tx_id=tx_id,
        plan_requested="max",
        screenshot_url="https://via.placeholder.com/150"
    )
    if ADMIN_ID:
        admin_msg = (
            f"🔔 **DEMO UPGRADE REQUEST**\n\n"
            f"👤 **Student:** {user.first_name} (@{user.username or 'N/A'})\n"
            f"🆔 **ID:** `{user.id}`\n"
            f"💎 **Plan:** MAX\n"
            f"🧾 **TX ID:** `{tx_id}`\n\n"
            f"Click buttons below to test approval."
        )
        await ctx.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_msg,
            parse_mode="Markdown",
            reply_markup=kb.admin_approval_keyboard(tx_id)
        )
        await update.message.reply_text("Demo request sent to admin! Check the admin account for buttons.")
    else:
        await update.message.reply_text("ADMIN_USER_ID is not configured in .env. Cannot send demo.")


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text(
        "🛠 **Admin Command Center**\n\nWhat would you like to view?",
        reply_markup=kb.telegram_admin_keyboard(),
        parse_mode="Markdown"
    )


async def cmd_manual_upgrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin command: /manualupgrade <telegram_id> <tier> [days]
    Example: /manualupgrade 123456789 max 365
    Directly sets a user's tier without going through the payment flow.
    Use this to fix users whose approval message was sent but tier write failed.
    """
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    args = ctx.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/manualupgrade <telegram_id> <tier> [days]`\n"
            "Example: `/manualupgrade 123456789 max 365`\n"
            "tier can be: `pro`, `max`, `free`\n"
            "days defaults to 30 (use 365 for yearly)",
            parse_mode="Markdown"
        )
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID. Must be a number.")
        return

    tier = args[1].lower().strip()
    if tier not in {"free", "pro", "max"}:
        await update.message.reply_text("❌ Invalid tier. Use: `free`, `pro`, or `max`.", parse_mode="Markdown")
        return

    try:
        days = int(args[2]) if len(args) >= 3 else 30
    except ValueError:
        days = 30

    import datetime
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)

    # Verify user exists first
    user = db.get_user(target_id)
    if not user:
        await update.message.reply_text(f"❌ No user found with ID `{target_id}`. They must /start the bot first.", parse_mode="Markdown")
        return

    old_tier = user.get("tier", "free")
    db.update_user(target_id, {
        "tier": tier,
        "tier_updated_at": datetime.datetime.now(datetime.timezone.utc) if tier != "free" else None,
        "subscription_expires_at": expires_at if tier != "free" else None,
    })

    # Verify the write succeeded
    refreshed = db.get_user(target_id)
    new_tier = (refreshed or {}).get("tier", "unknown")

    if new_tier == tier:
        await update.message.reply_text(
            f"✅ **Success!**\n\n"
            f"👤 User `{target_id}` ({user.get('name', 'N/A')})\n"
            f"📈 Tier: `{old_tier}` → `{tier}`\n"
            f"📅 Expires: {expires_at.strftime('%B %d, %Y') if tier != 'free' else 'N/A'}",
            parse_mode="Markdown"
        )
        # Notify the student
        try:
            if tier != "free":
                await ctx.bot.send_message(
                    chat_id=target_id,
                    text=(
                        f"🎊 **Your account has been updated!**\n\n"
                        f"You now have **{tier.upper()}** access.\n"
                        f"📅 Expires: {expires_at.strftime('%B %d, %Y')}\n\n"
                        f"Enjoy your studies! 🚀"
                    ),
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.warning(f"Could not notify user {target_id} after manual upgrade: {e}")
    else:
        await update.message.reply_text(f"❌ Write verification failed! Expected `{tier}`, got `{new_tier}`. Check bot logs.", parse_mode="Markdown")


async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.error:
        # Avoid spamming logs with common Telegram "Message not modified" or "Query is too old" errors
        err_msg = str(ctx.error)
        if "Message is not modified" in err_msg or "Query is too old" in err_msg:
            return
            
        logger.error(f"Handler error: {ctx.error}", exc_info=ctx.error)
        
    if not update:
        return

    # Clear processing flag on error
    if ctx.user_data:
        ctx.user_data["is_processing"] = False

    if update.callback_query:
        # For buttons, use a non-intrusive alert if possible, or just ignore if it's already handled
        try:
            await update.callback_query.answer("Something went wrong. Please try again!", show_alert=False)
        except Exception:
            pass
    elif update.effective_message:
        # For text messages, send the friendly fallback
        try:
            await update.effective_message.reply_text("I'm currently optimizing my circuits to help you better. Let's try that again in a moment!")
        except Exception:
            pass
async def cmd_admin_build(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin-only: Pre-generate all notes and check all audio wiring."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    status_msg = await update.message.reply_text("🏗 **Building Subject Packs...**\nStarting full scan of all 11 subjects.")
    
    results = []
    from config import SUBJECTS
    for sub_id, sub_name in SUBJECTS.items():
        try:
            # 1. Check/Build Notes
            notes_files = await run_blocking(notes.ensure_subject_notes_generated, sub_id)
            has_pdf = "✅" if notes_files.get("pdf") else "❌"
            
            # 2. Check Audio
            audio_file = notes.get_local_audio_file(sub_id)
            has_audio = "✅" if audio_file else "❌"
            
            results.append(f"{sub_name}: Notes {has_pdf}, Audio {has_audio}")
        except Exception as e:
            results.append(f"{sub_name}: ⚠️ ERROR - {str(e)[:50]}")
            
    summary = "📦 **Build Status Report**\n\n" + "\n".join(results)
    await status_msg.edit_text(summary)
