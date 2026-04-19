#!/usr/bin/env python3
"""End-to-end integration tests for creation flow using real handlers.

These tests actually run the handler functions with realistic update objects
to catch wiring issues like:
- Handler not registered in main.py
- Handler returning early due to wrong conditions
- User_data not persisting between calls
- Missing filters or wrong handler order

v3.5: Real integration testing to prevent flow breakage.
"""
import pytest
import random
import string
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from typing import Dict, Any

# We need to import the actual application to test real handler registration
# This test file should catch issues like handlers not being wired up


class FakeTelegramUser:
    """Fake user object like telegram.User."""
    def __init__(self, user_id=12345, username="testuser"):
        self.id = user_id
        self.first_name = "Test"
        self.last_name = "User"
        self.username = username
        self.is_bot = False
        self.language_code = "en"


class FakeChat:
    """Fake chat object like telegram.Chat."""
    def __init__(self, chat_id=-1001234567890):
        self.id = chat_id
        self.type = "group"
        self.title = "Test Group"


class FakeMessage:
    """Fake message object like telegram.Message."""
    def __init__(self, text=None, user_id=12345, chat_id=-1001234567890, message_id=1000):
        self.text = text
        self.from_user = FakeTelegramUser(user_id)
        self.chat = FakeChat(chat_id)
        self.message_id = message_id
        self.date = datetime.now(timezone.utc)
        self.reply_text = AsyncMock()
        self.reply_markup = None


class FakeCallbackQuery:
    """Fake callback query like telegram.CallbackQuery."""
    def __init__(self, data, user_id=12345, chat_id=-1001234567890, message_id=1000):
        self.data = data
        self.from_user = FakeTelegramUser(user_id)
        self.message = FakeMessage(None, user_id, chat_id, message_id)
        self.chat_instance = "test_instance"
        self.id = "123456789"
        self.edit_message_text = AsyncMock()
        self.answer = AsyncMock()


class FakeUpdate:
    """Fake update like telegram.Update."""
    def __init__(self, message=None, callback_query=None, update_id=1):
        self.message = message
        self.callback_query = callback_query
        self.update_id = update_id
        self.effective_user = (message.from_user if message 
                                else callback_query.from_user if callback_query 
                                else None)
        self.effective_chat = (message.chat if message 
                              else callback_query.message.chat if callback_query 
                              else None)


class FakeContext:
    """Fake context like telegram.ext.Context."""
    def __init__(self, user_data: Dict[str, Any] = None):
        self.user_data = user_data or {}
        self.bot = MagicMock()
        self.chat_data = {}
        self.bot_data = {}


# =============================================================================
# Random Value Generators
# =============================================================================

def random_event_type() -> str:
    """Generate random event type."""
    types = ["hiking", "dinner", "meeting", "gaming", "movie", "concert", 
             "party", "boardgame", "tabletop_rpg", "brunch", "workshop"]
    return random.choice(types)


def random_flexible_input() -> str:
    """Generate random flexible creation input."""
    templates = [
        "something {} this weekend",
        "{} with friends on saturday",
        "low-key {} evening after work",
        "outdoor {} activity in the park",
        "{} get-together next week",
        "casual {} hangout",
    ]
    activities = ["fun", "chill", "active", "social", "relaxed", "creative", "energetic"]
    return random.choice(templates).format(random.choice(activities))


def random_description() -> str:
    """Generate random event description."""
    words = ["awesome", "fun", "casual", "exciting", "relaxed", "engaging", "cool"]
    return f"A {random.choice(words)} event about " + ''.join(random.choices(string.ascii_lowercase, k=10))


# =============================================================================
# E2E Flow Tests
# =============================================================================

@pytest.mark.asyncio
class TestCreationFlowEndToEnd:
    """Test the complete creation flow from /events to event creation."""

    async def test_full_specific_flow_with_real_handlers(self):
        """Run complete specific flow using actual handler functions.
        
        This test verifies:
        1. Callback handler updates user_data correctly
        2. Message handler reads user_data and processes input
        3. Flow transitions work end-to-end
        """
        from bot.handlers.menus import handle_menu_callback, handle_creation_message

        user_id = random.randint(100000, 999999)
        event_type = random_event_type()
        
        # Create a shared context to simulate state persistence
        context = FakeContext()

        # Step 1: User clicks "Create New Event" button
        callback1 = FakeCallbackQuery("events_create_new", user_id=user_id)
        update1 = FakeUpdate(callback_query=callback1)
        
        await handle_menu_callback(update1, context)
        
        # Verify callback was answered and message edited
        assert callback1.answer.called, "Callback should be answered"
        assert callback1.edit_message_text.called, "Message should be edited with intent selection"
        
        # Get text from positional args (index 0) or keyword args
        call_args = callback1.edit_message_text.call_args
        call_text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert "Let's create something together" in call_text, f"Should show intent selection, got: {call_text}"

        # Step 2: User clicks "Plan something specific"
        callback2 = FakeCallbackQuery("create_specific", user_id=user_id)
        update2 = FakeUpdate(callback_query=callback2)
        
        await handle_menu_callback(update2, context)
        
        # CRITICAL: Verify user_data was updated
        assert context.user_data.get("creation_intent") == "specific", \
            f"creation_intent should be 'specific', got: {context.user_data}"
        assert context.user_data.get("creation_step") == "awaiting_event_type", \
            f"creation_step should be 'awaiting_event_type', got: {context.user_data}"

        call_args = callback2.edit_message_text.call_args
        call_text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert "Planning something specific" in call_text, f"Should show specific planning prompt, got: {call_text}"

        # Step 3: User sends event type as text message
        message3 = FakeMessage(text=event_type, user_id=user_id)
        update3 = FakeUpdate(message=message3)
        
        # This is where the bug was - handler wasn't being called
        await handle_creation_message(update3, context)
        
        # CRITICAL: Verify message was processed and event_flow created
        assert "event_flow" in context.user_data, \
            f"event_flow should be created in user_data, got: {context.user_data.keys()}"
        assert context.user_data["creation_step"] is None, \
            "creation_step should be cleared after processing"
        
        event_flow = context.user_data["event_flow"]
        assert event_flow["data"]["event_type"] == event_type, \
            f"event_type should be '{event_type}', got: {event_flow}"

        # Verify bot replied with scheduling options
        assert message3.reply_text.called, "Bot should reply with scheduling options"
        call_args = message3.reply_text.call_args
        reply_text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert event_type in reply_text, f"Reply should contain event type '{event_type}', got: {reply_text}"
        assert "When would you like to schedule it?" in reply_text, f"Should ask for scheduling, got: {reply_text}"

    async def test_full_flexible_flow_with_real_handlers(self):
        """Run complete flexible flow using actual handler functions."""
        from bot.handlers.menus import handle_menu_callback, handle_creation_message

        user_id = random.randint(100000, 999999)
        user_input = random_flexible_input()
        
        context = FakeContext()

        # Step 1: Click "Create New Event"
        callback1 = FakeCallbackQuery("events_create_new", user_id=user_id)
        update1 = FakeUpdate(callback_query=callback1)
        await handle_menu_callback(update1, context)

        # Step 2: Click "Just exploring ideas"
        callback2 = FakeCallbackQuery("create_flexible", user_id=user_id)
        update2 = FakeUpdate(callback_query=callback2)
        await handle_menu_callback(update2, context)

        # Verify state
        assert context.user_data.get("creation_intent") == "flexible"
        assert context.user_data.get("creation_step") == "awaiting_flexible_input"

        # Step 3: Send flexible input
        message3 = FakeMessage(text=user_input, user_id=user_id)
        update3 = FakeUpdate(message=message3)
        await handle_creation_message(update3, context)

        # Verify flow created
        assert "event_flow" in context.user_data
        assert context.user_data["creation_step"] is None
        assert context.user_data["event_flow"]["data"]["flexible_input"] == user_input

        # Verify reply asks for event type
        assert message3.reply_text.called
        call_args = message3.reply_text.call_args
        reply_text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert user_input in reply_text, f"Reply should contain user input '{user_input}', got: {reply_text}"
        assert "What type of event would best fit?" in reply_text, f"Should ask for event type, got: {reply_text}"

    async def test_message_handler_returns_early_without_creation_step(self):
        """Test that message handler returns early when not in creation flow."""
        from bot.handlers.menus import handle_creation_message

        # Context with NO creation_step set
        context = FakeContext(user_data={"some_other_key": "value"})
        message = FakeMessage(text=random_event_type())
        update = FakeUpdate(message=message)

        await handle_creation_message(update, context)

        # Should not reply when not in creation flow
        assert not message.reply_text.called, "Should not reply when creation_step is not set"

    async def test_message_handler_returns_early_with_empty_text(self):
        """Test that message handler handles empty/whitespace text."""
        from bot.handlers.menus import handle_creation_message

        context = FakeContext(user_data={"creation_step": "awaiting_event_type"})
        message = FakeMessage(text="   ")  # Whitespace only
        update = FakeUpdate(message=message)

        await handle_creation_message(update, context)

        # Should reply with error
        assert message.reply_text.called, "Should reply with error for empty text"
        call_args = message.reply_text.call_args
        reply_text = call_args[0][0] if call_args[0] else call_args[1].get('text', '')
        assert "❌" in reply_text, f"Should show error indicator, got: {reply_text}"
        
        # creation_step should NOT be cleared
        assert context.user_data["creation_step"] == "awaiting_event_type"


class TestHandlerRegistration:
    """Verify handlers are actually registered in the application."""

    def test_main_py_imports_menus_handler(self):
        """Test that main.py imports and uses menus.handle_creation_message."""
        from pathlib import Path
        import ast

        main_py_path = Path(__file__).parent.parent / "main.py"
        source = main_py_path.read_text()

        # Check imports
        assert "from bot.handlers import" in source, "Should import from bot.handlers"
        assert "menus" in source, "Should import menus module"

        # Check that handle_creation_message is registered
        assert "handle_creation_message" in source, \
            "handle_creation_message should be registered in main.py"
        
        # Check that it's used with MessageHandler
        assert "MessageHandler" in source, "Should use MessageHandler"

    def test_callback_patterns_registered(self):
        """Verify callback patterns are in main.py callback_handlers list."""
        from pathlib import Path
        import re

        main_py_path = Path(__file__).parent.parent / "main.py"
        source = main_py_path.read_text()

        # Extract callback_handlers list
        pattern = r'callback_handlers\s*=\s*\[(.*?)\]'
        match = re.search(pattern, source, re.DOTALL)
        assert match, "Should find callback_handlers list in main.py"

        handlers_text = match.group(1)

        # Check for our patterns
        assert 'r"^events_"' in handlers_text, "events_ pattern should be in callback_handlers"
        assert 'r"^create_"' in handlers_text, "create_ pattern should be in callback_handlers"
        assert "menus.handle_menu_callback" in handlers_text, "menus.handle_menu_callback should be registered"


@pytest.mark.asyncio  
class TestRandomizedFlowsMultipleRuns:
    """Run flows multiple times with different random values."""

    @pytest.mark.parametrize("run", range(3))
    async def test_specific_flow_randomized(self, run):
        """Run specific flow 3 times with random values each time."""
        from bot.handlers.menus import handle_menu_callback, handle_creation_message

        user_id = random.randint(100000, 999999)
        event_type = random_event_type()
        context = FakeContext()

        # Step 1-2: Callbacks
        await handle_menu_callback(FakeUpdate(callback_query=FakeCallbackQuery("events_create_new", user_id)), context)
        await handle_menu_callback(FakeUpdate(callback_query=FakeCallbackQuery("create_specific", user_id)), context)

        # Verify state
        assert context.user_data.get("creation_step") == "awaiting_event_type"

        # Step 3: Message
        message = FakeMessage(text=event_type, user_id=user_id)
        await handle_creation_message(FakeUpdate(message=message), context)

        # Verify result
        assert "event_flow" in context.user_data
        assert context.user_data["event_flow"]["data"]["event_type"] == event_type
        assert message.reply_text.called

    @pytest.mark.parametrize("run", range(3))
    async def test_flexible_flow_randomized(self, run):
        """Run flexible flow 3 times with random values each time."""
        from bot.handlers.menus import handle_menu_callback, handle_creation_message

        user_id = random.randint(100000, 999999)
        user_input = random_flexible_input()
        context = FakeContext()

        # Step 1-2: Callbacks
        await handle_menu_callback(FakeUpdate(callback_query=FakeCallbackQuery("events_create_new", user_id)), context)
        await handle_menu_callback(FakeUpdate(callback_query=FakeCallbackQuery("create_flexible", user_id)), context)

        # Verify state
        assert context.user_data.get("creation_step") == "awaiting_flexible_input"

        # Step 3: Message
        message = FakeMessage(text=user_input, user_id=user_id)
        await handle_creation_message(FakeUpdate(message=message), context)

        # Verify result
        assert "event_flow" in context.user_data
        assert context.user_data["event_flow"]["data"]["flexible_input"] == user_input
        assert message.reply_text.called
