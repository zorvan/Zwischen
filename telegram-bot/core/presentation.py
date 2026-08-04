"""Transport-neutral read models. Renderers, not domain services, own markup."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class UserRef:
    public_id: UUID
    display_name: str | None


@dataclass(frozen=True)
class EventSummary:
    public_id: UUID
    group_public_id: UUID | None
    title: str
    event_type: str
    state: str
    scheduled_time: datetime | None
    confirmed: int
    interested: int
    needed: int
    organizer: UserRef | None = None

    def as_json(self) -> dict[str, Any]:
        result = asdict(self)
        result["public_id"] = str(self.public_id)
        result["group_public_id"] = (
            str(self.group_public_id) if self.group_public_id else None
        )
        result["scheduled_time"] = (
            self.scheduled_time.isoformat() if self.scheduled_time else None
        )
        if self.organizer:
            result["organizer"]["public_id"] = str(self.organizer.public_id)
        return result


def render_telegram_event(summary: EventSummary) -> str:
    """Telegram-specific HTML stays at the transport boundary."""
    import html

    title = html.escape(summary.title)
    return f"<b>{title}</b> — {summary.confirmed}/{summary.needed} confirmed"
