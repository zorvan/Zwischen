"""
Full event lifecycle simulation test.

Covers the complete event lifecycle: proposed -> interested -> confirmed -> locked -> completed,
including rollback scenarios that expose database persistence bugs like the lock-state bug.

Run with: python -m tests.test_lifecycle_simulation
"""

import asyncio
import os
import sys
import itertools
import uuid

import pytest
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from telegram import Bot

# Add parent directory to path for local imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select

from db.connection import get_session
from db.models import (
    Group,
    Event,
    EventParticipant,
    ParticipantStatus,
    EventStateTransition,
)
from bot.services.event_lifecycle_service import EventLifecycleService
from bot.services.participant_service import ParticipantService
from bot.common.event_states import can_transition

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_URL = os.environ.get(
    "DATABASE_URL",
    os.environ.get(
        "POSTGRES_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/coord_bot_test",
    ),
)


@pytest.fixture(autouse=True)
def _use_test_database(test_db_url, monkeypatch):
    """Point every scenario at the migrated throwaway database.

    Requesting `test_db_url` is also what arms the truncate-between-tests
    fixture in conftest, so scenarios stop inheriting each other's rows.
    """
    monkeypatch.setattr(sys.modules[__name__], "DB_URL", test_db_url)


# Synthetic identity space. These must never be real Telegram accounts: this
# file is public, and the fixtures previously hardcoded a real user's name,
# username and account IDs.
#
# IDs are allocated per setup_test_data() call rather than fixed. Fixed IDs
# meant the second scenario in a session collided on users.telegram_user_id;
# the scenarios never asserted, so that failure went unnoticed.
# Use a unique suffix to avoid collisions between test runs
TEST_SUFFIX = uuid.uuid4().hex[:8]

# The base is randomized per run, not just per call. These scenarios do not
# clean up after themselves, so a per-process counter alone still collided
# with rows left behind by the previous run.
TEST_ID_BASE = 900_000_000_000 + int(TEST_SUFFIX[:6], 16) * 100
_id_counter = itertools.count(1)


def _next_identity() -> tuple[int, int, int]:
    """Allocate a fresh (organizer, participant, group) identity triple."""
    n = next(_id_counter) * 10
    return TEST_ID_BASE + n, TEST_ID_BASE + n + 1, -(TEST_ID_BASE + n + 2)


async def _require_database() -> None:
    """Skip rather than fail when no database is reachable.

    Must be awaited: the callers are async, so asyncio.run() here would raise
    "cannot be called from a running event loop".
    """
    import pytest

    from db.connection import check_db_connection

    ok, message = await check_db_connection(DB_URL)
    if not ok:
        pytest.skip(f"No database at {DB_URL.rsplit('@', 1)[-1]}: {message}")


def _assert_no_failures(results: list[str]) -> None:
    """Turn the [OK]/[FAIL] report into a real assertion.

    These tests previously only *returned* their report. pytest treats a
    returned value as a pass, so all seven reported green even when the
    database was unreachable and every step had failed.
    """
    failures = [r for r in results if "[FAIL]" in r or "FAIL:" in r]
    assert not failures, "scenario failed:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Mock Bot (no Telegram library needed)
# ---------------------------------------------------------------------------


def make_bot() -> "Bot":
    """Build a MockBot typed as telegram.Bot.

    The substitution is intentional (no API calls in tests); the cast states
    that once here instead of leaving an arg-type error at every call site.
    """
    return cast("Bot", MockBot())


class MockBot:
    """Stands in for telegram.Bot — no API calls are made."""

    async def send_message(self, chat_id: int, text: str, **kwargs):
        print(f"  [BOT MSG] chat={chat_id} text={text[:80]}...")
        return True


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def setup_test_data(session) -> dict[str, Any]:
    """Create test users, group, and event. Returns IDs."""
    now = datetime.now(timezone.utc)
    organizer_tg_id, participant_tg_id, group_tg_id = _next_identity()

    # Create test group
    group = Group(
        telegram_group_id=group_tg_id,
        group_name=f"Test Group {TEST_SUFFIX}",
        group_type="casual",
    )
    session.add(group)
    await session.flush()

    # Create organizer user
    from db.identity import resolve_telegram_user

    organizer = await resolve_telegram_user(
        session,
        organizer_tg_id,
        display_name="Test Organizer",
        username=f"test_organizer_{organizer_tg_id}",
    )

    # Create participant user
    participant = await resolve_telegram_user(
        session,
        participant_tg_id,
        display_name="Test Participant",
        username=f"test_participant_{participant_tg_id}",
    )
    await session.flush()

    # Create event in 'proposed' state
    scheduled = now + timedelta(days=7)
    commit_by = scheduled - timedelta(hours=12)

    event = Event(
        group_id=group.group_id,
        event_type="social",
        description=f"Test event {TEST_SUFFIX}",
        organizer_user_id=organizer.user_id,
        emergency_admin_user_id=organizer.user_id,
        scheduled_time=scheduled,
        commit_by=commit_by,
        duration_minutes=60,
        min_participants=2,
        target_participants=4,
        state="proposed",
        version=0,
    )
    session.add(event)
    await session.flush()

    return {
        "group": group,
        "organizer": organizer,
        "participant": participant,
        "event": event,
        "organizer_telegram_id": organizer.user_id,
        "participant_telegram_id": participant.user_id,
        "organizer_user_id": organizer.user_id,
        "participant_user_id": participant.user_id,
    }


async def add_participants(
    session, event_id: int, user_ids: list[int], status=ParticipantStatus.joined
) -> None:
    """Add participant records to an event."""
    for user_id in user_ids:
        participant = EventParticipant(
            event_id=event_id,
            user_id=user_id,
            status=status,
        )
        session.add(participant)


async def verify_event_state(session, event_id: int, expected_state: str) -> bool:
    """Verify the event is in the expected state in the database."""
    result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = result.scalar_one_or_none()
    actual = event.state if event else None
    return actual == expected_state


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


async def transition(
    session, lifecycle: EventLifecycleService, event_id: int, target: str, actor: int
) -> tuple[Any, bool]:
    """Run a lifecycle transition and return (event, transitioned)."""
    # Reload event to get current version
    result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = result.scalar_one_or_none()
    return await lifecycle.transition_with_lifecycle(
        event_id=event_id,
        target_state=target,
        actor_user_id=actor,
        source="test",
        reason=f"Test transition to {target}",
        expected_version=event.version if event else None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_full_lifecycle() -> list[str]:
    """Test the complete lifecycle: proposed -> interested -> confirmed -> locked -> completed."""
    await _require_database()
    results: list[str] = []
    bot = make_bot()

    print("\n=== Test: Full Lifecycle ===")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = data["organizer_telegram_id"]
            participant_id = data["participant_telegram_id"]

            # --- Step 1: proposed -> interested ---
            print("\n[1] proposed -> interested")
            lifecycle = EventLifecycleService(bot, session)
            event, ok = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            verified = await verify_event_state(session, event_id, "interested")
            results.append(
                f"  [{'OK' if verified else 'FAIL'}] "
                f"State is '{event.state}' (expected 'interested'), transitioned={ok}"
            )

            # --- Step 2: interested -> confirmed (with participants) ---
            print("\n[2] interested -> confirmed")
            await add_participants(
                session,
                event_id,
                [organizer_id, participant_id],
                status=ParticipantStatus.confirmed,
            )
            await session.commit()

            event, ok = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            await session.commit()

            verified = await verify_event_state(session, event_id, "confirmed")
            results.append(
                f"  [{'OK' if verified else 'FAIL'}] State is '{event.state}' (expected 'confirmed'), transitioned={ok}"
            )

            # --- Step 3: confirmed -> locked (THE BUG TEST) ---
            print("\n[3] confirmed -> locked  <-- THE BUG TEST")
            event, ok = await transition(
                session, lifecycle, event_id, "locked", organizer_id
            )
            # Commit IMMEDIATELY after transition — this is the fix
            await session.commit()

            verified = await verify_event_state(session, event_id, "locked")
            results.append(
                f"  [{'OK' if verified else 'FAIL'}] "
                f"State persisted as '{event.state}' (expected 'locked'), transitioned={ok}"
            )

            # Verify the transition was recorded in the audit trail
            # limit(1)/first(), not scalar_one_or_none(): by this step the
            # event has accumulated three transitions, and asking for "one or
            # none" from the full audit trail raises MultipleResultsFound.
            result = await session.execute(
                select(EventStateTransition)
                .where(EventStateTransition.event_id == event_id)
                .order_by(EventStateTransition.transition_id.desc())
                .limit(1)
            )
            last_transition = result.scalars().first()
            if last_transition:
                trail_msg = (
                    f"{last_transition.from_state} -> {last_transition.to_state}"
                )
            else:
                trail_msg = "N/A"
            results.append(
                f"  [{'OK' if last_transition and last_transition.to_state == 'locked' else 'FAIL'}] "
                f"Audit trail: {trail_msg}"
            )

            # --- Step 4: locked -> completed ---
            print("\n[4] locked -> completed")
            event, ok = await transition(
                session, lifecycle, event_id, "completed", organizer_id
            )
            await session.commit()

            verified = await verify_event_state(session, event_id, "completed")
            results.append(
                f"  [{'OK' if verified else 'FAIL'}] State is '{event.state}' (expected 'completed'), transitioned={ok}"
            )

    except Exception as e:
        results.append(f"  [FAIL] Exception: {type(e).__name__}: {e}")
        import traceback

        results.append(f"  {traceback.format_exc()[:500]}")

    _assert_no_failures(results)
    return results


async def test_lock_rollback_bug() -> list[str]:
    """
    Reproduce the exact bug: lifecycle transition succeeds but commit happens
    AFTER an exception, causing the state to roll back.

    This test verifies the fix: commit must happen BEFORE lifecycle side-effects
    that can fail.
    """
    await _require_database()
    results: list[str] = []
    bot = make_bot()

    print("\n=== Test: Lock Rollback Bug Reproduction ===")

    # --- Scenario A: OLD broken pattern (commit after lifecycle) ---
    print("\n[A] OLD pattern: commit AFTER lifecycle events (bug reproduces)")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = data["organizer_telegram_id"]

            # Get to confirmed state
            lifecycle = EventLifecycleService(bot, session)
            event, _ = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            event, _ = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            # Both participants, not just the organizer: setup_test_data sets
            # min_participants=2, so a single confirmed attendee is rejected by
            # the threshold check before the lock path under test is reached.
            await add_participants(
                session,
                event_id,
                [organizer_id, data["participant_telegram_id"]],
                status=ParticipantStatus.confirmed,
            )
            await session.commit()

            # Now try to lock — the lifecycle will try to query participants and send message
            # This simulates the OLD broken pattern where commit is outside the try block
            try:
                event, ok = await transition(
                    session, lifecycle, event_id, "locked", organizer_id
                )
                # OLD pattern: commit is AFTER this, outside any try block
                # If anything after this fails, the commit never happens
                # For this test, we'll simulate the failure by NOT committing
                # and checking that the state rolled back
                print(f"  Transition returned state={event.state}, ok={ok}")

                # Simulate what happens when an exception occurs BEFORE commit
                # In the real code, announce_event_locked could raise
                # The session context manager would then rollback
                raise RuntimeError("Simulated announcement failure")

            except RuntimeError:
                # In the old code, this would be caught and the session rolled back
                # without ever calling commit()
                print("  Exception caught (simulated announcement failure)")
                # Don't commit — this simulates the bug
                # The session context manager will rollback

        # Check if state persisted (it shouldn't in the broken pattern)
        async with get_session(DB_URL) as session:
            result = await session.execute(
                select(Event).where(Event.event_id == event_id)
            )
            event = result.scalar_one_or_none()
            if event:
                results.append(
                    f"  [INFO] After rollback: state='{event.state}' "
                    f"(expected 'confirmed' — the bug means locked was rolled back)"
                )
            else:
                results.append("  [INFO] Event not found after rollback")

    except Exception as e:
        results.append(f"  [FAIL] Setup error: {e}")

    # --- Scenario B: NEW fixed pattern (commit inside try block) ---
    print("\n[B] NEW pattern: commit INSIDE try block (bug is fixed)")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = data["organizer_telegram_id"]

            lifecycle = EventLifecycleService(bot, session)

            # Get to confirmed state
            event, _ = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            event, _ = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            # min_participants=2, so both attendees must be confirmed for the
            # lock below to be reachable at all.
            await add_participants(
                session,
                event_id,
                [organizer_id, data["participant_telegram_id"]],
                status=ParticipantStatus.confirmed,
            )
            await session.commit()

            # NEW pattern: commit INSIDE the try block, AFTER transition
            try:
                event, ok = await transition(
                    session, lifecycle, event_id, "locked", organizer_id
                )
                await session.commit()  # <-- COMMIT BEFORE any failing side-effects
                print(f"  Transition succeeded, state={event.state}")

                # Now simulate a side-effect failure (like announcement)
                raise RuntimeError("Simulated announcement failure after commit")

            except RuntimeError:
                print("  Exception caught (simulated announcement failure)")
                # The state transition was already committed, so it persists

        # Check if state persisted (it should in the fixed pattern)
        async with get_session(DB_URL) as session:
            result = await session.execute(
                select(Event).where(Event.event_id == event_id)
            )
            event = result.scalar_one_or_none()
            if event:
                persisted = event.state == "locked"
                results.append(
                    f"  [{'OK' if persisted else 'FAIL'}] After failure: state='{event.state}' "
                    f"({'persists correctly' if persisted else 'was rolled back — BUG!'})"
                )
            else:
                results.append("  [FAIL] Event not found after commit+failure")

    except Exception as e:
        results.append(f"  [FAIL] Setup error: {e}")

    _assert_no_failures(results)
    return results


async def test_unlock_transition() -> list[str]:
    """Test locked -> confirmed (unlock) transition."""
    await _require_database()
    results: list[str] = []
    bot = make_bot()

    print("\n=== Test: Unlock (locked -> confirmed) ===")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = data["organizer_telegram_id"]

            lifecycle = EventLifecycleService(bot, session)

            # Get to locked state
            event, _ = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            event, _ = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            # min_participants=2, so both attendees must be confirmed for the
            # lock below to be reachable at all.
            await add_participants(
                session,
                event_id,
                [organizer_id, data["participant_telegram_id"]],
                status=ParticipantStatus.confirmed,
            )
            await session.commit()

            event, ok = await transition(
                session, lifecycle, event_id, "locked", organizer_id
            )
            await session.commit()

            # Now unlock
            event, ok = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            await session.commit()

            verified = await verify_event_state(session, event_id, "confirmed")
            results.append(
                f"  [{'OK' if verified else 'FAIL'}] "
                f"Unlocked to '{event.state}' (expected 'confirmed'), transitioned={ok}"
            )

    except Exception as e:
        results.append(f"  [FAIL] Exception: {type(e).__name__}: {e}")

    _assert_no_failures(results)
    return results


async def test_state_machine_validity() -> list[str]:
    """Verify all expected transitions are allowed and all unexpected ones are rejected."""
    await _require_database()
    results: list[str] = []

    print("\n=== Test: State Machine Validity ===")

    # Valid transitions from each state
    valid_transitions: dict[str, list[str]] = {
        "proposed": ["interested", "cancelled"],
        "interested": ["confirmed", "cancelled"],
        "confirmed": ["locked", "proposed", "cancelled"],
        # The state machine deliberately allows cancelling a locked event
        # (emergencies happen); bot/common/event_states.py is the authority.
        "locked": ["confirmed", "completed", "cancelled"],
        "completed": [],
        "cancelled": [],
    }

    for from_state, allowed_to in valid_transitions.items():
        for to_state in allowed_to:
            can = can_transition(from_state, to_state)
            results.append(
                f"  [{'OK' if can else 'FAIL'}] {from_state} -> {to_state}: can_transition={can}"
            )

    # Test that invalid transitions are rejected
    invalid_pairs = [
        ("proposed", "locked"),
        ("proposed", "completed"),
        ("interested", "locked"),
        ("interested", "completed"),
        ("confirmed", "completed"),
        # ("locked", "cancelled") is deliberately ALLOWED -- a locked event
        # can still be cancelled in an emergency. See event_states.py.
        ("completed", "locked"),
    ]

    for from_state, to_state in invalid_pairs:
        can = can_transition(from_state, to_state)
        results.append(
            f"  [{'OK' if not can else 'FAIL'}] {from_state} -> {to_state}: can_transition={can} (should be False)"
        )

    _assert_no_failures(results)
    return results


async def test_participant_finalization() -> list[str]:
    """Test that finalize_commitments correctly sets participant statuses for a locked event."""
    await _require_database()
    results: list[str] = []
    bot = make_bot()

    print("\n=== Test: Participant Finalization on Lock ===")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = data["organizer_telegram_id"]
            participant_id = data["participant_telegram_id"]

            lifecycle = EventLifecycleService(bot, session)
            participant_service = ParticipantService(session)

            # Get to confirmed state with mixed participant statuses
            event, _ = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            event, _ = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )

            # Add participants with different statuses
            await add_participants(
                session, event_id, [organizer_id], status=ParticipantStatus.confirmed
            )
            await add_participants(
                session, event_id, [participant_id], status=ParticipantStatus.joined
            )
            await session.commit()

            # Finalize commitments (this is what happens during lock)
            await participant_service.finalize_commitments(event_id)
            await session.commit()

            # Verify statuses
            result = await session.execute(
                select(EventParticipant).where(EventParticipant.event_id == event_id)
            )
            participants = result.scalars().all()

            for p in participants:
                results.append(f"  [INFO] User {p.user_id}: status={p.status.value}")

    except Exception as e:
        results.append(f"  [FAIL] Exception: {type(e).__name__}: {e}")
        import traceback

        results.append(f"  {traceback.format_exc()[:500]}")

    _assert_no_failures(results)
    return results


async def test_concurrent_version_conflict() -> list[str]:
    """Test that optimistic concurrency control catches concurrent modifications."""
    await _require_database()
    results: list[str] = []
    bot = make_bot()

    print("\n=== Test: Optimistic Concurrency Control ===")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = data["organizer_telegram_id"]

            # Get the event and its version
            result = await session.execute(
                select(Event).where(Event.event_id == event_id)
            )
            event = result.scalar_one_or_none()
            old_version = event.version

            # First transition (uses old_version)
            lifecycle = EventLifecycleService(bot, session)
            event, ok = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            # Try to transition again with the OLD version (should fail)
            try:
                result = await session.execute(
                    select(Event).where(Event.event_id == event_id)
                )
                event = result.scalar_one_or_none()
                await lifecycle.transition_with_lifecycle(
                    event_id=event_id,
                    target_state="confirmed",
                    actor_user_id=organizer_id,
                    source="test",
                    expected_version=old_version,  # Stale version!
                )
                results.append("  [FAIL] Should have raised ConcurrencyConflictError")
            except Exception as e:
                if "version" in str(e).lower() or "conflict" in str(e).lower():
                    results.append(
                        f"  [OK] Concurrency conflict detected: {type(e).__name__}"
                    )
                else:
                    results.append(
                        f"  [WARN] Got exception but not clearly a version conflict: {type(e).__name__}: {e}"
                    )

    except Exception as e:
        results.append(f"  [FAIL] Exception: {type(e).__name__}: {e}")

    _assert_no_failures(results)
    return results


async def test_timezone_handling_in_materialization() -> list[str]:
    """
    Regression test for the timezone subtraction bug:
    get_time_framing_tier was using datetime.utcnow() (naive) with
    event.scheduled_time from PostgreSQL (aware), causing:
    TypeError: can't subtract offset-naive and offset-aware datetimes

    This test verifies that the materialization layer handles both
    timezone-aware and naive datetimes correctly.
    """
    await _require_database()
    results: list[str] = []

    print("\n=== Test: Timezone Handling in Materialization ===")

    # Import the function being tested
    from bot.common.materialization import get_time_framing_tier
    from unittest.mock import MagicMock

    # Test 1: Event with timezone-aware scheduled_time (PostgreSQL default)
    aware_now = datetime.now(timezone.utc)
    aware_future = aware_now + timedelta(hours=48)

    mock_event_aware = MagicMock()
    mock_event_aware.scheduled_time = aware_future
    mock_event_aware.event_id = 999

    try:
        tier = get_time_framing_tier(mock_event_aware)
        results.append(
            f"  [{'OK' if tier == 'warm' else 'FAIL'}] Aware datetime -> tier={tier} (expected 'warm')"
        )
    except TypeError as e:
        results.append(f"  [FAIL] Aware datetime raised TypeError: {e}")

    # Test 2: Event with naive scheduled_time (edge case, should still work)
    naive_future = datetime.utcnow() + timedelta(hours=48)
    mock_event_naive = MagicMock()
    mock_event_naive.scheduled_time = naive_future
    mock_event_naive.event_id = 998

    try:
        tier = get_time_framing_tier(mock_event_naive)
        results.append(
            f"  [{'OK' if tier == 'warm' else 'FAIL'}] Naive datetime -> tier={tier} (expected 'warm')"
        )
    except TypeError as e:
        results.append(f"  [FAIL] Naive datetime raised TypeError: {e}")

    # Test 3: Event with string scheduled_time (ISO format with timezone)
    iso_string = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
    mock_event_string = MagicMock()
    mock_event_string.scheduled_time = iso_string
    mock_event_string.event_id = 997

    try:
        tier = get_time_framing_tier(mock_event_string)
        results.append(
            f"  [{'OK' if tier == 'urgent' else 'FAIL'}] ISO string -> tier={tier} (expected 'urgent')"
        )
    except TypeError as e:
        results.append(f"  [FAIL] ISO string raised TypeError: {e}")

    # Test 4: Event with no scheduled_time
    mock_event_none = MagicMock()
    mock_event_none.scheduled_time = None

    try:
        tier = get_time_framing_tier(mock_event_none)
        results.append(
            f"  [{'OK' if tier == 'light' else 'FAIL'}] None scheduled_time -> tier={tier} (expected 'light')"
        )
    except Exception as e:
        results.append(f"  [FAIL] None scheduled_time raised {type(e).__name__}: {e}")

    # Test 5: Full lifecycle with aware datetimes (reproduces the original bug scenario)
    print("\n[5] Full lifecycle with timezone-aware datetimes")
    bot = make_bot()
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = data["organizer_telegram_id"]

            # Verify the event's scheduled_time is timezone-aware (PostgreSQL stores with TZ)
            result = await session.execute(
                select(Event).where(Event.event_id == event_id)
            )
            event = result.scalar_one_or_none()
            if event and event.scheduled_time:
                has_tz = event.scheduled_time.tzinfo is not None
                results.append(f"  [INFO] DB scheduled_time has timezone: {has_tz}")

            lifecycle = EventLifecycleService(bot, session)

            # Get to confirmed state
            event, _ = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            event, _ = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            # min_participants=2, so both attendees must be confirmed for the
            # lock below to be reachable at all.
            await add_participants(
                session,
                event_id,
                [organizer_id, data["participant_telegram_id"]],
                status=ParticipantStatus.confirmed,
            )
            await session.commit()

            # This is where the original bug occurred
            event, ok = await transition(
                session, lifecycle, event_id, "locked", organizer_id
            )
            await session.commit()

            verified = await verify_event_state(session, event_id, "locked")
            results.append(
                f"  [{'OK' if verified else 'FAIL'}] Lock succeeded with aware TZ datetimes, state={event.state}"
            )

    except TypeError as e:
        if "offset-naive" in str(e) or "offset-aware" in str(e):
            results.append(f"  [FAIL] Timezone bug reproduced: {e}")
        else:
            results.append(f"  [FAIL] Unexpected TypeError: {e}")
    except Exception as e:
        results.append(f"  [FAIL] Exception: {type(e).__name__}: {e}")

    _assert_no_failures(results)
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("Event Lifecycle Simulation Tests")
    print(f"DB URL: {DB_URL}")
    print("=" * 60)

    all_results: list[str] = []

    # Test 1: Full lifecycle
    all_results.extend(await test_full_lifecycle())

    # Test 2: Lock rollback bug reproduction
    all_results.extend(await test_lock_rollback_bug())

    # Test 3: Unlock transition
    all_results.extend(await test_unlock_transition())

    # Test 4: State machine validity
    all_results.extend(await test_state_machine_validity())

    # Test 5: Participant finalization
    all_results.extend(await test_participant_finalization())

    # Test 6: Concurrent version conflict
    all_results.extend(await test_concurrent_version_conflict())

    # Test 7: Timezone handling in materialization
    all_results.extend(await test_timezone_handling_in_materialization())

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    failures = [r for r in all_results if "[FAIL]" in r]
    oks = [r for r in all_results if "[OK]" in r]
    warns = [r for r in all_results if "[WARN]" in r]
    infos = [r for r in all_results if "[INFO]" in r]

    print(f"  Passed: {len(oks)}")
    print(f"  Failed: {len(failures)}")
    print(f"  Warnings: {len(warns)}")
    print(f"  Info: {len(infos)}")

    if failures:
        print("\n  FAILURES:")
        for f in failures:
            print(f"    {f}")

    print("\n" + "=" * 60)
    if failures:
        print("RESULT: FAIL")
        sys.exit(1)
    else:
        print("RESULT: PASS")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
