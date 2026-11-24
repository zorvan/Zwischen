"""/privacy and /delete_account: the retention policy, in the user's hands.

/privacy states docs/RETENTION_POLICY.md in product terms. /delete_account
exercises the right to erasure: after an explicit confirmation it runs
RetentionService.erase_user and then scrubs what Telegram-side state still
mentions the user (conversation data, rolling chat history, pending
modify requests), which the database cascade cannot reach.
"""

from __future__ import annotations

import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.common.i18n import get_user_language, t
from bot.common.safe_edit import safe_edit_message
from bot.services.retention_service import RetentionService
from config.settings import settings
from db.connection import get_session
from db.identity import get_telegram_user
from db.models import AuthProvider

logger = logging.getLogger("coord_bot.account")

CONFIRM = "acct_delete_yes"
CANCEL = "acct_delete_no"


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /privacy: what is kept, and for how long."""
    if not update.message:
        return
    lang = await get_user_language(update.effective_user, user_data=context.user_data)
    await update.message.reply_html(t("privacy_policy", lang=lang))


async def delete_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete_account: ask for confirmation, in private only."""
    if not update.message or not update.effective_user:
        return
    lang = await get_user_language(update.effective_user, user_data=context.user_data)
    chat = update.effective_chat
    if chat is None or chat.type != "private":
        await update.message.reply_text(t("delete_account_dm_only", lang=lang))
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("delete_account_button_confirm", lang=lang),
                    callback_data=CONFIRM,
                )
            ],
            [
                InlineKeyboardButton(
                    t("delete_account_button_cancel", lang=lang),
                    callback_data=CANCEL,
                )
            ],
        ]
    )
    await update.message.reply_html(
        t("delete_account_confirm", lang=lang), reply_markup=keyboard
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm or cancel an account deletion."""
    query = update.callback_query
    if query is None or query.from_user is None:
        return
    await query.answer()
    lang = await get_user_language(query.from_user, user_data=context.user_data)

    if query.data == CANCEL:
        await safe_edit_message(query, t("delete_account_cancelled", lang=lang))
        return
    if query.data != CONFIRM:
        return

    telegram_id = int(query.from_user.id)
    try:
        async with get_session(settings.db_url or "") as session:
            user = await get_telegram_user(session, telegram_id)
            if user is None:
                erased = None
            else:
                erased = await RetentionService(session).erase_user(int(user.user_id))
                await session.commit()
    except Exception:
        logger.exception("Account erasure failed")
        await safe_edit_message(query, t("delete_account_failed", lang=lang))
        return

    telegram_ids = {telegram_id}
    if erased is not None:
        telegram_ids.update(
            int(pid)
            for pid in erased.provider_ids(AuthProvider.telegram.value)
            if pid.lstrip("-").isdigit()
        )
    # This callback runs in the erased user's own context.
    if isinstance(context.user_data, dict):
        context.user_data.clear()
    for tid in telegram_ids:
        await scrub_telegram_state(context, tid)

    if erased is None:
        await safe_edit_message(query, t("delete_account_not_found", lang=lang))
        return
    logger.info(
        "Account erased",
        extra={
            "user_id": erased.user_id,
            "identities": len(erased.identities),
            "fragments": erased.memory_fragments_removed,
        },
    )
    await safe_edit_message(query, t("delete_account_done", lang=lang))


async def scrub_telegram_state(context: Any, telegram_id: int) -> None:
    """Remove a Telegram user from state the database cascade cannot see."""
    bot_data = getattr(context, "bot_data", None)
    if isinstance(bot_data, dict):
        history = bot_data.get("chat_history")
        if isinstance(history, dict):
            for chat_id, entries in list(history.items()):
                history[chat_id] = [
                    entry
                    for entry in entries
                    if not (
                        isinstance(entry, dict) and entry.get("user_id") == telegram_id
                    )
                ]
        pending = bot_data.get("pending_modify_requests")
        if isinstance(pending, dict):
            for key, entry in list(pending.items()):
                if isinstance(entry, dict) and telegram_id in (
                    entry.get("requester_id"),
                    entry.get("admin_id"),
                ):
                    pending.pop(key, None)

    application = getattr(context, "application", None)
    if application is not None:
        try:
            application.drop_user_data(telegram_id)
        except (KeyError, AttributeError):
            pass
        persistence = getattr(application, "persistence", None)
        if persistence is not None:
            try:
                await persistence.drop_user_data(telegram_id)
            except Exception:
                logger.warning("Could not drop persisted user data", exc_info=True)
