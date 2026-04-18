#!/usr/bin/env python3
"""Tests for bot/handlers/event_panel.py - New v3.5 Event Panel.

Tests the redesigned event panel with:
- Compact callback format (ev:{id}:act)
- Context-aware buttons
- Enrich and Constraint sub-menus
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestEventPanelRouter:
    """Tests for the event panel callback router."""

    @pytest.fixture
    def mock_update(self):
        """Create a mock Telegram update."""
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_chat.id = 67890
        update.callback_query = MagicMock()
        update.callback_query.data = "ev:1:view"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock Telegram context."""
        context = MagicMock()
        context.bot = MagicMock()
        return context

    @pytest.mark.asyncio
    async def test_route_callback_basic(self, mock_update, mock_context):
        """Test routing a basic callback."""
        from bot.handlers.event_panel import route_event_callback
        
        # Should route without error
        with patch('bot.handlers.event_panel.decode_callback', return_value=("view", 1)):
            with patch('bot.handlers.event_panel._handle_view', new_callable=AsyncMock) as mock_handler:
                await route_event_callback(mock_update, mock_context)
                mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_invalid_callback(self, mock_update, mock_context):
        """Test routing invalid callback data."""
        from bot.handlers.event_panel import route_event_callback
        
        mock_update.callback_query.data = "invalid_format"
        
        with patch('bot.handlers.event_panel.decode_callback', return_value=(None, None)):
            result = await route_event_callback(mock_update, mock_context)
            # Should handle gracefully
            mock_update.callback_query.answer.assert_called_once()


class TestButtonBuilders:
    """Tests for button building functions."""

    def test_build_main_panel_buttons(self):
        """Test building main event panel buttons."""
        from bot.handlers.event_panel import build_main_panel_buttons
        from db.models import ParticipantStatus
        
        # Test for joined user
        buttons = build_main_panel_buttons(
            event_id=1,
            user_status=ParticipantStatus.joined,
            is_organizer=False,
            event_state="proposed"
        )
        
        assert isinstance(buttons, list)
        # Should have [Enrich] [Constraint] row
        # Should have [Relinquish] row (for joined users)
        # Should have [Commit] if threshold met
        # Should have [Back] row

    def test_build_enrich_submenu(self):
        """Test building Enrich sub-menu buttons."""
        from bot.handlers.event_panel import build_enrich_submenu
        
        buttons = build_enrich_submenu(event_id=1)
        
        assert isinstance(buttons, list)
        # Should have: [Idea] [Hashtag] [Memory]
        # Should have: [View My Contributions]
        # Should have: [Back to Panel]

    def test_build_constraint_submenu(self):
        """Test building Constraint sub-menu buttons."""
        from bot.handlers.event_panel import build_constraint_submenu
        
        buttons = build_constraint_submenu(event_id=1)
        
        assert isinstance(buttons, list)
        # Should have constraint type buttons
        # Should have: [Suggest Time] [Negotiate]
        # Should have: [Back to Panel]

    def test_button_callback_format(self):
        """Test that buttons use compact callback format."""
        from bot.handlers.event_panel import build_main_panel_buttons
        from telegram import InlineKeyboardButton
        
        buttons = build_main_panel_buttons(
            event_id=123,
            user_status=None,
            is_organizer=False,
            event_state="proposed"
        )
        
        # Flatten and check all buttons
        for row in buttons:
            for button in row:
                if isinstance(button, InlineKeyboardButton):
                    # Callback data should be compact format
                    assert button.callback_data.startswith("ev:"), \
                        f"Button {button.text} has non-compact callback: {button.callback_data}"
                    # Should be under 64 bytes
                    assert len(button.callback_data) <= 64, \
                        f"Button {button.text} exceeds 64 bytes: {len(button.callback_data)}"


class TestContextAwareButtons:
    """Tests for context-aware button visibility."""

    def test_joined_user_sees_relinquish(self):
        """Test that joined users see Relinquish button."""
        from bot.handlers.event_panel import build_main_panel_buttons
        from db.models import ParticipantStatus
        
        buttons = build_main_panel_buttons(
            event_id=1,
            user_status=ParticipantStatus.joined,
            is_organizer=False,
            event_state="proposed"
        )
        
        # Flatten button texts
        all_texts = []
        for row in buttons:
            for btn in row:
                all_texts.append(btn.text.lower())
        
        # Should have relinquish/leave option
        assert any("relinquish" in t or "leave" in t for t in all_texts)

    def test_non_participant_sees_join(self):
        """Test that non-participants see Join button."""
        from bot.handlers.event_panel import build_main_panel_buttons
        
        buttons = build_main_panel_buttons(
            event_id=1,
            user_status=None,
            is_organizer=False,
            event_state="proposed"
        )
        
        all_texts = [btn.text.lower() for row in buttons for btn in row]
        
        # Should have join option
        assert any("join" in t for t in all_texts)

    def test_organizer_sees_lock_button(self):
        """Test that organizers see Lock button."""
        from bot.handlers.event_panel import build_main_panel_buttons
        from db.models import ParticipantStatus
        
        buttons = build_main_panel_buttons(
            event_id=1,
            user_status=ParticipantStatus.joined,
            is_organizer=True,
            event_state="confirmed"  # Ready to lock
        )
        
        all_texts = [btn.text.lower() for row in buttons for btn in row]
        
        # Should have lock option
        assert any("lock" in t for t in all_texts)

    def test_locked_event_shows_different_buttons(self):
        """Test that locked events show different action set."""
        from bot.handlers.event_panel import build_main_panel_buttons
        from db.models import ParticipantStatus
        
        buttons = build_main_panel_buttons(
            event_id=1,
            user_status=ParticipantStatus.confirmed,
            is_organizer=False,
            event_state="locked"
        )
        
        all_texts = [btn.text.lower() for row in buttons for btn in row]
        
        # Locked events shouldn't show commit/relinquish
        # Should show different options


class TestHandleEnrichSubmenu:
    """Tests for Enrich sub-menu handlers."""

    @pytest.mark.asyncio
    async def test_show_enrich_menu(self):
        """Test showing the Enrich sub-menu."""
        from bot.handlers.event_panel import handle_enrich_menu
        from telegram.ext import ContextTypes
        
        mock_query = MagicMock()
        mock_query.edit_message_text = AsyncMock()
        mock_query.answer = AsyncMock()
        mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await handle_enrich_menu(mock_query, mock_context, event_id=1)
        
        mock_query.edit_message_text.assert_called_once()
        # Should show enrich options

    @pytest.mark.asyncio
    async def test_handle_add_idea_prompt(self):
        """Test showing add idea prompt."""
        from bot.handlers.event_panel import handle_add_idea_prompt
        from telegram.ext import ContextTypes
        
        mock_query = MagicMock()
        mock_query.edit_message_text = AsyncMock()
        mock_query.answer = AsyncMock()
        mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await handle_add_idea_prompt(mock_query, mock_context, event_id=1)
        
        mock_query.edit_message_text.assert_called_once()
        mock_query.answer.assert_called_once()


class TestHandleConstraintSubmenu:
    """Tests for Constraint sub-menu handlers."""

    @pytest.mark.asyncio
    async def test_show_constraint_menu(self):
        """Test showing the Constraint sub-menu."""
        from bot.handlers.event_panel import handle_constraint_menu
        from telegram.ext import ContextTypes
        
        mock_query = MagicMock()
        mock_query.edit_message_text = AsyncMock()
        mock_query.answer = AsyncMock()
        mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await handle_constraint_menu(mock_query, mock_context, event_id=1)
        
        mock_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_add_constraint_prompt(self):
        """Test showing add constraint prompt."""
        from bot.handlers.event_panel import handle_add_constraint_prompt
        from telegram.ext import ContextTypes
        
        mock_query = MagicMock()
        mock_query.edit_message_text = AsyncMock()
        mock_query.answer = AsyncMock()
        mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        
        await handle_add_constraint_prompt(mock_query, mock_context, event_id=1)
        
        mock_query.edit_message_text.assert_called_once()
        mock_query.answer.assert_called_once()


class TestIntegrationWithOldHandlers:
    """Tests ensuring compatibility with existing event flow handlers."""

    @pytest.mark.asyncio
    async def test_legacy_callback_still_works(self):
        """Test that old callback format still routes correctly during transition."""
        from bot.handlers.event_panel import route_event_callback
        
        # This test ensures we don't break existing handlers during migration
        pass  # Placeholder - actual implementation will depend on migration strategy


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
