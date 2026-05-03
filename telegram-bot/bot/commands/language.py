"""Language preference command handler."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.models import User
from bot.common.i18n import t, SUPPORTED_LANGS, DEFAULT_LANG
from bot.common.user_preferences import set_language_preference


LANGUAGES = {
    "en": {"name": "English", "native": "English", "flag": "🇬🇧"},
    "fa": {"name": "Persian", "native": "فارسی", "flag": "🇮🇷"},
}


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /language command - show language selection keyboard."""
    if not update.effective_user:
        return

    user_lang = "en"  # Default for this command's UI
    db_url = settings.db_url or ""

    async with get_session(db_url) as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == update.effective_user.id)
        )
        db_user = result.scalar_one_or_none()

        if not db_user:
            db_user = User(
                telegram_user_id=update.effective_user.id,
                display_name=update.effective_user.full_name,
            )
            session.add(db_user)
            await session.flush()

        # Get current language
        from bot.common.user_preferences import get_language_preference

        current_lang = await get_language_preference(session, db_user.user_id)
        if not current_lang:
            current_lang = DEFAULT_LANG

    # Build keyboard
    keyboard = []
    for lang_code, lang_info in LANGUAGES.items():
        label = f"{lang_info['flag']} {lang_info['native']}"
        if lang_code == current_lang:
            label += " ✓"
        keyboard.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"lang_{lang_code}",
                )
            ]
        )

    await context.bot.send_message(
        chat_id=(
            update.effective_chat.id
            if update.effective_chat
            else update.effective_user.id
        ),
        text=t("language_select_title", lang=user_lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle language selection callback."""
    query = update.callback_query
    if not query or not query.data.startswith("lang_"):
        return

    await query.answer()

    lang_code = query.data.replace("lang_", "")
    if lang_code not in SUPPORTED_LANGS:
        await query.edit_message_text(t("language_invalid", lang="en"))
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == query.from_user.id)
        )
        db_user = result.scalar_one_or_none()

        if not db_user:
            db_user = User(
                telegram_user_id=query.from_user.id,
                display_name=query.from_user.full_name,
            )
            session.add(db_user)
            await session.flush()

        await set_language_preference(session, db_user.user_id, lang_code)
        await session.commit()

    # Cache in user_data for fast lookup without DB query
    if context.user_data is not None:
        context.user_data["language"] = lang_code

    lang_info = LANGUAGES[lang_code]
    await query.edit_message_text(
        t(
            "language_changed",
            lang="en",
            flag=lang_info["flag"],
            native=lang_info["native"],
        ),
        parse_mode="HTML",
    )
