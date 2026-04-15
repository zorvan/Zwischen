#!/usr/bin/env python3
"""Event finalization and DM handling."""

from datetime import datetime
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, CallbackQuery
from telegram.ext import ContextTypes

from sqlalchemy import select

from ai.llm import LLMClient
from config.settings import settings
from bot.common.event_formatters import (
    format_scheduled_time,
    format_commit_by,
    format_duration,
    format_location_type,
    format_budget_level,
    format_transport_mode,
    format_date_preset,
    format_time_window,
)
from bot.common.event_notifications import send_event_invitation_dm
from bot.common.scheduling import find_user_event_conflict
from bot.services.event_live_card_service import EventLiveCardService
from bot.services.event_hashtag_service import EventHashtagService
from db.connection import get_session
from db.models import Event, Group, User
from db.users import get_user_id_by_username


DEFAULT_COMMIT_BY_OFFSET_HOURS = 12
TIME_WINDOWS = {
    "early-morning": ["04:00", "05:00", "06:00", "07:00"],
    "morning": ["08:00", "09:00", "10:00", "11:00"],
    "afternoon": ["12:00", "13:00", "14:00", "15:00"],
    "evening": ["17:00", "18:00", "19:00", "20:00"],
    "night": ["21:00", "22:00", "23:00"],
}
LOCATION_PRESETS = [
    ("🏠 Home", "home"),
    ("🌳 Outdoor", "outdoor"),
    ("☕ Cafe", "cafe"),
    ("🏢 Office", "office"),
    ("🏋️ Gym", "gym"),
]
BUDGET_PRESETS = [
    ("🆓 Free", "free"),
    ("💸 Low", "low"),
    ("💰 Medium", "medium"),
    ("💎 High", "high"),
]
TRANSPORT_PRESETS = [
    ("🚶 Walk", "walk"),
    ("🚌 Public Transit", "public_transit"),
    ("🚗 Drive", "drive"),
    ("🤝 Any", "any"),
]
ALLOWED_EVENT_TYPES = {"social", "sports", "work"}
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _escape_md(text: str) -> str:
    """Escape text for safe Telegram Markdown parsing."""
    return (
        str(text)
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def compute_commit_by_time(scheduled_time: datetime | None) -> datetime | None:
    """Derive default commit-by deadline from scheduled time."""
    if scheduled_time is None:
        return None
    return scheduled_time - timedelta(hours=DEFAULT_COMMIT_BY_OFFSET_HOURS)


def _normalize_patch_invitees(values: Any) -> list[str]:
    """Normalize invitee list from patch values."""
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        if not text.startswith("@"):
            text = f"@{text}"
        handle = text[1:]
        if TELEGRAM_HANDLE_PATTERN.fullmatch(handle):
            normalized.append(f"@{handle.lower()}")
    deduped: list[str] = []
    seen: set[str] = set()
    for handle in normalized:
        if handle not in seen:
            seen.add(handle)
            deduped.append(handle)
    return deduped


def build_event_summary_text(data: dict[str, Any], is_private: bool = False) -> str:
    """Build event draft summary text."""
    scheduled_time = format_scheduled_time(data.get("scheduled_time"))
    invitees = data.get("invitees", [])
    if not isinstance(invitees, list):
        invitees = []
    invite_all = bool(data.get("invite_all_members"))
    invitees_summary = (
        "all group members"
        if invite_all
        else f"{len(invitees)} users ({', '.join(invitees) if invitees else 'none'})"
    )
    notes = data.get("planning_notes", [])

    date_preset_label = format_date_preset(data.get("date_preset"))
    time_window_label = format_time_window(data.get("time_window"))
    location_type_label = format_location_type(data.get("location_type"))
    budget_level_label = format_budget_level(data.get("budget_level"))
    transport_mode_label = format_transport_mode(data.get("transport_mode"))
    commit_by_text = format_commit_by(data.get("commit_by"))

    notes_text = ""
    if isinstance(notes, list) and notes:
        note_lines = [f"- {str(note)}" for note in notes[-5:]]
        notes_text = "\n\nPlanning notes:\n" + "\n".join(note_lines)

    if is_private:
        return (
            f"✨ *Event Summary*\n\n"
            f"Type: {data.get('event_type', 'Not specified')}\n"
            f"Description: {data.get('description', 'Not provided')}\n"
            f"Time: {scheduled_time}\n"
            f"Date Preset: {date_preset_label}\n"
            f"Time Window: {time_window_label}\n"
            f"Commit-By: {commit_by_text}\n"
            f"Duration: {format_duration(data.get('duration_minutes'))}\n"
            f"Location Type: {location_type_label}\n"
            f"Budget: {budget_level_label}\n"
            f"Transport: {transport_mode_label}\n"
            f"Minimum: {data.get('min_participants', 'Not set')}\n"
            f"Capacity: {data.get('target_participants', 'Not set')}\n"
            f"Invitees: {invitees_summary}\n\n"
            "Press *Confirm & Lock* to finalize and lock this event."
        )

    return (
        f"✨ *Event Summary*\n\n"
        f"Type: {data.get('event_type', 'Not specified')}\n"
        f"Description: {data.get('description', 'Not provided')}\n"
        f"Time: {scheduled_time}\n"
        f"Date Preset: {date_preset_label}\n"
        f"Time Window: {time_window_label}\n"
        f"Commit-By: {commit_by_text}\n"
        f"Duration: {format_duration(data.get('duration_minutes'))}\n"
        f"Mode: {data.get('scheduling_mode', 'fixed')}\n"
        f"Location Type: {location_type_label}\n"
        f"Budget: {budget_level_label}\n"
        f"Transport: {transport_mode_label}\n"
        f"Minimum: {data.get('min_participants', 'Not set')}\n"
        f"Capacity: {data.get('target_participants', 'Not set')}\n"
        f"Invitees: {invitees_summary}"
        f"{notes_text}\n\n"
        "Create this event?\n"
        "You can press *Modify* or reply with free-text changes."
    )


def build_final_confirmation_markup(prefix: str = "event") -> InlineKeyboardMarkup:
    """Build final confirmation keyboard with revision support."""
    if prefix == "event":
        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data=f"{prefix}_final_yes")],
            [InlineKeyboardButton("🛠 Modify", callback_data=f"{prefix}_final_edit")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{prefix}_cancel_no")],
        ]
    else:
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Confirm & Lock", callback_data=f"{prefix}_final_yes"
                )
            ],
            [InlineKeyboardButton("🛠 Modify", callback_data=f"{prefix}_final_edit")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"{prefix}_cancel_no")],
        ]
    return InlineKeyboardMarkup(keyboard)


async def _apply_final_stage_patch(
    flow_data: dict[str, Any],
    message_text: str,
    is_private: bool = False,
) -> tuple[bool, list[str], str | None]:
    """Apply LLM-inferred patch to event draft data."""
    try:
        llm = LLMClient()
        try:
            patch = await llm.infer_event_draft_patch(flow_data, message_text)
        finally:
            await llm.close()
    except Exception:
        if is_private:
            return False, [], "LLM unavailable for modifications"
        return False, [], None

    changes: list[str] = []
    warnings: list[str] = []
    changed = False

    description = patch.get("description")
    if isinstance(description, str) and description.strip():
        next_description = description.strip()[:500]
        if next_description != str(flow_data.get("description", "")):
            flow_data["description"] = next_description
            changes.append("description updated")
            changed = True

    event_type_raw = patch.get("event_type")
    if event_type_raw is not None:
        normalized = str(event_type_raw).strip().lower()
        if normalized in ALLOWED_EVENT_TYPES:
            if normalized != str(flow_data.get("event_type", "")).lower():
                flow_data["event_type"] = normalized
                changes.append(f"type set to {normalized}")
                changed = True
        else:
            warnings.append(
                "Unsupported event type in modification; kept current value."
            )

    min_raw = patch.get("min_participants")
    if min_raw is not None:
        try:
            min_participants = int(min_raw)
            if min_participants < 1:
                warnings.append("Minimum participants must be at least 1.")
            else:
                flow_data["min_participants"] = min_participants
                existing_target = int(
                    flow_data.get("target_participants", min_participants)
                )
                if existing_target < min_participants:
                    flow_data["target_participants"] = min_participants
                changes.append(f"minimum set to {min_participants}")
                changed = True
        except (TypeError, ValueError):
            warnings.append("Invalid minimum participant format; ignored.")

    target_raw = patch.get("target_participants")
    if target_raw is not None:
        try:
            target_participants = int(target_raw)
            min_participants = int(flow_data.get("min_participants", 2))
            if target_participants < min_participants:
                warnings.append("Capacity cannot be below the minimum participants.")
            else:
                flow_data["target_participants"] = target_participants
                changes.append(f"capacity set to {target_participants}")
                changed = True
        except (TypeError, ValueError):
            warnings.append("Invalid capacity format; ignored.")

    duration_raw = patch.get("duration_minutes")
    if duration_raw is not None:
        try:
            duration = int(duration_raw)
            if duration <= 0 or duration > 720:
                warnings.append("Duration must be between 1 and 720 minutes.")
            else:
                flow_data["duration_minutes"] = duration
                changes.append(f"duration set to {duration} minutes")
                changed = True
        except (TypeError, ValueError):
            warnings.append("Invalid duration format; ignored.")

    if not is_private:
        mode_raw = patch.get("scheduling_mode")
        if mode_raw is not None:
            normalized_mode = str(mode_raw).strip().lower()
            if normalized_mode in {"fixed", "flexible"}:
                flow_data["scheduling_mode"] = normalized_mode
                changes.append(f"mode set to {normalized_mode}")
                changed = True
                if normalized_mode == "flexible":
                    flow_data.pop("scheduled_time", None)
                    flow_data.pop("scheduled_date", None)
            else:
                warnings.append("Unsupported scheduling mode; ignored.")

    location_raw = patch.get("location_type")
    if location_raw is not None:
        normalized_location = str(location_raw).strip().lower().replace(" ", "_")
        valid_locations = {value for _, value in LOCATION_PRESETS}
        if normalized_location in valid_locations:
            flow_data["location_type"] = normalized_location
            changes.append(f"location type set to {normalized_location}")
            changed = True
        else:
            warnings.append("Unsupported location type; ignored.")

    budget_raw = patch.get("budget_level")
    if budget_raw is not None:
        normalized_budget = str(budget_raw).strip().lower().replace(" ", "_")
        valid_budgets = {value for _, value in BUDGET_PRESETS}
        if normalized_budget in valid_budgets:
            flow_data["budget_level"] = normalized_budget
            changes.append(f"budget set to {normalized_budget}")
            changed = True
        else:
            warnings.append("Unsupported budget level; ignored.")

    transport_raw = patch.get("transport_mode")
    if transport_raw is not None:
        normalized_transport = str(transport_raw).strip().lower().replace(" ", "_")
        valid_transport = {value for _, value in TRANSPORT_PRESETS}
        if normalized_transport in valid_transport:
            flow_data["transport_mode"] = normalized_transport
            changes.append(f"transport set to {normalized_transport}")
            changed = True
        else:
            warnings.append("Unsupported transport mode; ignored.")

    if not is_private:
        time_window_raw = patch.get("time_window")
        if time_window_raw is not None:
            normalized_window = str(time_window_raw).strip().lower()
            if normalized_window in TIME_WINDOWS:
                flow_data["time_window"] = normalized_window
                changes.append(f"time window set to {normalized_window}")
                changed = True
            else:
                warnings.append("Unsupported time window; ignored.")

        date_preset_raw = patch.get("date_preset")
        if date_preset_raw is not None:
            normalized_preset = str(date_preset_raw).strip().lower()
            if normalized_preset in DATE_PRESET_LABELS or normalized_preset == "custom":
                flow_data["date_preset"] = normalized_preset
                changes.append(f"date preset set to {normalized_preset}")
                changed = True
            else:
                warnings.append("Unsupported date preset; ignored.")

    if not is_private and bool(patch.get("clear_time")):
        flow_data.pop("scheduled_time", None)
        flow_data.pop("scheduled_date", None)
        changes.append("time cleared (now TBD)")
        changed = True

    scheduled_time_iso = patch.get("scheduled_time_iso")
    if scheduled_time_iso is not None:
        try:
            parsed = datetime.fromisoformat(str(scheduled_time_iso).strip())
            flow_data["scheduled_time"] = parsed.isoformat(timespec="minutes")
            if not is_private:
                flow_data["scheduling_mode"] = "fixed"
            changes.append(f"time set to {parsed.strftime('%Y-%m-%d %H:%M')}")
            changed = True
        except ValueError:
            warnings.append("Invalid datetime format; use YYYY-MM-DDTHH:MM.")

    invitees_add = _normalize_patch_invitees(patch.get("invitees_add"))
    if invitees_add:
        if bool(flow_data.get("invite_all_members")):
            flow_data["invite_all_members"] = False
            flow_data["invitees"] = []
        existing = list(flow_data.get("invitees", []))
        for handle in invitees_add:
            if handle not in existing:
                existing.append(handle)
        flow_data["invitees"] = existing
        changes.append(f"added invitees: {', '.join(invitees_add)}")
        changed = True

    invitees_remove = _normalize_patch_invitees(patch.get("invitees_remove"))
    if invitees_remove:
        existing = list(flow_data.get("invitees", []))
        reduced = [h for h in existing if h not in set(invitees_remove)]
        flow_data["invitees"] = reduced
        if flow_data.get("invite_all_members"):
            flow_data["invite_all_members"] = False
        changes.append(f"removed invitees: {', '.join(invitees_remove)}")
        changed = True

    if patch.get("invite_all_members") is True:
        flow_data["invite_all_members"] = True
        flow_data["invitees"] = ["@all"]
        changes.append("invitees set to all group members")
        changed = True
    elif patch.get("invite_all_members") is False and flow_data.get(
        "invite_all_members"
    ):
        flow_data["invite_all_members"] = False
        if flow_data.get("invitees") == ["@all"]:
            flow_data["invitees"] = []
        changes.append("invite-all disabled")
        changed = True

    if not is_private:
        note = patch.get("note")
        if isinstance(note, str) and note.strip():
            notes = flow_data.get("planning_notes")
            if not isinstance(notes, list):
                notes = []
            notes.append(note.strip()[:300])
            flow_data["planning_notes"] = notes[-10:]
            changes.append("added planning note")
            changed = True

    if (
        not is_private
        and str(flow_data.get("scheduling_mode", "fixed")) == "fixed"
        and not flow_data.get("scheduled_time")
    ):
        warnings.append("Fixed mode requires a date/time before final confirm.")

    warning_text = "\n".join(f"- {w}" for w in warnings) if warnings else None
    return changed, changes, warning_text


async def finalize_event(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, _mode: str = "public"
) -> None:
    """Finalize and create the public/event in database."""
    from telegram import CallbackQuery

    if context.user_data is None:
        await query.edit_message_text("❌ User session data is unavailable.")
        return

    event_flow_raw = context.user_data.get("event_flow")
    if not isinstance(event_flow_raw, dict):
        await query.edit_message_text("❌ Event flow not found.")
        return

    event_flow: dict[str, Any] = event_flow_raw
    data_raw = event_flow.get("data")
    if not isinstance(data_raw, dict):
        await query.edit_message_text("❌ Event flow data is invalid.")
        return
    data: dict[str, Any] = data_raw

    scheduled_time_raw = data.get("scheduled_time")
    scheduling_mode = str(data.get("scheduling_mode", "fixed"))
    if scheduling_mode != "flexible" and not isinstance(scheduled_time_raw, str):
        await query.edit_message_text("❌ Event time is missing.")
        return

    group_id = event_flow.get("group_id")
    if not isinstance(group_id, int):
        await query.edit_message_text("❌ Group context is missing.")
        return

    async with get_session(settings.db_url) as session:
        candidate_time = (
            datetime.fromisoformat(scheduled_time_raw)
            if isinstance(scheduled_time_raw, str)
            else None
        )
        commit_by = compute_commit_by_time(candidate_time)
        duration_minutes = int(data.get("duration_minutes", 120))
        creator_id = int(data.get("creator", query.from_user.id))
        conflict = await find_user_event_conflict(
            session=session,
            telegram_user_id=creator_id,
            start_time=candidate_time,
            duration_minutes=duration_minutes,
        )
        if conflict:
            await query.edit_message_text(
                "❌ Creator has a conflicting event.\n"
                f"Conflicting Event ID: {conflict.event_id}\n"
                f"Time: {conflict.scheduled_time}\n"
                f"Duration: {conflict.duration_minutes or 120} minutes"
            )
            return

        event = Event(
            group_id=group_id,
            event_type=data.get("event_type", "general"),
            description=data.get("description"),
            organizer_telegram_user_id=creator_id,
            admin_telegram_user_id=creator_id,
            scheduled_time=candidate_time,
            commit_by=commit_by,
            duration_minutes=duration_minutes,
            min_participants=data.get("min_participants", 2),
            target_participants=data.get(
                "target_participants", max(data.get("min_participants", 2), 5)
            ),
            planning_prefs={
                "date_preset": data.get("date_preset"),
                "time_window": data.get("time_window"),
                "location_type": data.get("location_type"),
                "budget_level": data.get("budget_level"),
                "transport_mode": data.get("transport_mode"),
            },
            state="proposed",
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        from bot.services import ParticipantService

        participant_service = ParticipantService(session)
        await participant_service.join(
            event_id=event.event_id,
            telegram_user_id=creator_id,
            source="creation",
            role="organizer",
        )

        from bot.services.event_memory_service import EventMemoryService

        memory_service = EventMemoryService(context.bot, session)
        prior_memories = await memory_service.get_recent_memories(group_id, limit=5)

        lineage_event_ids = []
        lineage_suggestion = None
        for memory in prior_memories:
            if memory.event and memory.event.event_type == event.event_type:
                lineage_event_ids.append(memory.event.event_id)
                if not lineage_suggestion and memory.weave_text:
                    lineage_suggestion = {
                        "event_id": memory.event.event_id,
                        "event_type": memory.event.event_type,
                        "weave_preview": (
                            memory.weave_text[:200] if memory.weave_text else None
                        ),
                        "hashtags": memory.hashtags or [],
                    }

        if lineage_event_ids:
            await memory_service.link_lineage(event.event_id, lineage_event_ids[:3])
            logger.info(
                "Linked lineage for event %s: %s",
                event.event_id,
                lineage_event_ids[:3],
            )

        hashtags = data.get("hashtags", [])
        if hashtags:
            hashtag_service = EventHashtagService(session)
            try:
                event = await hashtag_service.assign_hashtags(event, hashtags)
                logger.info(
                    "Assigned hashtags to event %s: %s",
                    event.event_id,
                    hashtags,
                )
            except ValueError as e:
                logger.warning(f"Failed to assign hashtags: {e}")

        live_card_service = EventLiveCardService(context.bot, session)
        await live_card_service.create_live_card(event, hashtags=hashtags)

    context.user_data.pop("event_flow", None)

    invitees = list(data.get("invitees", []))

    logger.info(
        "Event %s created in group %s: invitees=%s",
        event.event_id,
        group_id,
        invitees,
    )

    async with get_session(settings.db_url) as session:
        organizer_user = (
            await session.execute(
                select(User).where(User.telegram_user_id == int(creator_id))
            )
        ).scalar_one_or_none()
        organizer_username = organizer_user.username if organizer_user else None
        organizer_display_name = organizer_user.display_name if organizer_user else None

        group = (
            await session.execute(select(Group).where(Group.group_id == group_id))
        ).scalar_one_or_none()

        data["organizer_telegram_user_id"] = int(creator_id)
        data["organizer_username"] = organizer_username
        data["organizer_display_name"] = organizer_display_name

        group_members = group.member_list or []

        dm_count = 0
        dm_failed = 0

        logger.info(
            "Group event %s: Sending DMs to all %s group members",
            event.event_id,
            len(group_members),
        )
        for telegram_user_id in group_members:
            if telegram_user_id:
                try:
                    sent = await send_event_invitation_dm(
                        context,
                        int(telegram_user_id),
                        data,
                        int(event.event_id),
                    )
                    if sent:
                        logger.info(
                            "DM sent to user %s for event %s (group event, all members)",
                            telegram_user_id,
                            event.event_id,
                        )
                        dm_count += 1
                    else:
                        dm_failed += 1
                except Exception as e:
                    logger.error(
                        "Error sending DM to user %s: %s",
                        telegram_user_id,
                        e,
                        exc_info=True,
                    )
                    dm_failed += 1

        if dm_count == 0:
            try:
                sent = await send_event_invitation_dm(
                    context,
                    int(creator_id),
                    data,
                    int(event.event_id),
                )
                if sent:
                    logger.info(
                        "DM sent to admin %s for event %s (fallback, no group members)",
                        creator_id,
                        event.event_id,
                    )
                    dm_count += 1
                else:
                    dm_failed += 1
            except Exception as e:
                logger.error(
                    "Error sending DM to admin %s: %s",
                    creator_id,
                    e,
                    exc_info=True,
                )
                dm_failed += 1

        logger.info(
            "Event %s DM distribution complete: %s sent, %s failed",
            event.event_id,
            dm_count,
            dm_failed,
        )

    scheduled_time = format_scheduled_time(data.get("scheduled_time"))
    commit_by_text = format_commit_by(commit_by)
    invitees_summary = (
        "all group members"
        if data.get("invite_all_members")
        else f"{len(data.get('invitees', []))} users"
    )
    location_text = format_location_type(data.get("location_type"))
    budget_text = format_budget_level(data.get("budget_level"))
    transport_text = format_transport_mode(data.get("transport_mode"))
    date_preset_text = format_date_preset(data.get("date_preset"))
    time_window_text = format_time_window(data.get("time_window"))

    group_summary = (
        f"✅ *Event Created!*\n\n"
        f"Event ID: `{event.event_id}`\n"
        f"Description: {_escape_md(data.get('description', 'Not provided'))}\n\n"
        "A private DM has been sent to group members with full event details and next steps."
    )

    await query.edit_message_text(group_summary)

    full_summary = (
        f"✅ *Event Created Successfully!*\n\n"
        f"Event ID: `{event.event_id}`\n"
        f"State: proposed (awaiting confirmations)\n\n"
        f"Type: {_escape_md(data.get('event_type', 'Not specified'))}\n"
        f"Description: {_escape_md(data.get('description', 'Not provided'))}\n"
        f"Time: {_escape_md(scheduled_time)}\n"
        f"Commit-By: {_escape_md(commit_by_text)}\n"
        f"Date Preset: {_escape_md(date_preset_text)}\n"
        f"Time Window: {_escape_md(time_window_text)}\n"
        f"Duration: {_escape_md(format_duration(data.get('duration_minutes')))}\n"
        f"Mode: {_escape_md(scheduling_mode)}\n"
        f"Location Type: {_escape_md(location_text)}\n"
        f"Budget: {_escape_md(budget_text)}\n"
        f"Transport: {_escape_md(transport_text)}\n"
        f"Minimum: {_escape_md(data.get('min_participants', 'Not set'))}\n"
        f"Capacity: {_escape_md(data.get('target_participants', 'Not set'))}\n"
        f"Invitees: {_escape_md(invitees_summary)}\n\n"
        f"✅ Event ready for confirmation. Run /confirm {event.event_id} to lock it."
        + (
            "\n\nFlexible flow tip:\n"
            "Each attendee can add availability slots with:\n"
            f"/constraints {event.event_id} availability <YYYY-MM-DD HH:MM, ...>"
            if scheduling_mode == "flexible"
            else ""
        )
    )

    dm_keyboard = [
        [
            InlineKeyboardButton(
                "View Event Details", callback_data=f"event_details_{event.event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "Manage Event", callback_data=f"event_admin_{event.event_id}"
            )
        ],
    ]
    dm_reply_markup = InlineKeyboardMarkup(dm_keyboard)

    await context.bot.send_message(
        chat_id=creator_id,
        text=full_summary,
        reply_markup=dm_reply_markup,
        parse_mode="Markdown",
    )
    logger.info(
        "Full event details sent to admin %s via DM for event %s",
        creator_id,
        event.event_id,
    )


async def finalize_private_event(
    query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Finalize and create the private event in database."""
    if context.user_data is None:
        await query.edit_message_text("❌ Session data unavailable.")
        return

    event_flow_raw = context.user_data.get("private_event_flow")
    if not isinstance(event_flow_raw, dict):
        await query.edit_message_text("❌ Event flow not found.")
        return

    event_flow: dict[str, Any] = event_flow_raw
    data_raw = event_flow.get("data")
    if not isinstance(data_raw, dict):
        await query.edit_message_text("❌ Event flow data is invalid.")
        return
    data: dict[str, Any] = data_raw

    scheduled_time_raw = data.get("scheduled_time")
    scheduling_mode = str(data.get("scheduling_mode", "fixed"))
    if scheduling_mode != "flexible" and not isinstance(scheduled_time_raw, str):
        await query.edit_message_text("❌ Event time is missing.")
        return

    creator_id = int(data.get("creator", query.from_user.id))

    async with get_session(settings.db_url) as session:
        candidate_time = (
            datetime.fromisoformat(scheduled_time_raw)
            if isinstance(scheduled_time_raw, str)
            else None
        )
        commit_by = compute_commit_by_time(candidate_time)
        duration_minutes = int(data.get("duration_minutes", 120))

        try:
            conflict = await find_user_event_conflict(
                session=session,
                telegram_user_id=creator_id,
                start_time=candidate_time,
                duration_minutes=duration_minutes,
            )
            if conflict:
                await query.edit_message_text(
                    "❌ Creator has a conflicting event.\n"
                    f"Conflicting Event ID: {conflict.event_id}\n"
                    f"Time: {conflict.scheduled_time}\n"
                    f"Duration: {conflict.duration_minutes or 120} minutes"
                )
                return
        except ImportError:
            pass

        event = Event(
            group_id=0,
            event_type=data.get("event_type", "general"),
            description=data.get("description"),
            organizer_telegram_user_id=creator_id,
            scheduled_time=candidate_time,
            commit_by=commit_by,
            duration_minutes=duration_minutes,
            min_participants=data.get("min_participants", 2),
            target_participants=data.get(
                "target_participants", max(data.get("min_participants", 2), 5)
            ),
            planning_prefs={
                "date_preset": data.get("date_preset"),
                "time_window": data.get("time_window"),
                "location_type": data.get("location_type"),
                "budget_level": data.get("budget_level"),
                "transport_mode": data.get("transport_mode"),
            },
            state="confirmed",
            locked_at=datetime.utcnow(),
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        from bot.services import ParticipantService

        participant_service = ParticipantService(session)
        await participant_service.join(
            event_id=event.event_id,
            telegram_user_id=creator_id,
            source="creation",
            role="organizer",
        )

        hashtags = data.get("hashtags", [])
        if hashtags:
            hashtag_service = EventHashtagService(session)
            try:
                event = await hashtag_service.assign_hashtags(event, hashtags)
                logger.info(
                    "Assigned hashtags to private event %s: %s",
                    event.event_id,
                    hashtags,
                )
            except ValueError as e:
                logger.warning(f"Failed to assign hashtags: {e}")

        live_card_service = EventLiveCardService(context.bot, session)
        await live_card_service.create_live_card(event, hashtags=hashtags)

    invitees = list(data.get("invitees", []))

    organizer_username = None

    async with get_session(settings.db_url) as session:
        organizer_user = (
            await session.execute(
                select(User).where(User.telegram_user_id == int(creator_id))
            )
        ).scalar_one_or_none()
        organizer_username = organizer_user.username if organizer_user else None

        data["organizer_telegram_user_id"] = int(creator_id)
        data["organizer_username"] = organizer_username

        dm_count = 0
        dm_failed = 0

        if invitees:
            logger.info(
                "Private event %s: Sending DMs to %s invitees",
                event.event_id,
                len(invitees),
            )
            for handle in invitees:
                if not handle.startswith("@"):
                    continue
                username = handle[1:]
                try:
                    user_id = await get_user_id_by_username(session, username)
                    if user_id:
                        result = await session.execute(
                            select(User).where(User.user_id == int(user_id))
                        )
                        invitee_user = result.scalar_one_or_none()
                        if invitee_user and invitee_user.telegram_user_id:
                            sent = await send_event_invitation_dm(
                                context,
                                int(invitee_user.telegram_user_id),
                                data,
                                int(event.event_id),
                            )
                            if sent:
                                logger.info(
                                    "DM sent to user %s (@%s) for private event %s (invitee)",
                                    invitee_user.telegram_user_id,
                                    username,
                                    event.event_id,
                                )
                                dm_count += 1
                            else:
                                dm_failed += 1
                        else:
                            logger.warning(
                                "User @%s not found or no telegram_user_id for private event %s",
                                username,
                                event.event_id,
                            )
                            dm_failed += 1
                    else:
                        logger.warning(
                            "No user_id found for handle @%s in private event %s",
                            username,
                            event.event_id,
                        )
                        dm_failed += 1
                except Exception as e:
                    logger.error(
                        "Error sending DM to @%s: %s",
                        username,
                        e,
                        exc_info=True,
                    )
                    dm_failed += 1
        else:
            await query.edit_message_text(
                "❌ For private events, you must specify invitees. Use @username (comma-separated)."
            )
            return

        try:
            sent = await send_event_invitation_dm(
                context, int(creator_id), data, int(event.event_id)
            )
            if sent:
                logger.info(
                    "DM sent to admin %s for private event %s (admin)",
                    creator_id,
                    event.event_id,
                )
                dm_count += 1
            else:
                dm_failed += 1
        except Exception as e:
            logger.error(
                "Error sending DM to admin %s: %s",
                creator_id,
                e,
                exc_info=True,
            )
            dm_failed += 1

        logger.info(
            "Private event %s DM distribution complete: %s sent, %s failed",
            event.event_id,
            dm_count,
            dm_failed,
        )

    context.user_data.pop("private_event_flow", None)

    keyboard = [
        [
            InlineKeyboardButton(
                "View Event", callback_data=f"private_event_details_{event.event_id}"
            )
        ],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    scheduled_time = format_scheduled_time(data.get("scheduled_time"))
    commit_by_text = format_commit_by(commit_by)
    invitees_summary = (
        "all group members"
        if data.get("invite_all_members")
        else f"{len(invitees)} users"
    )
    location_text = format_location_type(data.get("location_type"))
    budget_text = format_budget_level(data.get("budget_level"))
    transport_text = format_transport_mode(data.get("transport_mode"))
    date_preset_text = format_date_preset(data.get("date_preset"))
    time_window_text = format_time_window(data.get("time_window"))

    await query.edit_message_text(
        f"✅ *Event Created!*\n\n"
        f"Event ID: {event.event_id}\n"
        f"Type: {_escape_md(data.get('event_type', 'Not specified'))}\n"
        f"Description: {_escape_md(data.get('description', 'Not provided'))}\n"
        f"Time: {_escape_md(scheduled_time)}\n"
        f"Commit-By: {_escape_md(commit_by_text)}\n"
        f"Date Preset: {_escape_md(date_preset_text)}\n"
        f"Time Window: {_escape_md(time_window_text)}\n"
        f"Duration: {_escape_md(format_duration(data.get('duration_minutes')))}\n"
        f"Mode: {_escape_md(scheduling_mode)}\n"
        f"Location Type: {_escape_md(location_text)}\n"
        f"Budget: {_escape_md(budget_text)}\n"
        f"Transport: {_escape_md(transport_text)}\n"
        f"Minimum: {_escape_md(data.get('min_participants', 'Not set'))}\n"
        f"Capacity: {_escape_md(data.get('target_participants', 'Not set'))}\n"
        f"Invitees: {_escape_md(invitees_summary)}\n\n"
        f"✅ Event has been automatically locked.\n"
        f"Status: Locked - No further changes allowed.\n\n"
        + (
            f"Event Admin: {organizer_username if organizer_username else creator_id}"
            if organizer_username
            else f"Event Admin: {creator_id}"
        ),
        reply_markup=reply_markup,
    )
