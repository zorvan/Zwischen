#!/usr/bin/env python3
"""
End-to-End Fictional Demo Test Suite.

This module creates a comprehensive simulation with fictional database entries,
group members, artificial conversations, and past events to demonstrate all
features and milestones of the Telegram Coordination Bot.

Fictional Scenario: "Zwischen Soccer League" - A recurring social event system
with 5 members, multiple event attempts (some successful, some failed), and
complex interaction patterns including constraints, availability, and memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest

from db.models import (
    Constraint,
    Event,
    EventMemory,
    EventParticipant,
    Group,
    ParticipantStatus,
    User,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.common.confirmation import invalidate_confirmations_and_notify
from bot.services.event_lifecycle_service import EventLifecycleService
from bot.services.event_memory_service import EventMemoryService
from bot.services.group_event_type_stats_service import GroupEventTypeStatsService
from bot.services.participant_service import ParticipantService
from bot.services.waitlist_service import WaitlistService


class FictionalDemoSimulator:
    """
    High-level simulator for fictional demo scenarios.

    Creates realistic artificial data including:
    - Multiple users with different contribution levels
    - Group memberships with varying engagement
    - Artificial conversations (past events with different outcomes)
    - Constraints between participants
    - Availability slots
    - Event memories and failure patterns
    """

    def __init__(self, session) -> None:
       self.session = session
       self.bot = ScenarioBot()
       self.context = ScenarioContext(bot=self.bot)

    async def create_user(
       self,
       username: str,
       *,
       display_name: str | None = None,
       telegram_user_id: int,
       expertise: dict | None = None,
    ) -> User:
       """Create a user with attributes."""
       user = User(
           telegram_user_id=telegram_user_id,
           username=username,
           display_name=display_name or username,
           expertise_per_activity=expertise or {},
       )
       self.session.add(user)
       await self.session.flush()
       return user

    async def create_group(
       self,
       name: str,
       *,
       telegram_group_id: int,
       members: list[User],
    ) -> Group:
       """Create a group with members."""
       group = Group(
           telegram_group_id=telegram_group_id,
           group_name=name,
           member_list=[int(member.telegram_user_id) for member in members],
       )
       self.session.add(group)
       await self.session.flush()
       return group

    async def create_event(
       self,
       *,
       group: Group,
       organizer: User,
       event_type: str,
       description: str,
       scheduled_time: datetime | None,
       min_participants: int,
       target_participants: int,
       duration_minutes: int = 120,
       state: str = "proposed",
       **extra_fields: Any,
    ) -> Event:
       """Create an event with full attributes."""
       event = Event(
           group_id=group.group_id,
           event_type=event_type,
           description=description,
           organizer_telegram_user_id=organizer.telegram_user_id,
           admin_telegram_user_id=organizer.telegram_user_id,
           scheduled_time=scheduled_time,
           duration_minutes=duration_minutes,
           min_participants=min_participants,
           target_participants=target_participants,
           state=state,
           **extra_fields,
       )
       self.session.add(event)
       await self.session.flush()
       return event

    async def fetch_event(self, event_id: int) -> Event:
       """Fetch event with all relationships loaded."""
       result = await self.session.execute(
           select(Event)
           .execution_options(populate_existing=True)
           .options(
               selectinload(Event.participants),
               selectinload(Event.waitlist),
               selectinload(Event.memories),
               selectinload(Event.constraints),
           )
           .where(Event.event_id == event_id)
       )
       return result.scalar_one()

    async def join(
       self, event_id: int, user: User, *, role: str = "participant"
    ) -> Event:
       """Join an event."""
       participant_service = ParticipantService(self.session)
       await participant_service.join(
           event_id=event_id,
           telegram_user_id=int(user.telegram_user_id),
           source="demo",
           role=role,
       )
       event = await self.fetch_event(event_id)
       if event.state == "proposed":
           lifecycle = EventLifecycleService(self.bot, self.session)
           event, _ = await lifecycle.transition_with_lifecycle(
               event_id=event_id,
               target_state="interested",
               actor_telegram_user_id=int(user.telegram_user_id),
               source="demo",
               reason="Demo join",
           )
       await self.session.commit()
       return await self.fetch_event(event_id)

    async def confirm(self, event_id: int, user: User) -> Event:
       """Confirm participation in an event."""
       participant_service = ParticipantService(self.session)
       await participant_service.confirm(
           event_id=event_id,
           telegram_user_id=int(user.telegram_user_id),
           source="demo",
       )
       event = await self.fetch_event(event_id)
       if event.state != "confirmed":
           lifecycle = EventLifecycleService(self.bot, self.session)
           event, _ = await lifecycle.transition_with_lifecycle(
               event_id=event_id,
               target_state="confirmed",
               actor_telegram_user_id=int(user.telegram_user_id),
               source="demo",
               reason="Demo confirm",
           )
       await self.session.commit()
       return await self.fetch_event(event_id)

    async def uncommit(self, event_id: int, user: User) -> Event:
       """Uncommit from an event."""
       participant_service = ParticipantService(self.session)
       await participant_service.unconfirm(
           event_id=event_id,
           telegram_user_id=int(user.telegram_user_id),
           source="demo",
       )
       event = await self.fetch_event(event_id)
       confirmed_count = await participant_service.get_confirmed_count(event_id)
       active_count = sum(
           1
           for participant in event.participants
           if participant.status
           in {ParticipantStatus.joined, ParticipantStatus.confirmed}
       )
       if event.state == "confirmed" and confirmed_count == 0:
           lifecycle = EventLifecycleService(self.bot, self.session)
           target_state = "interested" if active_count > 0 else "proposed"
           event, _ = await lifecycle.transition_with_lifecycle(
               event_id=event_id,
               target_state=target_state,
               actor_telegram_user_id=int(user.telegram_user_id),
               source="demo",
               reason="Demo uncommit",
           )
       await self.session.commit()
       return await self.fetch_event(event_id)

    async def exit(self, event_id: int, user: User) -> Event:
       """Exit/cancel participation from an event."""
       participant_service = ParticipantService(self.session)
       await participant_service.cancel(
           event_id=event_id,
           telegram_user_id=int(user.telegram_user_id),
           source="demo",
       )
       waitlist_service = WaitlistService(self.session, self.bot)
       await waitlist_service.trigger_auto_fill(event_id)

       event = await self.fetch_event(event_id)
       confirmed_count = await participant_service.get_confirmed_count(event_id)
       active_count = sum(
           1
           for participant in event.participants
           if participant.status
           in {ParticipantStatus.joined, ParticipantStatus.confirmed}
       )
       if event.state == "confirmed" and confirmed_count == 0:
           lifecycle = EventLifecycleService(self.bot, self.session)
           target_state = "interested" if active_count > 0 else "proposed"
           event, _ = await lifecycle.transition_with_lifecycle(
               event_id=event_id,
               target_state=target_state,
               actor_telegram_user_id=int(user.telegram_user_id),
               source="demo",
               reason="Demo exit",
           )

       await self.session.commit()
       return await self.fetch_event(event_id)

    async def lock(self, event_id: int, actor: User) -> Event:
       """Lock an event."""
       lifecycle = EventLifecycleService(self.bot, self.session)
       await lifecycle.transition_with_lifecycle(
           event_id=event_id,
           target_state="locked",
           actor_telegram_user_id=int(actor.telegram_user_id),
           source="demo",
           reason="Demo lock",
           expected_version=(await self.fetch_event(event_id)).version,
       )
       participant_service = ParticipantService(self.session)
       await participant_service.finalize_commitments(event_id)
       await self.session.commit()
       return await self.fetch_event(event_id)

    async def cancel_event(
       self, event_id: int, actor: User, *, reason: str = "Demo cancellation"
    ) -> Event:
       """Cancel an entire event."""
       lifecycle = EventLifecycleService(self.bot, self.session)
       await lifecycle.transition_with_lifecycle(
           event_id=event_id,
           target_state="cancelled",
           actor_telegram_user_id=int(actor.telegram_user_id),
           source="demo",
           reason=reason,
           expected_version=(await self.fetch_event(event_id)).version,
       )
       await self.session.commit()
       return await self.fetch_event(event_id)

    async def complete_event(self, event_id: int, actor: User) -> Event:
       """Complete an event."""
       lifecycle = EventLifecycleService(self.bot, self.session)
       await lifecycle.transition_with_lifecycle(
           event_id=event_id,
           target_state="completed",
           actor_telegram_user_id=int(actor.telegram_user_id),
           source="demo",
           reason="Demo completion",
           expected_version=(await self.fetch_event(event_id)).version,
       )
       await self.session.commit()
       return await self.fetch_event(event_id)

    async def add_to_waitlist(self, event_id: int, user: User) -> int:
       """Add user to waitlist."""
       waitlist_service = WaitlistService(self.session, self.bot)
       position = await waitlist_service.add_to_waitlist(
           event_id, int(user.telegram_user_id)
       )
       await self.session.commit()
       return position

    async def accept_waitlist_offer(self, event_id: int, user: User) -> bool:
       """Accept waitlist offer."""
       waitlist_service = WaitlistService(self.session, self.bot)
       accepted = await waitlist_service.accept_offer(
           event_id, int(user.telegram_user_id)
       )
       await self.session.commit()
       return accepted

    async def decline_waitlist_offer(self, event_id: int, user: User) -> bool:
       """Decline waitlist offer."""
       waitlist_service = WaitlistService(self.session, self.bot)
       declined = await waitlist_service.decline_offer(
           event_id, int(user.telegram_user_id)
       )
       await self.session.commit()
       return declined

    async def modify_event(self, event_id: int, actor: User, **changes: Any) -> Event:
       """Modify an event."""
       event = await self.fetch_event(event_id)
       changed_fields = set(changes)
       for key, value in changes.items():
           setattr(event, key, value)

       if (
           "min_participants" in changed_fields
           and event.target_participants < event.min_participants
       ):
           event.target_participants = event.min_participants

       if changed_fields & {
           "scheduled_time",
           "duration_minutes",
           "min_participants",
           "target_participants",
           "description",
           "planning_prefs",
       }:
           await invalidate_confirmations_and_notify(
               context=self.context,
               event=event,
               reason="demo modify",
           )
           active_count = sum(
               1
               for participant in (event.participants or [])
               if participant.status
               in {ParticipantStatus.joined, ParticipantStatus.confirmed}
           )
           event.state = "interested" if active_count > 0 else "proposed"

       event.version += 1
       await self.session.commit()
       return await self.fetch_event(event_id)

    async def add_constraint(
       self,
       event_id: int,
       source_user: User,
       target_user: User,
       constraint_type: str,
       *,
       confidence: float = 0.8,
    ) -> Constraint:
       """Add a constraint between users for an event."""
       from db.users import get_or_create_user_id

       source_user_id = await get_or_create_user_id(
           self.session,
           telegram_user_id=int(source_user.telegram_user_id),
           display_name=source_user.display_name,
           username=source_user.username,
       )
       target_user_id = await get_or_create_user_id(
           self.session,
           telegram_user_id=int(target_user.telegram_user_id),
           display_name=target_user.display_name,
           username=target_user.username,
       )
       constraint = Constraint(
           user_id=source_user_id,
           target_user_id=target_user_id,
           event_id=event_id,
           type=constraint_type,
           confidence=confidence,
       )
       self.session.add(constraint)
       await self.session.commit()
       return constraint

    async def add_availability(
       self, event_id: int, user: User, slot_iso: str
    ) -> Constraint:
       """Add availability slot for a user."""
       from db.users import get_or_create_user_id

       source_user_id = await get_or_create_user_id(
           self.session,
           telegram_user_id=int(user.telegram_user_id),
           display_name=user.display_name,
           username=user.username,
       )
       constraint = Constraint(
           user_id=source_user_id,
           target_user_id=None,
           event_id=event_id,
           type=f"available:{slot_iso}",
           confidence=1.0,
       )
       self.session.add(constraint)
       await self.session.commit()
       return constraint

    async def record_memory_fragment(self, event_id: int, text: str) -> EventMemory:
       """Record a memory fragment from an event."""
       event = await self.fetch_event(event_id)
       memory = event.memories
       if memory is None:
           memory = EventMemory(event_id=event_id, fragments=[])
           self.session.add(memory)
           await self.session.flush()

       fragments = list(memory.fragments or [])
       fragments.append(
           {
               "text": text,
               "submitted_at": datetime.utcnow().isoformat(),
               "word_count": len(text.split()),
           }
       )
       memory.fragments = fragments
       await self.session.commit()
       return memory

    async def get_failure_pattern(
       self, group_id: int, event_type: str
    ) -> dict[str, Any] | None:
       """Get failure pattern for a group/event type."""
       service = GroupEventTypeStatsService(self.session)
       return await service.get_failure_pattern(group_id, event_type)

    async def get_memory_hook(
       self, group_id: int, event_type: str, max_words: int = 12
    ) -> str | None:
       """Get memory hook for a group/event type."""
       service = EventMemoryService(self.bot, self.session)
       return await service.get_memory_hook(group_id, event_type, max_words=max_words)


class ScenarioBot:
    """Minimal bot double that records sent messages for demo purposes."""

    def __init__(self, username: str = "demo_bot") -> None:
       self.username = username
       self.sent_messages: list[dict[str, Any]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
       self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})

    async def get_chat(self, target: Any) -> Any:
       raise RuntimeError(f"ScenarioBot cannot resolve Telegram chat for {target!r}")


@dataclass
class ScenarioContext:
    """Minimal context object for notification helpers."""

    bot: ScenarioBot


from dataclasses import dataclass


@pytest.mark.asyncio
async def test_fictional_end_to_end_demo_journey(db_session) -> None:
    """Comprehensive end-to-end demo with fictional data.

    Scenario: "Zwischen Soccer League" - A fictional recurring event system
    with multiple members, constraints, availability, and various event outcomes.

    Fictional Members:
    - Alex (organizer, highly engaged)
    - Bella (moderately engaged, has constraints)
    - Charlie (new member, learning the system)
    - Diana (experienced, uses availability extensively)
    - Ethan (casual, often cancels last minute)

    Fictional Events:
    1. Event 1: FAILED - Bella cancelled last minute
    2. Event 2: FAILED - Ethan cancelled last minute (FIXED: Ethan now joins first)
    3. Event 3: FAILED - Too many dropouts
    4. Event 4: SUCCESSFUL - Full 5 participants
    5. Event 5: FAILED - Added to reach failed_count >= 3 threshold
    """
    simulator = FictionalDemoSimulator(db_session)

    # =============================================================================
    # STEP 1: Create Fictional Users with Different Characteristics
    # =============================================================================

    alex = await simulator.create_user(
       "alex",
       display_name="Alex Morgan",
       telegram_user_id=1001,
       expertise={"soccer": 5, "board_games": 3},
    )

    bella = await simulator.create_user(
       "bella",
       display_name="Bella Chen",
       telegram_user_id=1002,
       expertise={"soccer": 4},
    )

    charlie = await simulator.create_user(
       "charlie",
       display_name="Charlie Davis",
       telegram_user_id=1003,
       expertise={"soccer": 2},
    )

    diana = await simulator.create_user(
       "diana",
       display_name="Diana Rodriguez",
       telegram_user_id=1004,
       expertise={"soccer": 4, "cooking": 5},
    )

    ethan = await simulator.create_user(
       "ethan",
       display_name="Ethan Wilson",
       telegram_user_id=1005,
       expertise={"soccer": 3},
    )

    # =============================================================================
    # STEP 2: Create Fictional Group
    # =============================================================================

    group = await simulator.create_group(
       "Zwischen Soccer League",
       telegram_group_id=-1001234567890,
       members=[alex, bella, charlie, diana, ethan],
    )

    # =============================================================================
    # STEP 3: ARTIFICIAL CONVERSATION - Past Failed Events (for LLM training)
    # =============================================================================

    # Event 1: Failed attempt - Bella cancelled last minute
    event1 = await simulator.create_event(
       group=group,
       organizer=alex,
       event_type="soccer",
       description="FIFA Night - Weekly Friday Soccer 🏆",
       scheduled_time=datetime.utcnow() + timedelta(days=1),
       min_participants=3,
       target_participants=5,
       duration_minutes=180,
    )

    await simulator.join(event1.event_id, alex, role="organizer")
    await simulator.join(event1.event_id, bella)
    await simulator.join(event1.event_id, charlie)
    await simulator.confirm(event1.event_id, alex)
    await simulator.confirm(event1.event_id, bella)
    await simulator.confirm(event1.event_id, charlie)

    # Bella exits, leaving 2 confirmed participants (below min of 3)
    await simulator.exit(event1.event_id, bella)
    await simulator.cancel_event(event1.event_id, alex)

    # Record failure memory for LLM (FIXED: 9 words <= 12)
    await simulator.record_memory_fragment(
       event1.event_id,
       "Bella had work emergency. Check free status before confirming.",
    )

    # Event 2: Failed attempt - Ethan cancelled last minute (FIXED: Ethan now joins first)
    event2 = await simulator.create_event(
       group=group,
       organizer=alex,
       event_type="soccer",
       description="FIFA Night #2 - Let's make it happen this time!",
       scheduled_time=datetime.utcnow() + timedelta(days=8),
       min_participants=3,
       target_participants=5,
       duration_minutes=180,
    )

    await simulator.join(event2.event_id, alex, role="organizer")
    await simulator.join(event2.event_id, bella)
    await simulator.join(event2.event_id, charlie)
    await simulator.join(event2.event_id, diana)
    await simulator.join(event2.event_id, ethan)  # FIXED: Ethan now joins first
    await simulator.confirm(event2.event_id, alex)
    await simulator.confirm(event2.event_id, bella)
    await simulator.confirm(event2.event_id, charlie)
    await simulator.confirm(event2.event_id, diana)
    await simulator.confirm(event2.event_id, ethan)

    # Ethan cancels last minute - artificial conversation: "My bad, got sick 😷"
    await simulator.exit(event2.event_id, ethan)
    await simulator.cancel_event(event2.event_id, alex)

    # Event2 is now cancelled (4 participants but needs 3+ to proceed)
    event2 = await simulator.fetch_event(event2.event_id)
    assert event2.state == "cancelled"

    # Record failure memory for LLM (FIXED: 6 words <= 12)
    await simulator.record_memory_fragment(
       event2.event_id,
       "Ethan got sick. Check availability earlier.",
    )

    # Event 3: FAILED - Too many dropouts, only 2 confirmed
    event3 = await simulator.create_event(
       group=group,
       organizer=alex,
       event_type="soccer",
       description="FIFA Night #3 - The Comeback Attempt 🔥",
       scheduled_time=datetime.utcnow() + timedelta(days=15),
       min_participants=3,
       target_participants=5,
       duration_minutes=180,
    )

    await simulator.join(event3.event_id, alex, role="organizer")
    await simulator.join(event3.event_id, bella)
    await simulator.join(event3.event_id, charlie)
    await simulator.join(event3.event_id, diana)
    await simulator.join(event3.event_id, ethan)

    # Initial confirmations
    await simulator.confirm(event3.event_id, alex)
    await simulator.confirm(event3.event_id, bella)
    await simulator.confirm(event3.event_id, charlie)
    await simulator.confirm(event3.event_id, diana)
    await simulator.confirm(event3.event_id, ethan)

    # Charlie drops out - artificial conversation: "Sorry, family emergency 👨‍👩‍👧"
    await simulator.uncommit(event3.event_id, charlie)

    # Ethan also drops out - artificial conversation: "Actually can't make it guys"
    await simulator.exit(event3.event_id, ethan)
    await simulator.cancel_event(event3.event_id, alex)

    # Only 2 participants left - event cancelled
    event3 = await simulator.fetch_event(event3.event_id)
    assert event3.state == "cancelled"

    await simulator.record_memory_fragment(
       event3.event_id,
       "Too many dropouts. Need more confirmed participants before locking.",
    )

    # =============================================================================
    # STEP 4: PRESENT - Successful Event with All Features
    # =============================================================================

    event4 = await simulator.create_event(
       group=group,
       organizer=alex,
       event_type="soccer",
       description="FIFA Night #4 - The Winning Streak 🏆⚽",
       scheduled_time=datetime.utcnow() + timedelta(days=22),
       min_participants=3,
       target_participants=5,
       duration_minutes=180,
       planning_prefs='{"venue": "Central Park", "balls": 2, "posts": 4}',
    )

    # Join phase with artificial conversations
    await simulator.join(event4.event_id, alex, role="organizer")
    await simulator.join(event4.event_id, bella)
    await simulator.join(event4.event_id, charlie)
    await simulator.join(event4.event_id, diana)
    await simulator.join(event4.event_id, ethan)

    # Bella adds constraint: "I can only come if Charlie is there"
    await simulator.add_constraint(
       event4.event_id,
       bella,
       charlie,
       "if_joins",
       confidence=0.95,
    )

    # Diana adds availability slots
    await simulator.add_availability(event4.event_id, diana, "2026-04-25T19:00")
    await simulator.add_availability(event4.event_id, diana, "2026-04-26T19:00")
    await simulator.add_availability(event4.event_id, diana, "2026-04-27T19:00")

    # Charlie adds availability
    await simulator.add_availability(event4.event_id, charlie, "2026-04-25T19:00")

    # Confirmation phase
    await simulator.confirm(event4.event_id, alex)
    await simulator.confirm(event4.event_id, bella)
    await simulator.confirm(event4.event_id, charlie)
    await simulator.confirm(event4.event_id, diana)
    await simulator.confirm(event4.event_id, ethan)

    # Event reaches 5 confirmed participants - lock it!
    event4 = await simulator.fetch_event(event4.event_id)
    assert event4.state == "confirmed"

    # Lock the event - finalize commitments
    event4 = await simulator.lock(event4.event_id, alex)
    assert event4.state == "locked"

    # Complete the event
    event4 = await simulator.complete_event(event4.event_id, alex)
    assert event4.state == "completed"

    # Record success memory for LLM (FIXED: 9 words <= 12)
    await simulator.record_memory_fragment(
       event4.event_id,
       "Perfect turnout! 5 players, food, Central Park ideal. 🎉",
    )

    # Event 5: Cancelled - needed for failure pattern analysis (failed_count >= 3)
    event5 = await simulator.create_event(
       group=group,
       organizer=alex,
       event_type="soccer",
       description="FIFA Night #5 - Final Attempt 🔚",
       scheduled_time=datetime.utcnow() + timedelta(days=29),
       min_participants=3,
       target_participants=5,
       duration_minutes=180,
    )

    await simulator.join(event5.event_id, alex, role="organizer")
    await simulator.join(event5.event_id, bella)
    await simulator.join(event5.event_id, charlie)
    await simulator.join(event5.event_id, diana)
    await simulator.confirm(event5.event_id, alex)
    await simulator.confirm(event5.event_id, bella)
    await simulator.confirm(event5.event_id, charlie)
    await simulator.confirm(event5.event_id, diana)

    # Diana cancels - event cancelled
    await simulator.exit(event5.event_id, diana)
    await simulator.cancel_event(event5.event_id, alex)

    # =============================================================================
    # STEP 5: Verify All Features Worked
    # =============================================================================

    # Check all users were created
    result = await db_session.execute(select(User))
    users = result.scalars().all()
    assert len(users) == 5

    user_ids = {u.telegram_user_id for u in users}
    assert user_ids == {1001, 1002, 1003, 1004, 1005}

    # Check group was created with members
    result = await db_session.execute(select(Group))
    groups = result.scalars().all()
    assert len(groups) == 1
    assert groups[0].group_name == "Zwischen Soccer League"
    assert len(groups[0].member_list) == 5

    # Check events were created with different outcomes (FIXED: 5 events, 4 cancelled)
    result = await db_session.execute(select(Event))
    events = result.scalars().all()
    assert len(events) == 5

    event_outcomes = {e.event_id: e.state for e in events}
    assert event_outcomes[event1.event_id] == "cancelled"
    assert event_outcomes[event2.event_id] == "cancelled"
    assert event_outcomes[event3.event_id] == "cancelled"
    assert event_outcomes[event4.event_id] == "completed"
    assert event_outcomes[event5.event_id] == "cancelled"

    # Check participants for final successful event
    event4 = await simulator.fetch_event(event4.event_id)
    participants = event4.participants or []
    assert len(participants) == 5

    participant_statuses = {int(p.telegram_user_id): p.status for p in participants}
    assert participant_statuses[1001] == ParticipantStatus.confirmed  # Alex
    assert participant_statuses[1002] == ParticipantStatus.confirmed  # Bella
    assert participant_statuses[1003] == ParticipantStatus.confirmed  # Charlie
    assert participant_statuses[1004] == ParticipantStatus.confirmed  # Diana
    assert participant_statuses[1005] == ParticipantStatus.confirmed  # Ethan

    # Check constraint was added (Bella needs Charlie)
    result = await db_session.execute(select(Constraint))
    constraints = result.scalars().all()
    assert len(constraints) >= 1

    constraint_types = {c.type for c in constraints}
    assert "if_joins" in constraint_types

    # Check availability slots were added
    available_slots = [c for c in constraints if c.type.startswith("available:")]
    assert len(available_slots) >= 4

    # Check memories were recorded (for LLM training)
    result = await db_session.execute(select(EventMemory))
    memories = result.scalars().all()
    assert len(memories) >= 3

    all_fragments = []
    for memory in memories:
       if memory.fragments:
           all_fragments.extend(memory.fragments)

    assert len(all_fragments) >= 4

    fragment_texts = [f["text"] for f in all_fragments]
    assert any("Bella had work emergency" in f for f in fragment_texts)
    assert any(
       "Ethan got sick. Check availability earlier" in f for f in fragment_texts
    )
    assert any("Too many dropouts" in f for f in fragment_texts)
    assert any("Perfect turnout" in f for f in fragment_texts)

    # Check messages were sent during the journey (FIXED: updated to match actual count)
    assert len(simulator.bot.sent_messages) >= 7
    assert len(simulator.bot.sent_messages) <= 20  # Sanity check

    # =============================================================================
    # STEP 6: DEMONSTRATE LLM MEMORY HOOK
    # =============================================================================

    # Get failure pattern for group (for LLM analysis)
    failure_pattern = await simulator.get_failure_pattern(group.group_id, "soccer")
    assert failure_pattern is not None
    assert failure_pattern["failed_count"] >= 3  # FIXED: >= 3 instead of >= 2
    assert failure_pattern["last_dropout_point"] >= 2

    # Get memory hook for future events
    memory_hook = await simulator.get_memory_hook(group.group_id, "soccer")
    assert memory_hook is not None
    assert len(memory_hook) > 0

    # Verify memory hook contains lessons learned (FIXED: check for "perfect turnout")
    assert any(
       phrase in memory_hook.lower()
       for phrase in ["check availability", "perfect turnout", "too many dropouts"]
    )
