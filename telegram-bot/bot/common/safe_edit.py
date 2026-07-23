"""Resilient wrapper around CallbackQuery.edit_message_text.

Editing a Telegram message fails routinely for reasons that are not bugs:

- "Message is not modified" — the user tapped a button that re-renders
  identical content. Extremely common in a panel-driven UI.
- Flood control (RetryAfter) — the bot edited too quickly.
- "Message to edit not found" — the user deleted the message.

Unprotected, each of these raises out of the handler into the global error
handler: the interaction silently does nothing and the log fills with noise.
This helper absorbs them and reports success as a bool.

Previously this logic existed only as a private function inside
bot/commands/event_creation.py, so the other ~95 call sites across the panel,
menus, mentions and waitlist handlers had no protection at all.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any

from telegram import CallbackQuery
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

logger = logging.getLogger(__name__)

# Telegram phrases these as prose; there are no error codes to match on.
_NOT_MODIFIED = "message is not modified"
_GONE = (
    "message to edit not found",
    "message can't be edited",
    "message identifier is not specified",
)

# Cap the flood-control wait. Telegram occasionally returns very long values;
# blocking a handler for minutes is worse than dropping the edit.
MAX_RETRY_AFTER = 30.0


def _retry_seconds(exc: RetryAfter) -> float:
    """Seconds to wait for a RetryAfter.

    PTB types retry_after as int | timedelta depending on version and
    configuration, so float() alone raises TypeError on the timedelta form.
    """
    value = exc.retry_after
    if isinstance(value, timedelta):
        return value.total_seconds()
    return float(value)


async def _quiet_answer(query: CallbackQuery, text: str = "", **kwargs: Any) -> None:
    """Answer a callback query, ignoring failures.

    The query may already have been answered or aged out; neither should turn
    a cosmetic notice into a raised exception.
    """
    try:
        await query.answer(text, **kwargs)
    except Exception:  # noqa: BLE001 - best-effort notification only
        logger.debug("callback answer failed (already answered or expired)")


async def safe_edit_message(query: CallbackQuery, text: str, **kwargs: Any) -> bool:
    """Edit the message behind ``query``, absorbing routine Telegram failures.

    Returns True if the message now shows ``text``, False if the edit was
    skipped (content unchanged, message gone, or rate limited beyond retry).
    Never raises for the expected failure modes above.
    """
    try:
        await query.edit_message_text(text, **kwargs)
        return True

    except BadRequest as exc:
        message = str(exc).lower()
        if _NOT_MODIFIED in message:
            await _quiet_answer(query, "ℹ️ Already up to date.")
            return False
        if any(phrase in message for phrase in _GONE):
            logger.info("Skipping edit; message no longer editable: %s", exc)
            return False
        raise

    except RetryAfter as exc:
        delay = min(_retry_seconds(exc), MAX_RETRY_AFTER)
        logger.warning("Flood control; retrying edit in %.1fs", delay)
        await asyncio.sleep(delay)
        try:
            await query.edit_message_text(text, **kwargs)
            return True
        except RetryAfter:
            logger.error("Flood control persisted after %.1fs; giving up", delay)
            await _quiet_answer(
                query,
                "⏳ Too many requests. Please try again in a moment.",
                show_alert=True,
            )
            return False
        except BadRequest as retry_exc:
            if _NOT_MODIFIED in str(retry_exc).lower():
                await _quiet_answer(query, "ℹ️ Already up to date.")
                return False
            raise

    except (TimedOut, Forbidden) as exc:
        # TimedOut: the edit may well have landed; retrying risks duplicates.
        # Forbidden: the user blocked the bot or left the chat.
        logger.info("Edit not delivered (%s): %s", type(exc).__name__, exc)
        return False
