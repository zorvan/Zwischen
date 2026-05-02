#!/usr/bin/env python3
"""Modify existing event command handler."""
from __future__ import annotations

import logging
from datetime import datetime
import uuid as uuid_lib

from telegram import Update
from telegram.ext import ContextTypes

from ai.llm import LLMClient
from bot.common.confirmation import (
    invalidate_confirmations_and_notify,
    notify_attendees_of_modification,
)
from bot.common.event_access import (
    get_event_admin_telegram_id,
)
from bot.common.rbac import check_event_visibility_and_get_event
from bot.common.i18n import t, get_user_language
from bot.common.event_notifications import send_event_modification_request_dm
from config.settings import settings
from db.connection import get_session
from db.models import Event

logger = logging.getLogger("coord_bot.modify_event")


def _build_event_draft(event: Event) -> dict[str, object]:
    """Build the current event draft used for LLM patch inference."""
    planning_prefs = (
        event.planning_prefs if isinstance(event.planning_prefs, dict) else {}
    )
    return {
        "description": event.description or "",
        "event_type": event.event_type,
        "scheduled_time": (
            event.scheduled_time.isoformat(timespec="minutes")
            if event.scheduled_time
            else None
        ),
        "duration_minutes": int(event.duration_minutes or 120),
        "min_participants": int(event.min_participants or 2),
        "target_participants": int(
            event.target_participants or event.min_participants or 2
        ),
        "scheduling_mode": "fixed" if event.scheduled_time else "flexible",
        "location_type": planning_prefs.get("location_type"),
        "budget_level": planning_prefs.get("budget_level"),
        "transport_mode": planning_prefs.get("transport_mode"),
    }


def _apply_inferred_event_patch(
    event: Event,
    patch: dict[str, object],
) -> tuple[list[str], list[str]]:
    """Apply inferred patch fields to an event and report what changed."""
    changed_fields: list[str] = []
    reason_parts: list[str] = []

    description = patch.get("description")
    if isinstance(description, str) and description.strip():
        next_description = description.strip()[:500]
        if next_description != (event.description or ""):
            event.description = next_description
            changed_fields.append("description")
            reason_parts.append("description changed")

    event_type = patch.get("event_type")
    if isinstance(event_type, str):
        normalized = event_type.strip().lower()
        if (
            normalized in {"social", "sports", "work"}
            and normalized != event.event_type
        ):
            event.event_type = normalized
            changed_fields.append("event_type")
            reason_parts.append("event type changed")

    min_participants = patch.get("min_participants")
    if min_participants is not None:
        try:
            value = int(min_participants)
            if value >= 1 and value != int(event.min_participants or 0):
                event.min_participants = value
                if int(event.target_participants or 0) < value:
                    event.target_participants = value
                    changed_fields.append("target_participants")
                changed_fields.append("min_participants")
                reason_parts.append("minimum changed")
        except (TypeError, ValueError):
            pass

    target_participants = patch.get("target_participants")
    if target_participants is not None:
        try:
            value = int(target_participants)
            current_min = int(event.min_participants or 1)
            if value >= current_min and value != int(event.target_participants or 0):
                event.target_participants = value
                changed_fields.append("target_participants")
                reason_parts.append("capacity changed")
        except (TypeError, ValueError):
            pass

    duration = patch.get("duration_minutes")
    if duration is not None:
        try:
            value = int(duration)
            if 1 <= value <= 720 and value != int(event.duration_minutes or 120):
                event.duration_minutes = value
                changed_fields.append("duration_minutes")
                reason_parts.append("duration changed")
        except (TypeError, ValueError):
            pass

    if bool(patch.get("clear_time")) and event.scheduled_time is not None:
        event.scheduled_time = None
        changed_fields.append("scheduled_time")
        reason_parts.append("time cleared")

    scheduled_time_iso = patch.get("scheduled_time_iso")
    if scheduled_time_iso is not None:
        try:
            parsed = datetime.fromisoformat(str(scheduled_time_iso).strip())
            if event.scheduled_time != parsed:
                event.scheduled_time = parsed
                changed_fields.append("scheduled_time")
                reason_parts.append("time changed")
        except ValueError:
            pass

    planning_prefs = (
        dict(event.planning_prefs) if isinstance(event.planning_prefs, dict) else {}
    )
    planning_changed = False

    for pref_key in ["location_type", "budget_level", "transport_mode"]:
        new_value = patch.get(pref_key)
        if isinstance(new_value, str) and new_value.strip():
            normalized = new_value.strip().lower()
            old_value = planning_prefs.get(pref_key)
            if old_value != normalized:
                planning_prefs[pref_key] = normalized
                planning_changed = True
                changed_fields.append(pref_key)
                reason_parts.append(f"{pref_key} changed to {normalized}")

    if planning_changed:
        event.planning_prefs = planning_prefs

    return changed_fields, reason_parts


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /modify_event <event_id> <free text patch>."""
    if not update.message or not update.effective_user:
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /modify_event <event_id> <changes>\n\n"
            "Example: /modify_event 12 change time to 2026-03-08 18:30 and minimum to 5"
        )
        return
    try:
        event_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Event ID must be a number.")
        return
    change_text = " ".join(args[1:]).strip()
    if not change_text:
        await update.message.reply_text("❌ Change text cannot be empty.")
        return

    async with get_session(settings.db_url) as session:
        requester_id = int(update.effective_user.id)
        chat_id = update.effective_chat.id if update.effective_chat else None
        is_visible, event, group, error_msg = (
            await check_event_visibility_and_get_event(
                session,
                event_id,
                requester_id,
                telegram_chat_id=chat_id,
                bot=context.bot,
            )
        )
        if not is_visible:
            await update.message.reply_text(f"❌ {error_msg or 'Event not found.'}")
            return
        if event.state in {"locked", "completed", "cancelled"}:
            await update.message.reply_text(
                f"❌ Event {event_id} is {event.state}; modification is not allowed."
            )
            return
        admin_id = get_event_admin_telegram_id(event)
        requester_id = int(update.effective_user.id)
        if admin_id is not None and requester_id != admin_id:
            await _submit_modify_request(
                update=update,
                context=context,
                event=event,
                requester_id=requester_id,
                change_text=change_text,
            )
            return

        draft = _build_event_draft(event)
        llm = LLMClient()
        try:
            patch = await llm.infer_event_draft_patch(draft, change_text)
        finally:
            await llm.close()

        changed_fields, reason_parts = _apply_inferred_event_patch(event, patch)

        if not changed_fields:
            await update.message.reply_text(
                "⚠️ No valid event change inferred from your message."
            )
            return

        invalidated = await invalidate_confirmations_and_notify(
            context=context,
            event=event,
            reason=", ".join(reason_parts) or "event details changed",
        )
        await notify_attendees_of_modification(
            context=context,
            event=event,
            reason=", ".join(reason_parts) or "event details changed",
        )
        await session.commit()

    await update.message.reply_text(
        "✅ Event updated.\n"
        f"Changed fields: {', '.join(changed_fields)}\n"
        f"Confirmations reset: {invalidated}"
    )


async def _submit_modify_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    event,
    requester_id: int,
    change_text: str,
) -> None:
    """Submit a modify request when non-admin user requests changes."""
    admin_id = get_event_admin_telegram_id(event)
    if admin_id is None:
        await update.message.reply_text(
            "❌ Could not identify event admin to approve modification request."
        )
        return

    request_id = uuid_lib.uuid4().hex[:8]
    pending_key = f"modreq_{request_id}"
    context.bot_data.setdefault("pending_modify_requests", {})[pending_key] = {
        "event_id": event.event_id,
        "requester_id": requester_id,
        "requester_username": update.effective_user.username
        or update.effective_user.full_name,
        "change_text": change_text,
        "admin_id": admin_id,
        "created_at": datetime.utcnow().isoformat(),
    }

    await update.message.reply_text(
        f"📩 *Modify request submitted for admin approval*\n\n"
        f"Event ID: {event.event_id}\n"
        f"Requested by: @{update.effective_user.username or update.effective_user.full_name}\n"
        f"Changes: {change_text}\n\n"
        f"Waiting for admin approval...",
        parse_mode="Markdown",
    )

    adminDM_sent = await send_event_modification_request_dm(
        context=context,
        telegram_user_id=admin_id,
        event_data={
            "description": event.description or "",
            "event_type": event.event_type,
            "scheduled_time": (
                event.scheduled_time.isoformat(timespec="minutes")
                if event.scheduled_time
                else None
            ),
            "duration_minutes": int(event.duration_minutes or 120),
            "min_participants": int(event.min_participants or 2),
            "target_participants": int(
                event.target_participants or event.min_participants or 2
            ),
            "location_type": (
                (event.planning_prefs or {}).get("location_type")
                if hasattr(event, "planning_prefs")
                else None
            ),
            "change_text": change_text,
            "requester": update.effective_user.username
            or update.effective_user.full_name,
        },
        event_id=int(event.event_id),
        deadline_info=(
            "Modification requested by "
            f"@{update.effective_user.username or update.effective_user.full_name}: "
            f"{change_text[:200]}"
        ),
        request_id=request_id,
    )

    if not adminDM_sent:
        await update.message.reply_text(
            "⚠️ Could not send DM to admin. Please check your privacy settings."
        )


async def handle_modify_request_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle modify request approval/rejection callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    data = query.data
    if not data.startswith("modreq_"):
        return

    parts = data.split("_")
    if len(parts) != 3:
        return

    request_id = parts[1]
    decision = parts[2]

    pending_root = context.bot_data.get("pending_modify_requests", {})
    pending = pending_root.get(f"modreq_{request_id}")

    if not pending:
        await query.edit_message_text("⚠️ This modify request has expired.")
        return

    admin_id = pending.get("admin_id")
    requester_id = pending.get("requester_id")
    event_id = pending.get("event_id")
    change_text = pending.get("change_text")

    user_lang = get_user_language(query.from_user) if query.from_user else "en"
    if query.from_user.id != admin_id:
        await query.answer(
            t("modify_event_only_admin", lang=user_lang), show_alert=True
        )
        return

    pending_root.pop(f"modreq_{request_id}", None)

    if decision == "reject":
        await query.edit_message_text(
            t("modify_event_rejected", lang=user_lang, event_id=event_id)
        )
        # Notify requester of rejection
        if requester_id:
            try:
                await context.bot.send_message(
                    chat_id=requester_id,
                    text=t(
                        "modify_event_requester_rejected",
                        lang=user_lang,
                        event_id=event_id,
                    ),
                )
            except Exception as e:
                logger.warning(
                    f"Could not notify requester ({requester_id}) of rejection: {e}"
                )
        return

    async with get_session(settings.db_url) as session:
        # Admin is already authorized via pending request check above
        chat_id = getattr(getattr(query, "message", None), "chat_id", None)
        is_visible, event, group, error_msg = (
            await check_event_visibility_and_get_event(
                session,
                event_id,
                query.from_user.id,
                telegram_chat_id=chat_id,
                bot=context.bot,
            )
        )
        if not is_visible:
            await query.edit_message_text(
                t("error_event_not_found", lang=user_lang)
                if not error_msg
                else t("error_event_not_visible", lang=user_lang, error_msg=error_msg)
            )
            return
        if event.state in {"locked", "completed", "cancelled"}:
            await query.edit_message_text(
                t(
                    "modify_event_terminal_state",
                    lang=user_lang,
                    event_id=event_id,
                    state=event.state,
                )
            )
            return

        draft = _build_event_draft(event)
        llm = LLMClient()
        try:
            patch = await llm.infer_event_draft_patch(draft, change_text)
        finally:
            await llm.close()

        changed_fields, reason_parts = _apply_inferred_event_patch(event, patch)

        if not changed_fields:
            # Log the patch for debugging
            logger.warning(
                f"No changes inferred for event {event_id}. "
                f"Change text: '{change_text}'. "
                f"LLM patch: {patch}. "
                f"Current draft: {_build_event_draft(event)}"
            )
            await query.edit_message_text(
                t("modify_event_no_inferred_changes", lang=user_lang)
            )
            return

        reconfirm_needed = await invalidate_confirmations_and_notify(
            context=context,
            event=event,
            reason=", ".join(reason_parts) or "event details changed",
        )
        await notify_attendees_of_modification(
            context=context,
            event=event,
            reason=", ".join(reason_parts) or "event details changed",
        )
        await session.commit()

    await query.edit_message_text(
        t(
            "modify_event_approved",
            lang=user_lang,
            event_id=event_id,
            fields=", ".join(changed_fields),
            count=reconfirm_needed,
        )
    )

    # Notify requester of approval
    if requester_id:
        try:
            await context.bot.send_message(
                chat_id=requester_id,
                text=t(
                    "modify_event_requester_approved",
                    lang=user_lang,
                    event_id=event_id,
                    fields=", ".join(changed_fields),
                ),
            )
        except Exception as e:
            logger.warning(
                f"Could not notify requester ({requester_id}) of approval: {e}"
            )
