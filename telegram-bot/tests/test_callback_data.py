#!/usr/bin/env python3
"""Tests for bot/common/callback_data.py - Compact callback encoding.

Tests the v3.5 compact callback data format that fits within Telegram's
64-byte limit.
"""
import pytest


class TestCallbackEncoding:
    """Tests for encode_callback function."""

    def test_encode_basic(self):
        """Test basic callback encoding."""
        from bot.common.callback_data import encode_callback
        
        result = encode_callback("view", 123)
        assert result == "ev:123:view"

    def test_encode_different_actions(self):
        """Test encoding various action types."""
        from bot.common.callback_data import encode_callback
        
        assert encode_callback("join", 1) == "ev:1:join"
        assert encode_callback("confirm", 999) == "ev:999:confirm"
        assert encode_callback("det", 42) == "ev:42:det"
        assert encode_callback("enrich", 100) == "ev:100:enrich"

    def test_encode_large_event_id(self):
        """Test encoding with large event IDs."""
        from bot.common.callback_data import encode_callback
        
        # Should still be well under 64 bytes
        result = encode_callback("join", 999999999)
        assert len(result) < 64
        assert result == "ev:999999999:join"

    def test_encode_submenu_actions(self):
        """Test encoding sub-menu actions."""
        from bot.common.callback_data import encode_callback
        
        # Enrich sub-menu
        assert encode_callback("enrich_idea", 1) == "ev:1:enrich_idea"
        assert encode_callback("enrich_hashtag", 1) == "ev:1:enrich_hashtag"
        
        # Constraint sub-menu
        assert encode_callback("constraint", 1) == "ev:1:constraint"
        assert encode_callback("suggest_time", 1) == "ev:1:suggest_time"


class TestCallbackDecoding:
    """Tests for decode_callback function."""

    def test_decode_basic(self):
        """Test basic callback decoding."""
        from bot.common.callback_data import decode_callback
        
        action, event_id = decode_callback("ev:123:view")
        assert action == "view"
        assert event_id == 123

    def test_decode_different_formats(self):
        """Test decoding various formats."""
        from bot.common.callback_data import decode_callback
        
        assert decode_callback("ev:1:join") == ("join", 1)
        assert decode_callback("ev:999:confirm") == ("confirm", 999)
        assert decode_callback("ev:42:det") == ("det", 42)

    def test_decode_large_event_id(self):
        """Test decoding large event IDs."""
        from bot.common.callback_data import decode_callback
        
        action, event_id = decode_callback("ev:999999999:join")
        assert action == "join"
        assert event_id == 999999999

    def test_decode_submenu_actions(self):
        """Test decoding sub-menu actions."""
        from bot.common.callback_data import decode_callback
        
        assert decode_callback("ev:1:enrich_idea") == ("enrich_idea", 1)
        assert decode_callback("ev:1:enrich_hashtag") == ("enrich_hashtag", 1)
        assert decode_callback("ev:1:constraint_add") == ("constraint_add", 1)


class TestInvalidCallbacks:
    """Tests for invalid callback data handling."""

    def test_decode_invalid_format(self):
        """Test decoding invalid formats."""
        from bot.common.callback_data import decode_callback
        
        # Should return (None, None) for invalid formats
        assert decode_callback("invalid") == (None, None)
        assert decode_callback("menu_event_select_123") == (None, None)
        assert decode_callback("") == (None, None)

    def test_decode_wrong_prefix(self):
        """Test decoding with wrong prefix."""
        from bot.common.callback_data import decode_callback
        
        assert decode_callback("menu:123:view") == (None, None)
        assert decode_callback("event:123:join") == (None, None)

    def test_decode_missing_parts(self):
        """Test decoding with missing parts."""
        from bot.common.callback_data import decode_callback
        
        assert decode_callback("ev:123") == (None, None)
        assert decode_callback("ev:") == (None, None)
        assert decode_callback("ev::action") == (None, None)

    def test_decode_non_numeric_id(self):
        """Test decoding with non-numeric event ID."""
        from bot.common.callback_data import decode_callback
        
        assert decode_callback("ev:abc:view") == (None, None)


class TestByteLimit:
    """Tests ensuring callback data stays within 64-byte limit."""

    def test_all_standard_actions_under_limit(self):
        """Verify all standard actions fit within 64 bytes."""
        from bot.common.callback_data import encode_callback, CALLBACK_ACTIONS
        
        for action in CALLBACK_ACTIONS.values():
            # Test with large event ID
            encoded = encode_callback(action, 999999999)
            assert len(encoded) <= 64, f"Action '{action}' exceeds 64 bytes: {encoded}"

    def test_submenu_actions_under_limit(self):
        """Verify sub-menu actions fit within 64 bytes."""
        from bot.common.callback_data import encode_callback
        
        submenu_actions = [
            "enrich_idea", "enrich_hashtag", "enrich_memory",
            "constraint_add", "constraint_remove",
            "suggest_time", "negotiate_time",
        ]
        
        for action in submenu_actions:
            encoded = encode_callback(action, 999999999)
            assert len(encoded) <= 64, f"Action '{action}' exceeds 64 bytes: {encoded}"


class TestBackwardCompatibility:
    """Tests for legacy format handling."""

    def test_decode_legacy_format(self):
        """Test that legacy formats are rejected (as expected for migration)."""
        from bot.common.callback_data import decode_callback
        
        # Legacy formats should return (None, None) to trigger migration
        assert decode_callback("menu_event_select_123") == (None, None)
        assert decode_callback("event_join_123") == (None, None)
        assert decode_callback("event_confirm_123") == (None, None)


class TestConstants:
    """Tests for exported constants."""

    def test_callback_prefix_constant(self):
        """Verify CALLBACK_PREFIX constant."""
        from bot.common.callback_data import CALLBACK_PREFIX
        assert CALLBACK_PREFIX == "ev"

    def test_separator_constant(self):
        """Verify SEPARATOR constant."""
        from bot.common.callback_data import SEPARATOR
        assert SEPARATOR == ":"

    def test_callback_actions_dict(self):
        """Verify CALLBACK_ACTIONS dict exists and has expected actions."""
        from bot.common.callback_data import CALLBACK_ACTIONS
        
        assert isinstance(CALLBACK_ACTIONS, dict)
        assert "view" in CALLBACK_ACTIONS
        assert "join" in CALLBACK_ACTIONS
        assert "confirm" in CALLBACK_ACTIONS
        assert "cancel" in CALLBACK_ACTIONS
        assert "enrich" in CALLBACK_ACTIONS
        assert "constraint" in CALLBACK_ACTIONS


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
