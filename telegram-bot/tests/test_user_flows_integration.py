#!/usr/bin/env python3
"""Integration tests for full user flows with randomized values.

These tests simulate complete user interactions from command entry
to callback handling to message responses, ensuring all flow
connections are properly wired.

v3.5: Prevent obvious wiring errors like unregistered handlers.
"""
import pytest
import random
import string
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update, Message, User, Chat, InlineKeyboardMarkup
from telegram.ext import ContextTypes


# =============================================================================
# Flow Randomizers
# =============================================================================

def random_event_type() -> str:
    """Generate random event type."""
    types = ["hiking", "dinner", "meeting", "gaming", "movie", "concert", "party"]
    return random.choice(types)


def random_flexible_input() -> str:
    """Generate random flexible creation input."""
    templates = [
        "something {} this weekend",
        "{} with friends",
        "low-key {} evening",
        "outdoor {} activity",
        "{} after work",
    ]
    activities = ["fun", "chill", "active", "social", "relaxed"]
    template = random.choice(templates)
    return template.format(random.choice(activities))


def random_description() -> str:
    """Generate random event description."""
    return ''.join(random.choices(string.ascii_letters + ' ', k=random.randint(10, 50)))


# =============================================================================
# Mock Builders
# =============================================================================

def build_mock_update(text: str = None, callback_data: str = None, user_id: int = 12345) -> MagicMock:
    """Build a mock update with either message or callback query."""
    update = MagicMock(spec=Update)
    user = MagicMock(spec=User)
    user.id = user_id
    user.first_name = "Test"
    user.username = "testuser"

    chat = MagicMock(spec=Chat)
    chat.id = -1001234567890
    chat.type = "group"

    if callback_data:
        # Callback query update
        query = MagicMock()
        query.data = callback_data
        query.from_user = user
        query.message = MagicMock(spec=Message)
        query.message.chat = chat
        query.message.message_id = random.randint(1000, 9999)
        query.edit_message_text = AsyncMock()
        query.answer = AsyncMock()
        update.callback_query = query
        update.message = None
    else:
        # Message update
        message = MagicMock(spec=Message)
        message.text = text
        message.from_user = user
        message.chat = chat
        message.message_id = random.randint(1000, 9999)
        message.reply_text = AsyncMock()
        update.message = message
        update.callback_query = None

    update.effective_user = user
    update.effective_chat = chat
    return update


def build_mock_context(user_data: dict = None) -> MagicMock:
    """Build a mock context with user_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = user_data or {}
    context.bot = MagicMock()
    return context


# =============================================================================
# Flow Tests
# =============================================================================

@pytest.mark.asyncio
class TestEventsCreateFlow:
    """Test /events → Create New Event → Specific/Flexible flow."""

    async def test_events_create_new_callback(self):
        """Test clicking 'Create New Event' button shows intent selection."""
        from bot.handlers.menus import handle_menu_callback

        update = build_mock_update(callback_data="events_create_new")
        context = build_mock_context()

        await handle_menu_callback(update, context)

        # Should show intent selection with specific and flexible options
        call_args = update.callback_query.edit_message_text.call_args
        assert call_args is not None
        text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert "Let's create something together" in text

        # Check keyboard has both options
        reply_markup = call_args[1].get('reply_markup')
        assert reply_markup is not None
        keyboard = reply_markup.inline_keyboard
        assert len(keyboard) >= 2
        assert any("Plan something specific" in btn.text for row in keyboard for btn in row)
        assert any("Just exploring ideas" in btn.text for row in keyboard for btn in row)

    async def test_create_specific_callback_sets_state(self):
        """Test 'Plan something specific' sets creation_step correctly."""
        from bot.handlers.menus import handle_menu_callback

        update = build_mock_update(callback_data="create_specific")
        context = build_mock_context()

        await handle_menu_callback(update, context)

        # Should set creation_step to awaiting_event_type
        assert context.user_data.get("creation_intent") == "specific"
        assert context.user_data.get("creation_step") == "awaiting_event_type"

        # Should prompt for event type
        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert "Planning something specific" in text
        assert "What's the occasion?" in text

    async def test_create_flexible_callback_sets_state(self):
        """Test 'Just exploring ideas' sets creation_step correctly."""
        from bot.handlers.menus import handle_menu_callback

        update = build_mock_update(callback_data="create_flexible")
        context = build_mock_context()

        await handle_menu_callback(update, context)

        # Should set creation_step to awaiting_flexible_input
        assert context.user_data.get("creation_intent") == "flexible"
        assert context.user_data.get("creation_step") == "awaiting_flexible_input"

        # Should prompt for flexible input
        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert "Exploring ideas together" in text

    async def test_creation_message_handler_with_random_event_type(self):
        """Test message handler processes random event type input."""
        from bot.handlers.menus import handle_creation_message

        # Generate random event type
        event_type = random_event_type()

        update = build_mock_update(text=event_type)
        context = build_mock_context(user_data={"creation_step": "awaiting_event_type"})

        await handle_creation_message(update, context)

        # Should initialize event_flow and clear creation_step
        assert context.user_data.get("creation_step") is None
        assert "event_flow" in context.user_data
        assert context.user_data["event_flow"]["data"]["event_type"] == event_type

        # Should show scheduling options
        call_args = update.message.reply_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert event_type in text
        assert "When would you like to schedule it?" in text

    async def test_creation_message_handler_with_random_flexible_input(self):
        """Test message handler processes random flexible input."""
        from bot.handlers.menus import handle_creation_message

        # Generate random flexible input
        user_input = random_flexible_input()

        update = build_mock_update(text=user_input)
        context = build_mock_context(user_data={"creation_step": "awaiting_flexible_input"})

        await handle_creation_message(update, context)

        # Should initialize event_flow and clear creation_step
        assert context.user_data.get("creation_step") is None
        assert "event_flow" in context.user_data
        assert context.user_data["event_flow"]["data"]["flexible_input"] == user_input

        # Should show event type selection
        call_args = update.message.reply_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert user_input in text

    async def test_creation_message_handler_ignores_empty_text(self):
        """Test message handler ignores empty text and prompts again."""
        from bot.handlers.menus import handle_creation_message

        update = build_mock_update(text="   ")  # Whitespace only
        context = build_mock_context(user_data={"creation_step": "awaiting_event_type"})

        await handle_creation_message(update, context)

        # Should not clear creation_step (still waiting for valid input)
        assert context.user_data.get("creation_step") == "awaiting_event_type"

        # Should show error message
        call_args = update.message.reply_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert "❌" in text  # Error indicator

    async def test_creation_message_handler_not_in_flow(self):
        """Test message handler does nothing when not in creation flow."""
        from bot.handlers.menus import handle_creation_message

        update = build_mock_update(text=random_event_type())
        context = build_mock_context(user_data={})  # No creation_step

        await handle_creation_message(update, context)

        # Should not reply at all when not in creation flow
        update.message.reply_text.assert_not_called()


class TestCallbackPatternsRegistered:
    """Test that all callback patterns are properly registered in main.py."""

    def test_events_callback_pattern_in_main_py(self):
        """Verify events_ callback pattern is registered in main.py source."""
        import re
        from pathlib import Path

        # Read main.py source
        main_py = Path(__file__).parent.parent / "main.py"
        source = main_py.read_text()

        # Check that events_ pattern is registered
        assert '(r"^events_"' in source, "events_ pattern should be registered in main.py"
        assert "menus.handle_menu_callback" in source, "menus.handle_menu_callback should be registered"

    def test_create_callback_pattern_in_main_py(self):
        """Verify create_ callback pattern is registered in main.py source."""
        import re
        from pathlib import Path

        main_py = Path(__file__).parent.parent / "main.py"
        source = main_py.read_text()

        assert '(r"^create_"' in source, "create_ pattern should be registered in main.py"


@pytest.mark.asyncio
class TestFullRandomizedFlow:
    """Run full flows with randomized values multiple times."""

    @pytest.mark.parametrize("iteration", range(5))  # Run 5 times with different random values
    async def test_full_specific_creation_flow(self, iteration):
        """Run complete specific creation flow with random values."""
        from bot.handlers.menus import handle_menu_callback, handle_creation_message

        event_type = random_event_type()

        # Step 1: Click Create New Event
        update1 = build_mock_update(callback_data="events_create_new")
        context1 = build_mock_context()
        await handle_menu_callback(update1, context1)

        # Step 2: Click Plan something specific
        update2 = build_mock_update(callback_data="create_specific")
        context2 = build_mock_context(context1.user_data)  # Carry over user_data
        await handle_menu_callback(update2, context2)

        # Verify state is set
        assert context2.user_data.get("creation_step") == "awaiting_event_type"

        # Step 3: Send random event type
        update3 = build_mock_update(text=event_type)
        context3 = build_mock_context(context2.user_data)
        await handle_creation_message(update3, context3)

        # Verify flow initialized
        assert "event_flow" in context3.user_data
        assert context3.user_data["event_flow"]["data"]["event_type"] == event_type

    @pytest.mark.parametrize("iteration", range(5))
    async def test_full_flexible_creation_flow(self, iteration):
        """Run complete flexible creation flow with random values."""
        from bot.handlers.menus import handle_menu_callback, handle_creation_message

        user_input = random_flexible_input()

        # Step 1: Click Create New Event
        update1 = build_mock_update(callback_data="events_create_new")
        context1 = build_mock_context()
        await handle_menu_callback(update1, context1)

        # Step 2: Click Just exploring ideas
        update2 = build_mock_update(callback_data="create_flexible")
        context2 = build_mock_context(context1.user_data)
        await handle_menu_callback(update2, context2)

        # Verify state is set
        assert context2.user_data.get("creation_step") == "awaiting_flexible_input"

        # Step 3: Send random flexible input
        update3 = build_mock_update(text=user_input)
        context3 = build_mock_context(context2.user_data)
        await handle_creation_message(update3, context3)

        # Verify flow initialized
        assert "event_flow" in context3.user_data
        assert context3.user_data["event_flow"]["data"]["flexible_input"] == user_input
