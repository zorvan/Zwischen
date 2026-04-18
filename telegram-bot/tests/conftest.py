#!/usr/bin/env python3
"""Pytest configuration for tests."""
import pytest
import asyncio
from unittest.mock import AsyncMock


# =============================================================================
# Pytest Configuration
# =============================================================================

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)


def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line("markers", "asyncio: mark test as async")


# =============================================================================
# Async Fixtures
# =============================================================================

@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_session():
    """Create a database session for testing."""
    from db.connection import get_session
    from config.settings import settings
    
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        yield session


@pytest.fixture
def mock_session():
    """Create a mock database session for unit tests."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.add = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def mock_bot():
    """Create a mock Telegram bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    return bot


# =============================================================================
# Model Fixtures
# =============================================================================

@pytest.fixture
def sample_event():
    """Create a sample event for testing."""
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    
    return MagicMock(
        event_id=1,
        description="Test Event",
        event_time=datetime.now(timezone.utc),
        state="proposed",
        min_participants=2,
        telegram_group_id=-1001234567890,
    )


@pytest.fixture
def sample_enrichments():
    """Create sample enrichment data."""
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    
    return [
        MagicMock(
            enrichment_id=1,
            event_id=1,
            telegram_user_id=1001,
            enrichment_type="idea",
            content="Bring snacks",
            is_public=False,
            created_at=datetime.now(timezone.utc),
        ),
        MagicMock(
            enrichment_id=2,
            event_id=1,
            telegram_user_id=1002,
            enrichment_type="hashtag",
            content="#hiking",
            is_public=True,
            created_at=datetime.now(timezone.utc),
        ),
    ]


# =============================================================================
# Helper Fixtures
# =============================================================================

@pytest.fixture
def mock_update():
    """Create a mock Telegram update."""
    from unittest.mock import MagicMock, AsyncMock
    
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.callback_query = MagicMock()
    update.callback_query.data = "ev:1:view"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.from_user.id = 12345
    return update


@pytest.fixture
def mock_context():
    """Create a mock Telegram context."""
    from unittest.mock import MagicMock
    
    context = MagicMock()
    context.bot = MagicMock()
    context.chat_data = {}
    return context
