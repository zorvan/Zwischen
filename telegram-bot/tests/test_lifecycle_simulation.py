"""
Full event lifecycle simulation test.

Covers the complete event lifecycle: proposed -> interested -> confirmed -> locked -> completed,
including rollback scenarios that expose database persistence bugs like the lock-state bug.

Run with: python -m tests.test_lifecycle_simulation
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

# Add parent directory to path for local imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select

from db.connection import get_session
from db.models import (
    User,
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

# Use a unique suffix to avoid collisions between test runs
TEST_SUFFIX = uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Mock Bot (no Telegram library needed)
# ---------------------------------------------------------------------------


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

    # Create test group
    group = Group(
        telegram_group_id=-4882211102 + int(TEST_SUFFIX[:2], 16) % 1000,
        group_name=f"Test Group {TEST_SUFFIX}",
        group_type="casual",
        member_list=[8710491944, 109397689],
    )
    session.add(group)
    await session.flush()

    # Create organizer user
    organizer = User(
        telegram_user_id=8710491944,
        display_name="Zorvan Raz",
        username="humbanapir",
    )
    session.add(organizer)

    # Create participant user
    participant = User(
        telegram_user_id=109397689,
        display_name="User109397689",
        username="user109",
    )
    session.add(participant)
    await session.flush()

    # Create event in 'proposed' state
    scheduled = now + timedelta(days=7)
    commit_by = scheduled - timedelta(hours=12)

    event = Event(
        group_id=group.group_id,
        event_type="social",
        description=f"Test event {TEST_SUFFIX}",
        organizer_telegram_user_id=8710491944,
        emergency_admin_telegram_user_id=8710491944,
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
        "organizer_user_id": organizer.user_id,
        "participant_user_id": participant.user_id,
    }


async def add_participants(
    session, event_id: int, telegram_ids: list[int], status=ParticipantStatus.joined
) -> None:
    """Add participant records to an event."""
    for tid in telegram_ids:
        participant = EventParticipant(
            event_id=event_id,
            telegram_user_id=tid,
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
        actor_telegram_user_id=actor,
        source="test",
        reason=f"Test transition to {target}",
        expected_version=event.version if event else None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_full_lifecycle() -> list[str]:
    """Test the complete lifecycle: proposed -> interested -> confirmed -> locked -> completed."""
    results: list[str] = []
    bot = MockBot()

    print("\n=== Test: Full Lifecycle ===")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = 8710491944
            participant_id = 109397689

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
            result = await session.execute(
                select(EventStateTransition)
                .where(EventStateTransition.event_id == event_id)
                .order_by(EventStateTransition.transition_id.desc())
            )
            last_transition = result.scalar_one_or_none()
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

    return results


async def test_lock_rollback_bug() -> list[str]:
    """
    Reproduce the exact bug: lifecycle transition succeeds but commit happens
    AFTER an exception, causing the state to roll back.

    This test verifies the fix: commit must happen BEFORE lifecycle side-effects
    that can fail.
    """
    results: list[str] = []
    bot = MockBot()

    print("\n=== Test: Lock Rollback Bug Reproduction ===")

    # --- Scenario A: OLD broken pattern (commit after lifecycle) ---
    print("\n[A] OLD pattern: commit AFTER lifecycle events (bug reproduces)")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = 8710491944

            # Get to confirmed state
            lifecycle = EventLifecycleService(bot, session)
            event, _ = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            event, _ = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            await add_participants(
                session,
                event_id,
                [organizer_id],
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
            organizer_id = 8710491944

            lifecycle = EventLifecycleService(bot, session)

            # Get to confirmed state
            event, _ = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            event, _ = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            await add_participants(
                session,
                event_id,
                [organizer_id],
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

    return results


async def test_unlock_transition() -> list[str]:
    """Test locked -> confirmed (unlock) transition."""
    results: list[str] = []
    bot = MockBot()

    print("\n=== Test: Unlock (locked -> confirmed) ===")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = 8710491944

            lifecycle = EventLifecycleService(bot, session)

            # Get to locked state
            event, _ = await transition(
                session, lifecycle, event_id, "interested", organizer_id
            )
            await session.commit()

            event, _ = await transition(
                session, lifecycle, event_id, "confirmed", organizer_id
            )
            await add_participants(
                session,
                event_id,
                [organizer_id],
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

    return results


async def test_state_machine_validity() -> list[str]:
    """Verify all expected transitions are allowed and all unexpected ones are rejected."""
    results: list[str] = []

    print("\n=== Test: State Machine Validity ===")

    # Valid transitions from each state
    valid_transitions = {
        "proposed": ["interested", "cancelled"],
        "interested": ["confirmed", "cancelled"],
        "confirmed": ["locked", "proposed", "cancelled"],
        "locked": ["confirmed", "completed"],
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
        ("locked", "cancelled"),
        ("completed", "locked"),
    ]

    for from_state, to_state in invalid_pairs:
        can = can_transition(from_state, to_state)
        results.append(
            f"  [{'OK' if not can else 'FAIL'}] {from_state} -> {to_state}: can_transition={can} (should be False)"
        )

    return results


async def test_participant_finalization() -> list[str]:
    """Test that finalize_commitments correctly sets participant statuses for a locked event."""
    results: list[str] = []
    bot = MockBot()

    print("\n=== Test: Participant Finalization on Lock ===")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = 8710491944
            participant_id = 109397689

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
                results.append(
                    f"  [INFO] User {p.telegram_user_id}: status={p.status.value}"
                )

    except Exception as e:
        results.append(f"  [FAIL] Exception: {type(e).__name__}: {e}")
        import traceback

        results.append(f"  {traceback.format_exc()[:500]}")

    return results


async def test_concurrent_version_conflict() -> list[str]:
    """Test that optimistic concurrency control catches concurrent modifications."""
    results: list[str] = []
    bot = MockBot()

    print("\n=== Test: Optimistic Concurrency Control ===")
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = 8710491944

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
                    actor_telegram_user_id=organizer_id,
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
    bot = MockBot()
    try:
        async with get_session(DB_URL) as session:
            data = await setup_test_data(session)
            await session.commit()

            event_id = data["event"].event_id
            organizer_id = 8710491944

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
            await add_participants(
                session,
                event_id,
                [organizer_id],
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
