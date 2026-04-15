"""Event selection helpers for commands that currently require inline input."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from db.models import Event, EventParticipant


async def build_event_selector_markup(
    session, user_id: int, group_id: int | None = None, title: str = "Select Event"
) -> InlineKeyboardMarkup:
    """Build inline keyboard with user's recent events."""
    query = (
        select(Event)
        .where(Event.status.has_key("state"))
        .order_by(Event.created_at.desc())
        .limit(10)
    )

    if group_id:
        query = query.where(Event.group_id == group_id)

    result = await session.execute(query)
    events = result.scalars().all()

    if not events:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("No events found", callback_data="noop")]]
        )

    rows = []
    for event in events:
        time_str = (
            event.scheduled_time.strftime("%d %b %H:%M")
            if event.scheduled_time
            else "TBD"
        )
        label = f"{event.event_type} • {time_str}"
        callback = f"select_event_{event.event_id}"
        rows.append([InlineKeyboardButton(label, callback_data=callback)])

    return InlineKeyboardMarkup(rows)


async def build_my_events_selector_markup(
    session, user_id: int, group_id: int | None = None
) -> InlineKeyboardMarkup:
    """Build inline keyboard with events the user participates in."""
    query = (
        select(EventParticipant)
        .where(EventParticipant.telegram_user_id == user_id)
        .order_by(EventParticipant.created_at.desc())
        .limit(15)
    )

    if group_id:
        query = query.where(EventParticipant.group_id == group_id)

    result = await session.execute(query)
    participants = result.scalars().all()

    if not participants:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("No events found", callback_data="noop")]]
        )

    event_ids = [p.event_id for p in participants]

    events_query = (
        select(Event)
        .where(Event.event_id.in_(event_ids))
        .order_by(Event.scheduled_time.desc())
        .limit(10)
    )

    events_result = await session.execute(events_query)
    events = events_result.scalars().all()

    if not events:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("No events found", callback_data="noop")]]
        )

    rows = []
    for event in events:
        time_str = (
            event.scheduled_time.strftime("%d %b %H:%M")
            if event.scheduled_time
            else "TBD"
        )
        label = f"{event.event_type} • {time_str}"
        callback = f"select_event_{event.event_id}"
        rows.append([InlineKeyboardButton(label, callback_data=callback)])

    return InlineKeyboardMarkup(rows)
