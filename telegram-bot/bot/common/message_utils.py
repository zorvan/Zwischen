#!/usr/bin/env python3
"""Message utilities to safely send messages without reply issues."""

from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram._message import Message as TelegramMessage


async def safe_send_message(
    update: Update | None,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    chat_id: int | None = None,
    parse_mode: str | None = None,
    reply_markup=None,
    disable_web_page_preview: bool | None = None,
) -> Message:
    """
    Safely send a message without trying to reply to the triggering message.

    This avoids the "Message to be replied not found" error that occurs when
    the bot tries to reply to messages in group chats where the message context
    might not be accessible.

    Args:
        update: The update object (optional if chat_id is provided)
        context: The context object for accessing the bot
        text: The message text to send
        chat_id: Optional chat ID. If not provided, uses update.effective_chat.id
        parse_mode: Optional parse mode (HTML, Markdown, etc.)
        reply_markup: Optional reply markup
        disable_web_page_preview: Optional disable link preview

    Returns:
        The sent Message object
    """
    if chat_id is None and update is not None:
        if hasattr(update, "effective_chat") and update.effective_chat:
            chat_id = update.effective_chat.id
        elif hasattr(update, "message") and update.message and update.message.chat:
            chat_id = update.message.chat.id

    if chat_id is None:
        raise ValueError("chat_id must be provided or extractable from update")

    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


def patch_message_reply():
    """
    Monkey-patch telegram Message.reply_text to avoid reply_parameters issues.

    This ensures that reply_text() sends messages without trying to reply,
    which avoids "Message to be replied not found" errors in group chats.
    """
    original_reply_text = TelegramMessage.reply_text

    async def patched_reply_text(
        self,
        text: str,
        parse_mode: str | None = None,
        entities=None,
        link_preview_options=None,
        reply_markup=None,
        disable_web_page_preview: bool | None = None,
        reply_parameters=None,
        **kwargs,
    ):
        return await original_reply_text(
            self,
            text=text,
            parse_mode=parse_mode,
            entities=entities,
            link_preview_options=link_preview_options,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
            reply_parameters=None,
            **kwargs,
        )

    TelegramMessage.reply_text = patched_reply_text


async def safe_reply_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    parse_mode: str | None = None,
    reply_markup=None,
    disable_web_page_preview: bool | None = None,
) -> Message:
    """
    Reply to a message without using reply_parameters.

    This sends a regular message instead of trying to reply, avoiding
    "Message to be replied not found" errors.

    Args:
        update: The update object
        context: The context object for accessing the bot
        text: The message text to send
        parse_mode: Optional parse mode (HTML, Markdown, etc.)
        reply_markup: Optional reply markup
        disable_web_page_preview: Optional disable link preview

    Returns:
        The sent Message object
    """
    if not update.message or not update.effective_chat:
        raise ValueError("Update must have a message and effective chat")

    return await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )
