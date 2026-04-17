"""
Unit tests for markdown parsing and entity escaping.
Catches parse_mode errors before runtime.
"""

from __future__ import annotations

import pytest

from bot.commands.flow import _escape_md


class TestMarkdownEscaping:
    """Test that special characters are properly escaped for Markdown."""

    @pytest.mark.asyncio
    async def test_escape_bold_asterisks(self) -> None:
        """Test that * characters are escaped."""
        text = "Hello *world*"
        escaped = _escape_md(text)
        assert escaped == "Hello \\*world\\*"

    @pytest.mark.asyncio
    async def test_escape_underscores(self) -> None:
        """Test that _ characters are escaped."""
        text = "Hello_world"
        escaped = _escape_md(text)
        assert escaped == "Hello\\_world"

    @pytest.mark.asyncio
    async def test_escape_brackets(self) -> None:
        """Test that [ and ] characters are escaped."""
        text = "Hello [world]"
        escaped = _escape_md(text)
        assert escaped == "Hello \\[world\\]"

    @pytest.mark.asyncio
    async def test_escape_combined(self) -> None:
        """Test multiple special characters are all escaped."""
        text = "Test _bold_ and *italic* and [link]"
        escaped = _escape_md(text)
        assert escaped == "Test \\_bold\\_ and \\*italic\\* and \\[link\\]"

    @pytest.mark.asyncio
    async def test_special_characters_in_event_type(self) -> None:
        """Test that event_type with special chars doesn't break markdown."""
        event_type = "Game_Night"
        description = "Football *match* at the park"

        escaped_type = _escape_md(event_type)
        escaped_desc = _escape_md(description)

        # These should not cause parse_mode errors
        assert escaped_type == "Game\\_Night"
        assert escaped_desc == "Football \\*match\\* at the park"

    @pytest.mark.asyncio
    async def test_special_characters_in_user_name(self) -> None:
        """Test that user names with special chars don't break messages."""
        # User might have name like "John*Doe" or "Test_User"
        display_name = "John*Doe"
        escaped = _escape_md(display_name)

        # Message should be parseable
        message = f"👋 *Welcome, {escaped}!*\n\nTest message"
        assert "\\*" in message
        assert "\\_" not in message  # Only * should be escaped in this case

    @pytest.mark.asyncio
    async def test_empty_string(self) -> None:
        """Test that empty strings are handled."""
        text = ""
        escaped = _escape_md(text)
        assert escaped == ""

    @pytest.mark.asyncio
    async def test_no_special_chars(self) -> None:
        """Test that normal text passes through unchanged."""
        text = "Hello world, this is a test"
        escaped = _escape_md(text)
        assert escaped == text
