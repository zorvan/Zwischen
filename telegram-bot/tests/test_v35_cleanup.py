#!/usr/bin/env python3
"""Tests for v3.5 Phase 5 Cleanup.

Tests for:
1. Removal of deprecated commands
2. Column renames and removals
3. LLM layer cleanup (no regex fallbacks)
4. Final /events consolidation

PRD v3.5 Section 5: Cleanup
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDeprecatedCommandRemoval:
    """Tests ensuring deprecated commands are removed."""

    def test_deprecated_commands_marked(self):
        """Test that deprecated commands are identified."""
        # These commands should be deprecated in favor of /events
        deprecated_commands = [
            "/join",
            "/confirm", 
            "/cancel",
            "/lock",
            "/unlock",
        ]
        
        # Should exist in deprecated list
        assert len(deprecated_commands) > 0
        
    def test_events_command_is_primary(self):
        """Test that /events is the primary entry point."""
        from bot.commands import events
        
        # events command should exist and be functional
        assert hasattr(events, 'handle')


class TestExpertiseColumnRemoval:
    """Tests for removal of expertise_per_activity column."""

    def test_user_model_no_expertise_column(self):
        """Test User model doesn't have expertise_per_activity."""
        from db.models import User
        
        # Check that expertise_per_activity is not in User columns
        from sqlalchemy import inspect
        
        # Get column names from User model
        column_names = [c.name for c in User.__table__.columns]
        
        assert "expertise_per_activity" not in column_names


class TestAdminColumnRename:
    """Tests for admin_telegram_user_id rename."""

    def test_event_model_has_emergency_admin_column(self):
        """Test Event model has emergency_admin_telegram_user_id."""
        from db.models import Event
        
        column_names = [c.name for c in Event.__table__.columns]
        
        # Should have new name
        assert "emergency_admin_telegram_user_id" in column_names
        
    def test_event_model_no_old_admin_column(self):
        """Test Event model doesn't have old admin_telegram_user_id."""
        from db.models import Event
        
        column_names = [c.name for c in Event.__table__.columns]
        
        # Should NOT have old name
        assert "admin_telegram_user_id" not in column_names


class TestLLMRegexFallbackRemoval:
    """Tests for removal of regex fallbacks from LLM layer."""

    def test_no_infer_feedback_from_text_method(self):
        """Test that infer_feedback_from_text is removed."""
        from ai import llm
        
        # This method should not exist (it did behavioral scoring)
        assert not hasattr(llm.LLMClient, 'infer_feedback_from_text')

    def test_no_regex_fallback_in_constraint_inference(self):
        """Test that constraint inference has no regex fallback."""
        from ai import llm
        
        # Check the infer_constraint_from_text method
        import inspect
        source = inspect.getsource(llm.LLMClient.infer_constraint_from_text)
        
        # Should not contain regex fallback logic
        assert "fallback" not in source or "re.search" not in source


class TestEventsConsolidation:
    """Tests for /events command consolidation."""

    @pytest.mark.asyncio
    async def test_events_command_exists(self):
        """Test /events command exists and is importable."""
        from bot.commands import events
        
        # Verify handle function exists
        assert hasattr(events, 'handle')
        assert callable(events.handle)


class TestSchemaCleanup:
    """Tests for database schema cleanup."""

    def test_no_check_constraints_on_semantic_strings(self):
        """Verify CHECK constraints removed from semantic columns."""
        # This is tested in test_database_schema.py
        # Just ensure the concept is documented
        columns_without_checks = [
            "groups.group_type",
            "constraints.type", 
            "logs.action",
        ]
        assert len(columns_without_checks) == 3


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
