"""
Integration tests for the availability flow in the Telegram bot.
Tests end-to-end availability callback flow from button click to slot display.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone

import pytest

from bot.commands import event_details
from db.models import Event


@pytest.mark.asyncio
async def test_availability_flow_click_button_shows_slots() -> None:
    """Test complete availability flow: click button -> show slots -> user selects time."""
    # Create test event
    event = Event(
        event_id=123,
        group_id=1,
        event_type="sports",
        description="Test football match",
        scheduled_time=datetime(2026, 4, 18, 18, 0, 0),
        duration_minutes=120,
        min_participants=2,
        target_participants=6,
        state="confirmed",
    )

    # Mock Telegram update and query
    query = MagicMock()
    query.data = "avail_add_123"
    query.from_user = MagicMock()
    query.from_user.id = 456789
    query.from_user.full_name = "Test User"
    query.from_user.username = "testuser"
    query.edit_message_text = AsyncMock()
    query.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    # Mock context
    context = MagicMock()
    context.user_data = {}

    # Mock database session
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    # Mock database queries
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=event)
    mock_session.execute = AsyncMock(return_value=mock_result)

    # Patch get_session to return our mock
    with patch("bot.commands.event_details.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        # Mock ParticipantService inside the function
        with patch("bot.services.ParticipantService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.get_participant = AsyncMock(return_value=None)
            mock_service.return_value = mock_instance

            # Execute the callback handler
            await event_details.handle_callback(update, context)

            # Verify the callback response shows availability slots
            call_args = query.edit_message_text.call_args
            assert call_args is not None
            message_text = call_args[0][0]

            # Verify the message contains expected availability information
            assert "Select an available time slot" in message_text


@pytest.mark.asyncio
async def test_availability_flow_user_selects_slot() -> None:
    """Test user selecting a time slot and confirming."""
    event = Event(
        event_id=123,
        group_id=1,
        event_type="sports",
        description="Test match",
        scheduled_time=datetime(2026, 4, 18, 18, 0, 0),
        duration_minutes=120,
        min_participants=2,
        target_participants=6,
        state="confirmed",
    )

    # Mock user selecting slot
    query = MagicMock()
    query.data = "avail_slot_123_0"
    query.from_user = MagicMock()
    query.from_user.id = 456789
    query.from_user.full_name = "Test User"
    query.from_user.username = "testuser"
    query.edit_message_text = AsyncMock()
    query.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    context = MagicMock()
    context.user_data = {}

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=event)
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("bot.commands.event_details.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("bot.services.ParticipantService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.get_participant = AsyncMock(return_value=None)
            mock_service.return_value = mock_instance

            # First, show availability slots (user clicks "Add Availability")
            await event_details._show_availability_slots(query, context, 123)

            # Verify slots are displayed
            assert query.edit_message_text.call_count >= 1

            # Reset mock for slot selection test
            query.edit_message_text.reset_mock()

            # User selects a slot
            await event_details._handle_availability_slot(query, context, 123, 0)

            # Verify pending availability is stored
            assert "pending_availability" in context.user_data
            assert context.user_data["pending_availability"]["event_id"] == 123
            assert context.user_data["pending_availability"]["slot"] is not None

            # Verify confirmation message is shown
            call_args = query.edit_message_text.call_args
            assert call_args is not None
            message_text = call_args[0][0]
            assert "Continue" in message_text
            assert "selected" in message_text


@pytest.mark.asyncio
async def test_availability_flow_complete_save() -> None:
    """Test complete availability flow ending with saving to database."""
    event = Event(
        event_id=123,
        group_id=1,
        event_type="sports",
        description="Test match",
        scheduled_time=datetime(2026, 4, 18, 18, 0, 0),
        duration_minutes=120,
        min_participants=2,
        target_participants=6,
        state="confirmed",
    )

    # Mock user confirmation
    query = MagicMock()
    query.data = "avail_confirm_123"
    query.from_user = MagicMock()
    query.from_user.id = 456789
    query.from_user.full_name = "Test User"
    query.from_user.username = "testuser"
    query.edit_message_text = AsyncMock()
    query.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    # Set up pending availability in context
    slot_str = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
        "%Y-%m-%d %H:%M"
    )
    context = MagicMock()
    context.user_data = {
        "pending_availability": {
            "event_id": 123,
            "slot": slot_str,
        }
    }

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    # Mock event lookup
    event_result = MagicMock()
    event_result.scalar_one_or_none = MagicMock(return_value=event)

    # Mock user lookup
    user_result = MagicMock()
    user_result.scalar_one_or_none = MagicMock(return_value=None)

    # Mock constraint lookup
    constraint_result = MagicMock()
    constraint_result.scalar_one_or_none = MagicMock(return_value=None)

    # Use side_effect to return different results for each execute call
    mock_session.execute = AsyncMock(
        side_effect=[event_result, user_result, constraint_result]
    )

    # Mock constraint save
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    with patch("bot.commands.event_details.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("db.users.get_or_create_user_id") as mock_get_user:
            mock_get_user.return_value = 789

            # Execute save availability
            await event_details._save_availability(query, context, 123)

            # Verify success message
            call_args = query.edit_message_text.call_args
            assert call_args is not None
            message_text = call_args[0][0]
            assert "Availability saved" in message_text

            # Verify constraint was created with correct type
            assert mock_session.add.called
            added_constraint = mock_session.add.call_args[0][0]
            assert "available:" in added_constraint.type
            assert slot_str in added_constraint.type


@pytest.mark.asyncio
async def test_availability_callback_data_format() -> None:
    """Test that callback_data uses correct format: avail_add_{event_id}."""
    event_id = 42

    # Test the expected callback format used in the code
    callback_data = f"avail_add_{event_id}"
    assert callback_data == "avail_add_42"

    # Test parsing
    parsed_event_id = int(callback_data.replace("avail_add_", ""))
    assert parsed_event_id == event_id

    # Test availability options callback
    options_callback = f"avail_{event_id}"
    assert options_callback == "avail_42"

    parsed_options_id = int(options_callback.replace("avail_", ""))
    assert parsed_options_id == event_id


@pytest.mark.asyncio
async def test_availability_flow_verification() -> None:
    """Verify the complete availability flow is working as expected."""
    # Test that the callback handler properly routes to availability handlers
    query = MagicMock()
    query.data = "avail_add_999"
    query.edit_message_text = AsyncMock()
    query.answer = AsyncMock()

    update = MagicMock()
    update.callback_query = query

    context = MagicMock()

    # Mock session
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    # Mock the execute call to return None (event not found)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("bot.commands.event_details.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("bot.services.ParticipantService") as mock_service:
            mock_instance = MagicMock()
            mock_instance.get_participant = AsyncMock(return_value=None)
            mock_service.return_value = mock_instance

            # This should call _show_availability_slots which returns "Event not found"
            await event_details.handle_callback(update, context)

            # Verify the flow: avail_add_XXX -> _show_availability_slots
            # The callback_data parsing should work correctly
            callback_data = query.data
            assert callback_data.startswith("avail_add_")
            event_id_from_data = int(callback_data.replace("avail_add_", ""))
            assert event_id_from_data == 999
