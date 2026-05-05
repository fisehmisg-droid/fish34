"""Telegram reply and inline keyboards."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from config import PUBLIC_BOT_USERNAME, MODEL_EXAM_LIMITS


def lang_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["English", "አማርኛ"]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )


def subject_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    rows = [
        ["📐 Math", "⚛️ Physics", "🧪 Chemistry"],
        ["🧬 Biology", "📖 English", "🏛️ Civics"],
        ["📜 History", "🌍 Geography", "💰 Economics"],
        ["🌾 Agriculture", "💻 IT"],
        ["/menu"],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def main_menu_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    if lang == "en":
        rows = [
            ["🎯 Practice", "🎲 Random Challenge"],
            ["📝 Mock Exam", "🎧 Audio Lesson"],
            ["📒 Study Notes", "📚 E-Book / Textbooks"],
            ["🗂️ Flashcards", "🧠 Memory Trick"],
            ["📊 My Progress", "🏆 Leaderboard"],
            ["⚔️ Battle Mode", "🤝 Invite Friend"],
            ["🤫 Confession Box", "👾 Boss Fight"],
            ["🔮 Score Predictor", "💡 Exam Tips"],
            ["📡 Weak Radar", "👨‍👩‍👦 Parent Link"],
            ["📝 Model Exam", "👑 Upgrade"],
            ["📝 Review Sheet", "💡 Feature Suggest"],
            ["/menu"],
        ]
    else:
        # Amharic versions with matching emojis
        rows = [
            ["🎯 ልምምድ", "🎲 የዘፈቀደ ጥያቄ"],
            ["📝 የሙከራ ፈተና", "🎧 የኦዲዮ ትምህርት"],
            ["📒 ማስታወሻ ማስታወቂያ", "📚 ኢ-መጽሐፍት"],
            ["🗂️ ፍላሽ ካርዶች", "🧠 የማስታወሻ ዘዴ"],
            ["📊 እድገቴ", "🏆 ሰንጠረዥ"],
            ["⚔️ የውድድር ሁነታ", "🤝 ጓደኛ ይጋብዙ"],
            ["🤫 የምስጢር ሳጥን", "👾 የቦስ ውጊያ"],
            ["🔮 ውጤት ትንቢት", "💡 የፈተና ምክሮች"],
            ["📡 የድክመት ራዳር", "👨‍👩‍👦 የወላጅ ሊንክ"],
            ["📝 ሞዴል ፈተና", "👑 አሳድግ"],
            ["📝 የክለሳ ወረቀት", "💡 አዲስ ሀሳብ"],
            ["/menu"],
        ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def exam_options_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Quick (20)", callback_data="exam_20"),
                InlineKeyboardButton("Full (50)", callback_data="exam_50"),
            ],
            [InlineKeyboardButton("Timed (100)", callback_data="exam_100")],
        ]
    )


def after_answer_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("ELI10", callback_data="eli10"),
                InlineKeyboardButton("Read Aloud 🔊", callback_data="read_aloud"),
                InlineKeyboardButton("Next Question", callback_data="next_q"),
            ],
            [InlineKeyboardButton("Memory Trick", callback_data="mnemonic_last")],
        ]
    )


def upgrade_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Pro (100 Br/m)", callback_data="upgrade_pro_monthly"),
                InlineKeyboardButton("Pro (1200 Br/y)", callback_data="upgrade_pro_yearly")
            ],
            [
                InlineKeyboardButton("Max (200 Br/m)", callback_data="upgrade_max_monthly"),
                InlineKeyboardButton("Max (2200 Br/y)", callback_data="upgrade_max_yearly")
            ],
        ]
    )


def mcq_keyboard(options: dict) -> InlineKeyboardMarkup:
    """Display answer choices SIDEWAYS (horizontal row) with a Next button."""
    option_row = []
    for key in ["A", "B", "C", "D"]:
        if key in options:
            option_row.append(InlineKeyboardButton(key, callback_data=f"mcq_{key}"))
    option_row.append(InlineKeyboardButton("Next ➡️", callback_data="next_q"))
    return InlineKeyboardMarkup([option_row])


def battle_keyboard(battle_id: str) -> InlineKeyboardMarkup:
    if PUBLIC_BOT_USERNAME:
        deep_link = f"https://t.me/{PUBLIC_BOT_USERNAME}?start=battle_{battle_id}"
        return InlineKeyboardMarkup([[InlineKeyboardButton("Join Battle", url=deep_link)]])
    return InlineKeyboardMarkup([[InlineKeyboardButton("Join Battle", callback_data=f"join_battle_{battle_id}")]])


def flashcard_keyboard(index: int, total: int) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton("Flip Card", callback_data=f"flip_{index}")]]
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton("Prev", callback_data=f"fc_prev_{index}"))
    if index < total - 1:
        nav.append(InlineKeyboardButton("Next", callback_data=f"fc_next_{index}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(buttons)


def notes_chapter_keyboard(subject: str, lang: str = "en") -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for chapter_number in range(1, 6):
        row.append(InlineKeyboardButton(f"Chapter {chapter_number}", callback_data=f"chapter_{subject}_{chapter_number}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("Full Notes", callback_data=f"fullnotes_{subject}")])
    return InlineKeyboardMarkup(buttons)
def model_selection_keyboard(subject: str, lang: str = "en", tier: str = "free") -> InlineKeyboardMarkup:
    buttons = []
    # Tier-based limits
    limit = MODEL_EXAM_LIMITS.get(tier, 0)
    
    if limit == 0:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Upgrade to Access Models", callback_data="upgrade_pro_monthly")]])

    # Show models in a grid (5 columns)
    row = []
    for i in range(1, limit + 1):
        row.append(InlineKeyboardButton(f"M{i}", callback_data=f"model_{subject}_{i}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def telegram_admin_keyboard() -> InlineKeyboardMarkup:
    from config import BASE_WEB_URL
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 View Stats", callback_data="admin_view_stats")],
            [InlineKeyboardButton("⏳ Pending Upgrades", callback_data="admin_view_pending")],
            [InlineKeyboardButton("💡 Feature Suggestions", callback_data="admin_view_suggestions")],
        ]
    )


def admin_approval_keyboard(tx_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"admin_approve_{tx_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{tx_id}"),
            ]
        ]
    )
