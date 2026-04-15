#!/usr/bin/env python3
"""View/add/remove constraints command handler."""

from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from db.models import Event, Constraint
from db.connection import get_session
from db.users import get_or_create_user_id, get_user_id_by_username
from config.settings import settings
from ai.llm import LLMClient
from bot.common.event_access import is_attendee

ALLOWED_CONSTRAINT_TYPES = {"if_joins", "if_attends", "unless_joins"}
CONSTRAINT_TYPE_ALIASES = {
    "if_join": "if_joins",
    "if_attend": "if_attends",
    "unless_join": "unless_joins",
}


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /constraints command - manage constraints."""
    if not update.message or not update.effective_chat:
        return
    if not settings.db_url:
        await update.message.reply_text("❌ Database configuration is unavailable.")
        return

    args = context.args or []
    event_id_raw = args[0] if args else None

    if not event_id_raw:
        await update.message.reply_text(
            "Usage: /constraints <event_id> [view|add|remove|availability]\n\n"
            "Examples:\n"
            "/constraints 123 view\n"
            "/constraints 123 add @alice if_joins\n"
            "/constraints 123 add I only join if @alice joins\n"
            "/constraints 123 availability 2026-03-20 18:00,2026-03-21 10:30\n"
            "/constraints 123 remove 1"
        )
        return

    try:
        event_id = int(event_id_raw)
    except ValueError:
        await update.message.reply_text("❌ Event ID must be a number.")
        return

    action = args[1] if len(args) > 1 else "view"

    if action == "view":
        await view_constraints(update, event_id)
    elif action == "add":
        await add_constraint(update, event_id, context)
    elif action == "availability":
        await add_availability_slots(update, event_id, context)
    elif action == "remove":
        await remove_constraint(update, event_id, context)
    else:
        await update.message.reply_text(
            "❌ Unknown action. Use: view, add, remove, or availability"
        )


async def view_constraints(update: Update, event_id: int) -> None:
    """View constraints for an event."""
    if not update.message:
        return

    async with get_session(settings.db_url) as session:
        result = await session.execute(
            select(Constraint).where(Constraint.event_id == event_id)
        )
        constraints = result.scalars().all()

        if not constraints:
            await update.message.reply_text(
                f"ℹ️ Event {event_id} has no constraints yet."
            )

            return

        msg = f"📋 *Constraints for Event {event_id}*\n\n"
        availability_lines = []
        for c in constraints:
            if c.type.startswith("available:"):
                slot = c.type.replace("available:", "").replace("T", " ")
                availability_lines.append(f"- User {c.user_id}: available at {slot}")
                continue
            if c.target_user_id:
                # Constraint type tells us the condition
                constraint_name = {
                    "if_joins": "joins if target joins",
                    "if_attends": "attends if target attends",
                    "unless_joins": "won't join if target joins",
                }.get(c.type, c.type)
                msg += (
                    f"- User {c.user_id}: '{constraint_name}' "
                    f"(target: User {c.target_user_id}, "
                    f"confidence: {c.confidence})\n"
                )
            else:
                msg += f"- User {c.user_id}: {c.type}\n"

        if availability_lines:
            msg += "\n*Availability slots*\n"
            msg += "\n".join(availability_lines)

        await update.message.reply_text(msg)


async def add_constraint(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Add a constraint to an event."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "Usage:\n"
            "/constraints <event_id> add <target_username|target_user_id> <constraint_type>\n"
            "/constraints <event_id> add <free text>\n"
            "Examples:\n"
            "/constraints 123 add @alice if_joins\n"
            "/constraints 123 add 456 if_joins\n"
            "/constraints 123 add I only join if @alice joins"
        )
        return

    # Explicit structured format (backward compatible)
    structured_candidate = len(args) >= 4 and (
        args[2].strip().startswith("@") or args[2].strip().isdigit()
    )
    if structured_candidate:
        target_input = args[2].strip()
        constraint_type_raw = args[3].strip().lower()
        constraint_type = CONSTRAINT_TYPE_ALIASES.get(
            constraint_type_raw, constraint_type_raw
        )
        if constraint_type in ALLOWED_CONSTRAINT_TYPES:
            await _save_constraint_from_inputs(
                update=update,
                context=context,
                event_id=event_id,
                target_input=target_input,
                constraint_type=constraint_type,
                confidence=0.8,
                summary=None,
            )
            return

    # Natural language format: /constraints <event_id> add <anything>
    free_text = " ".join(args[2:]).strip()
    if not free_text:
        await update.message.reply_text("❌ Constraint text is empty.")
        return
    await _infer_and_confirm_constraint(update, context, event_id, free_text)


async def _infer_and_confirm_constraint(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    free_text: str,
) -> None:
    """Infer constraint from free text and ask user confirmation."""
    if not update.message or context.user_data is None:
        return

    llm = LLMClient()
    try:
        inferred = await llm.infer_constraint_from_text(free_text)
    finally:
        await llm.close()

    constraint_type_raw = str(inferred.get("constraint_type", "")).strip().lower()
    constraint_type = CONSTRAINT_TYPE_ALIASES.get(
        constraint_type_raw, constraint_type_raw
    )
    if constraint_type not in ALLOWED_CONSTRAINT_TYPES:
        await update.message.reply_text(
            "❌ I couldn't infer a valid constraint type.\n"
            "Try wording like: 'I only join if @alice joins'."
        )
        return

    target_username = inferred.get("target_username")
    target_input = f"@{str(target_username).lstrip('@')}" if target_username else ""
    confidence = float(inferred.get("confidence", 0.6))
    summary = str(inferred.get("sanitized_summary", free_text)).strip()

    if not target_input:
        await update.message.reply_text(
            "❌ I couldn't infer the target user from your message.\n"
            "Please include @username in the sentence."
        )
        return

    context.user_data["pending_constraint"] = {
        "event_id": event_id,
        "target_input": target_input,
        "constraint_type": constraint_type,
        "confidence": confidence,
        "summary": summary,
    }
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirm", callback_data="constraint_nl_confirm"
                ),
                InlineKeyboardButton("❌ Cancel", callback_data="constraint_nl_cancel"),
            ]
        ]
    )
    await update.message.reply_text(
        "🤖 *AI Parsed Constraint*\n\n"
        f"Event: {event_id}\n"
        f"Target: {target_input}\n"
        f"Type: {constraint_type}\n"
        f"Confidence: {confidence:.2f}\n"
        f"Summary: {summary}\n\n"
        "Save this constraint?",
        reply_markup=keyboard,
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callbacks for AI-parsed constraints confirmation."""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    if context.user_data is None:
        await query.edit_message_text("❌ User session data unavailable.")
        return

    if data == "constraint_nl_cancel":
        context.user_data.pop("pending_constraint", None)
        await query.edit_message_text("❌ Constraint creation cancelled.")
        return

    if data != "constraint_nl_confirm":
        return

    pending_raw = context.user_data.get("pending_constraint")
    if not isinstance(pending_raw, dict):
        await query.edit_message_text("❌ No pending AI-parsed constraint found.")
        return
    pending = pending_raw
    context.user_data.pop("pending_constraint", None)

    fake_update = update
    await _save_constraint_from_inputs(
        update=fake_update,
        context=context,
        event_id=int(pending.get("event_id")),
        target_input=str(pending.get("target_input", "")),
        constraint_type=str(pending.get("constraint_type", "")),
        confidence=float(pending.get("confidence", 0.7)),
        summary=str(pending.get("summary", "")),
        edit_via_query=True,
    )


async def _save_constraint_from_inputs(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    event_id: int,
    target_input: str,
    constraint_type: str,
    confidence: float,
    summary: str | None,
    edit_via_query: bool = False,
) -> None:
    """Save resolved constraint payload to database."""
    message = update.message
    query = update.callback_query
    if not update.effective_user:
        return

    async with get_session(settings.db_url) as session:
        from sqlalchemy.orm import selectinload

        result = await session.execute(
            select(Event)
            .options(selectinload(Event.participants))
            .where(Event.event_id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            if edit_via_query and query:
                await query.edit_message_text("❌ Event not found.")
            elif message:
                await message.reply_text("❌ Event not found.")

            return
        chat = update.effective_chat
        is_private_chat = bool(chat and chat.type == "private")
        requester_tg_id = int(update.effective_user.id)
        if is_private_chat:
            if not is_attendee(event, requester_tg_id):
                error_msg = "❌ Only interested attendees can add private constraints."
                if edit_via_query and query:
                    await query.edit_message_text(error_msg)
                elif message:
                    await message.reply_text(error_msg)
                return

        source_user_id = await get_or_create_user_id(
            session,
            telegram_user_id=update.effective_user.id,
            display_name=update.effective_user.full_name,
            username=update.effective_user.username,
        )
        if target_input.startswith("@"):
            target_user_id = await get_user_id_by_username(session, target_input)
            if target_user_id is None:
                # Fallback: try resolving username via Telegram API and store it.
                try:
                    target_chat = await context.bot.get_chat(target_input)
                    target_user_id = await get_or_create_user_id(
                        session,
                        telegram_user_id=target_chat.id,
                        display_name=getattr(target_chat, "full_name", None),
                        username=getattr(target_chat, "username", None),
                    )
                except Exception:
                    error_msg = (
                        f"❌ User {target_input} not found in bot records "
                        "and could not be resolved from Telegram API."
                    )
                    if edit_via_query and query:
                        await query.edit_message_text(error_msg)
                    elif message:
                        await message.reply_text(error_msg)
                    return
            target_label = target_input
        else:
            try:
                target_telegram_user_id = int(target_input)
            except ValueError:
                error_msg = "❌ Target must be @username or numeric Telegram user ID."
                if edit_via_query and query:
                    await query.edit_message_text(error_msg)
                elif message:
                    await message.reply_text(error_msg)
                return

            target_user_id = await get_or_create_user_id(
                session,
                telegram_user_id=target_telegram_user_id,
                display_name=None,
            )
            target_label = str(target_telegram_user_id)

        constraint = Constraint(
            user_id=source_user_id,
            target_user_id=target_user_id,
            event_id=event_id,
            type=constraint_type,
            confidence=confidence,
        )
        session.add(constraint)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            error_msg = (
                "❌ Failed to add constraint due to database validation.\n"
                "Please verify target user and constraint type."
            )
            if edit_via_query and query:
                await query.edit_message_text(error_msg)
            elif message:
                await message.reply_text(error_msg)
            return

        success_msg = (
            f"✅ Constraint added to event {event_id}!\n\n"
            f"Type: {constraint_type}\n"
            f"Target: {target_label}"
        )
        if summary:
            success_msg += f"\nSummary: {summary}"
        if edit_via_query and query:
            await query.edit_message_text(success_msg)
        elif message:
            await message.reply_text(success_msg)


async def remove_constraint(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Remove a constraint from an event."""
    if not update.message:
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: /constraints <event_id> remove <constraint_id>\n"
            "Example: /constraints 123 remove 1"
        )
        return

    try:
        constraint_id = int(args[2])
    except ValueError:
        await update.message.reply_text("❌ Constraint ID must be a number.")
        return

    async with get_session(settings.db_url) as session:
        result = await session.execute(
            Constraint.__table__.delete().where(
                Constraint.constraint_id == constraint_id,
                Constraint.event_id == event_id,
            )
        )
        await session.commit()

        affected = result.rowcount or 0
        if affected > 0:
            await update.message.reply_text(
                f"✅ Constraint {constraint_id} removed from event {event_id}."
            )
        else:
            await update.message.reply_text(
                f"❌ Constraint {constraint_id} not found for event {event_id}."
            )


def _parse_slot(raw: str) -> str:
    """Parse one availability slot and return normalized ISO minute string."""
    cleaned = raw.strip()
    if not cleaned:
        raise ValueError("empty slot")
    cleaned = cleaned.replace("T", " ")
    parsed = datetime.strptime(cleaned, "%Y-%m-%d %H:%M")
    return parsed.strftime("%Y-%m-%dT%H:%M")


async def add_availability_slots(
    update: Update, event_id: int, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Add one or more availability slots for the current user."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "Usage: /constraints <event_id> availability "
            "<YYYY-MM-DD HH:MM,YYYY-MM-DD HH:MM>\n"
            "Example: /constraints 123 availability "
            "2026-03-20 18:00,2026-03-21 10:30"
        )
        return

    slots_input = " ".join(args[2:])
    raw_slots = [s.strip() for s in slots_input.split(",") if s.strip()]
    if not raw_slots:
        await update.message.reply_text(
            "❌ No slots found. Provide comma-separated values."
        )
        return

    normalized_slots: list[str] = []
    try:
        for slot in raw_slots:
            normalized = _parse_slot(slot)
            if normalized not in normalized_slots:
                normalized_slots.append(normalized)
    except ValueError:
        await update.message.reply_text("❌ Invalid slot format. Use YYYY-MM-DD HH:MM")
        return

    async with get_session(settings.db_url) as session:
        from sqlalchemy.orm import selectinload

        event_result = await session.execute(
            select(Event)
            .options(selectinload(Event.participants))
            .where(Event.event_id == event_id)
        )
        event = event_result.scalar_one_or_none()
        if not event:
            await update.message.reply_text("❌ Event not found.")
            return
        chat = update.effective_chat
        is_private_chat = bool(chat and chat.type == "private")
        requester_tg_id = int(update.effective_user.id)
        if is_private_chat:
            if not is_attendee(event, requester_tg_id):
                await update.message.reply_text(
                    "❌ Only interested attendees can add private availability."
                )
                return

        source_user_id = await get_or_create_user_id(
            session,
            telegram_user_id=update.effective_user.id,
            display_name=update.effective_user.full_name,
            username=update.effective_user.username,
        )

        added = 0
        for slot in normalized_slots:
            existing = await session.execute(
                select(Constraint).where(
                    Constraint.event_id == event_id,
                    Constraint.user_id == source_user_id,
                    Constraint.target_user_id.is_(None),
                    Constraint.type == f"available:{slot}",
                )
            )
            if existing.scalar_one_or_none():
                continue
            session.add(
                Constraint(
                    user_id=source_user_id,
                    target_user_id=None,
                    event_id=event_id,
                    type=f"available:{slot}",
                    confidence=1.0,
                )
            )
            added += 1

        await session.commit()

    await update.message.reply_text(
        f"✅ Added {added} availability slot(s) for event {event_id}.\n"
        "Run /suggest_time {event_id} after attendees add slots.".replace(
            "{event_id}", str(event_id)
        )
    )
