#!/usr/bin/env python3
"""Tests for EventLiveCardService."""

import pytest
from unittest.mock import MagicMock
from datetime import datetime

from bot.services.event_live_card_service import EventLiveCardService


def test_categorize_sentiment():
    """Test sentiment categorization of emojis."""
    bot = MagicMock()
    session = MagicMock()
    service = EventLiveCardService(bot, session)

    assert service._categorize_sentiment("🎉") == "enthusiasm"
    assert service._categorize_sentiment("✨") == "enthusiasm"
    assert service._categorize_sentiment("❤️") == "enthusiasm"
    assert service._categorize_sentiment("🔥") == "interest"
    assert service._categorize_sentiment("👀") == "interest"
    assert service._categorize_sentiment("👍") == "acknowledgment"
    assert service._categorize_sentiment("⏳") == "timing_concern"
    assert service._categorize_sentiment("⏰") == "timing_concern"
    assert service._categorize_sentiment("❌") == "other"
