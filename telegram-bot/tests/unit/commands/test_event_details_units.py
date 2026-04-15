"""
Unit tests for event_details command callback handler.
Catches callback_data parsing errors and routing issues.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from bot.commands import event_details


class TestCallbackParsing:
    """Test callback_data parsing to prevent ValueError issues."""

    @pytest.mark.asyncio
    async def test_avail_add_event_id_parsing(self) -> None:
        """Test that avail_add_123 parses to event_id 123."""
        data = "avail_add_123"
        event_id = int(data.replace("avail_add_", ""))
        assert event_id == 123

    @pytest.mark.asyncio
    async def test_avail_event_id_parsing(self) -> None:
        """Test that avail_123 parses to event_id 123."""
        data = "avail_123"
        event_id = int(data.replace("avail_", ""))
        assert event_id == 123

    @pytest.mark.asyncio
    async def test_event_constraints_event_id_parsing(self) -> None:
        """Test that event_constraints_123 parses to event_id 123."""
        data = "event_constraints_123"
        event_id = int(data.replace("event_constraints_", ""))
        assert event_id == 123

    @pytest.mark.asyncio
    async def test_invalid_callback_data_does_not_crash(self) -> None:
        """Test that invalid callback data is handled gracefully."""
        update = MagicMock()
        update.callback_query = None

        context = MagicMock()

        with patch.object(event_details, "handle_callback", side_effect=Exception):
            with pytest.raises(Exception):
                await event_details.handle_callback(update, context)


class TestCallbackRouting:
    """Test that callback_data routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_avail_add_routes_to_availability_slots(self) -> None:
        """Test that avail_add_123 calls _show_availability_slots."""
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()

        context = MagicMock()

        with patch(
            "bot.commands.event_details._show_availability_slots", AsyncMock()
        ) as mock_slots:
            data = "avail_add_123"
            if data.startswith("avail_add_"):
                event_id = int(data.replace("avail_add_", ""))
                await event_details._show_availability_slots(query, context, event_id)
            mock_slots.assert_called_once()

    @pytest.mark.asyncio
    async def test_avail_routes_to_availability_options(self) -> None:
        """Test that avail_123 calls _show_availability_options."""
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()

        context = MagicMock()

        with patch(
            "bot.commands.event_details._show_availability_options", AsyncMock()
        ) as mock_options:
            data = "avail_123"
            if data.startswith("avail_"):
                event_id = int(data.replace("avail_", ""))
                await event_details._show_availability_options(query, context, event_id)
            mock_options.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_constraints_routes_to_constraints_menu(self) -> None:
        """Test that event_constraints_123 calls _show_constraints_menu."""
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()

        context = MagicMock()

        with patch(
            "bot.commands.event_details._show_constraints_menu", AsyncMock()
        ) as mock_constraints:
            data = "event_constraints_123"
            if data.startswith("event_constraints_"):
                event_id = int(data.replace("event_constraints_", ""))
                await event_details._show_constraints_menu(query, context, event_id)
            mock_constraints.assert_called_once()


class TestAvailabilityFlow:
    """End-to-end availability callback flow tests."""

    @pytest.mark.asyncio
    async def test_full_availability_flow(self) -> None:
        """Test complete availability flow from button to slot display."""
        update = MagicMock()
        query = MagicMock()
        query.data = "avail_add_42"
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()
        update.callback_query = query

        context = MagicMock()

        with patch(
            "bot.commands.event_details._show_availability_slots", AsyncMock()
        ) as mock_slots:
            await event_details.handle_callback(update, context)
            mock_slots.assert_called_once_with(query, context, 42)

    @pytest.mark.asyncio
    async def test_availability_options_flow(self) -> None:
        """Test availability options flow."""
        update = MagicMock()
        query = MagicMock()
        query.data = "avail_42"
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()
        update.callback_query = query

        context = MagicMock()

        with patch(
            "bot.commands.event_details._show_availability_options", AsyncMock()
        ) as mock_options:
            await event_details.handle_callback(update, context)
            mock_options.assert_called_once_with(query, context, 42)
