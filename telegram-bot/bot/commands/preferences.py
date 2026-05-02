"""User preferences command handler."""

from __future__ import annotations

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from config.settings import settings
from db.connection import get_session
from db.models import User
from bot.common.user_preferences import (
    get_user_preferences,
    create_or_update_user_preferences,
    get_privacy_defaults,
)
from bot.common.i18n import t, get_user_language


TIME_PREFERENCES = ["any", "morning", "afternoon", "evening", "night"]
ACTIVITY_PREFERENCES = ["any", "social", "sports", "work", "outdoor", "indoor"]
BUDGET_PREFERENCES = ["any", "free", "low", "medium", "high"]
LOCATION_PREFERENCES = ["any", "home", "outdoor", "cafe", "office", "gym"]
TRANSPORT_PREFERENCES = ["any", "walk", "public_transit", "drive"]


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /preferences command - view and set user preferences."""
    if not update.message or not update.effective_user:
        return

    user_lang = (
        get_user_language(update.message.from_user)
        if update.message.from_user
        else "en"
    )
    args = context.args or []
    if args and args[0].lower() == "wizard":
        await handle_wizard(update, context, user_lang)
        return
    if len(args) >= 2:
        await set_preference(update, context, user_lang)
        return

    user = update.effective_user
    telegram_user_id = user.id
    display_name = user.full_name

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        # Get or create user
        result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        db_user = result.scalar_one_or_none()

        if not db_user:
            db_user = User(
                telegram_user_id=telegram_user_id,
                display_name=display_name,
            )
            session.add(db_user)
            await session.flush()

        # Get user preferences
        preferences = await get_user_preferences(session, db_user.user_id)

        # Show current preferences
        if not preferences:
            await update.message.reply_text(t("preferences_not_set", lang=user_lang))
            return

        # Show preferences with privacy indicators
        privacy = preferences.privacy_settings or {}

        def format_preference(pref_type: str, value: str) -> str:
            privacy_settings = privacy.get(pref_type, get_privacy_defaults(pref_type))
            if privacy_settings.get("private", False):
                return f"{pref_type}: {value} (private)"
            return f"{pref_type}: {value}"

        lines = [
            t("profile_title", lang=user_lang),
            "",
            format_preference("time", preferences.time_preference or "any"),
            format_preference("activity", preferences.activity_preference or "any"),
            format_preference("budget", preferences.budget_preference or "any"),
            format_preference(
                "location_type", preferences.location_type_preference or "any"
            ),
            format_preference("transport", preferences.transport_preference or "any"),
            "",
            f"Last updated: {preferences.last_updated}",
        ]

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_wizard(
    update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str = "en"
) -> None:
    """Handle /preferences wizard - interactive preference setup."""
    if not update.message or not update.effective_user:
        return

    # Start preference wizard
    await update.message.reply_text(
        t("preferences_wizard_title", lang=lang),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        t("preferences_wizard_time_any", lang=lang),
                        callback_data="pref_wizard_time_any",
                    ),
                    InlineKeyboardButton(
                        t("preferences_wizard_time_morning", lang=lang),
                        callback_data="pref_wizard_time_morning",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        t("preferences_wizard_time_afternoon", lang=lang),
                        callback_data="pref_wizard_time_afternoon",
                    ),
                    InlineKeyboardButton(
                        t("preferences_wizard_time_evening", lang=lang),
                        callback_data="pref_wizard_time_evening",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        t("preferences_wizard_time_night", lang=lang),
                        callback_data="pref_wizard_time_night",
                    ),
                ],
            ]
        ),
        parse_mode="Markdown",
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries for preference wizard."""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data
    if not data.startswith("pref_wizard_"):
        return

    parts = data.split("_")
    if len(parts) < 4:
        return

    pref_type = parts[2]  # time, activity, etc.
    pref_value = parts[3]  # the selected value

    user_lang = get_user_language(query.from_user) if query.from_user else "en"
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        user = query.from_user
        if not user:
            return

        # Get user ID
        result = await session.execute(
            select(User).where(User.telegram_user_id == user.id)
        )
        db_user = result.scalar_one_or_none()

        if not db_user:
            await query.edit_message_text(
                t("preferences_user_not_found", lang=user_lang)
            )
            return

        # Update preference
        await create_or_update_user_preferences(
            session=session,
            telegram_user_id=db_user.user_id,
            **{f"{pref_type}_preference": pref_value},
        )

        await session.commit()

        await query.edit_message_text(
            t("preferences_saved", lang=user_lang, type=pref_type, value=pref_value),
            parse_mode="Markdown",
        )


async def set_preference(
    update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str = "en"
) -> None:
    """Set a specific preference value."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(t("preferences_usage", lang=lang))
        return

    pref_type = args[0].lower()
    pref_value = args[1].lower()

    # Validate preference type
    valid_types = {
        "time": TIME_PREFERENCES,
        "activity": ACTIVITY_PREFERENCES,
        "budget": BUDGET_PREFERENCES,
        "location": LOCATION_PREFERENCES,
        "transport": TRANSPORT_PREFERENCES,
    }

    if pref_type not in valid_types:
        await update.message.reply_text(
            t(
                "preferences_invalid_type",
                lang=lang,
                types=", ".join(valid_types.keys()),
            )
        )
        return

    if pref_value not in valid_types[pref_type]:
        await update.message.reply_text(
            t(
                "preferences_invalid_value",
                lang=lang,
                type=pref_type,
                values=", ".join(valid_types[pref_type]),
            )
        )
        return

    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        user = update.effective_user
        result = await session.execute(
            select(User).where(User.telegram_user_id == user.id)
        )
        db_user = result.scalar_one_or_none()

        if not db_user:
            await update.message.reply_text(t("preferences_user_not_found", lang=lang))
            return

        # Update preference
        await create_or_update_user_preferences(
            session=session,
            telegram_user_id=db_user.user_id,
            **{
                f"{pref_type.replace('location', 'location_type')}_preference": pref_value
            },
        )

        await session.commit()

        await update.message.reply_text(
            t("preferences_updated", lang=lang, type=pref_type, value=pref_value),
            parse_mode="Markdown",
        )
