#!/usr/bin/env python3
"""Tests for participant_service validation constants (v3.5).

This module tests the application-layer validation constants
that replace SQL CHECK constraints.
"""
import pytest


class TestValidationConstants:
    """Tests for validation constants exported from participant_service."""

    def test_valid_constraint_types_exists(self):
        """Verify VALID_CONSTRAINT_TYPES constant exists."""
        from bot.services.participant_service import VALID_CONSTRAINT_TYPES
        
        assert isinstance(VALID_CONSTRAINT_TYPES, set)
        assert len(VALID_CONSTRAINT_TYPES) == 3
        assert "if_joins" in VALID_CONSTRAINT_TYPES
        assert "if_attends" in VALID_CONSTRAINT_TYPES
        assert "unless_joins" in VALID_CONSTRAINT_TYPES

    def test_valid_log_actions_exists(self):
        """Verify VALID_LOG_ACTIONS constant exists."""
        from bot.services.participant_service import VALID_LOG_ACTIONS
        
        assert isinstance(VALID_LOG_ACTIONS, set)
        # Check v3.5 new actions
        assert "enrich_idea" in VALID_LOG_ACTIONS
        assert "enrich_hashtag" in VALID_LOG_ACTIONS
        assert "enrich_memory" in VALID_LOG_ACTIONS
        assert "relinquish" in VALID_LOG_ACTIONS
        # Check legacy actions
        assert "organize_event" in VALID_LOG_ACTIONS
        assert "join" in VALID_LOG_ACTIONS
        assert "confirm" in VALID_LOG_ACTIONS
        assert "cancel" in VALID_LOG_ACTIONS


class TestValidateConstraintType:
    """Tests for validate_constraint_type function."""

    def test_function_exists(self):
        """Verify validate_constraint_type function exists."""
        from bot.services.participant_service import validate_constraint_type
        assert callable(validate_constraint_type)

    def test_valid_types_normalized(self):
        """Test that valid types are normalized (lowercase, stripped)."""
        from bot.services.participant_service import validate_constraint_type
        
        # Exact matches
        assert validate_constraint_type("if_joins") == "if_joins"
        assert validate_constraint_type("if_attends") == "if_attends"
        assert validate_constraint_type("unless_joins") == "unless_joins"
        
        # Normalization
        assert validate_constraint_type("IF_JOINS") == "if_joins"
        assert validate_constraint_type("  if_attends  ") == "if_attends"
        assert validate_constraint_type("Unless_Joins") == "unless_joins"

    def test_invalid_types_raise_error(self):
        """Test that invalid types raise ValueError."""
        from bot.services.participant_service import validate_constraint_type
        
        with pytest.raises(ValueError):
            validate_constraint_type("invalid_type")
        
        with pytest.raises(ValueError):
            validate_constraint_type("available_saturday")  # Old pattern no longer valid
        
        with pytest.raises(ValueError):
            validate_constraint_type("")
        
        with pytest.raises(ValueError):
            validate_constraint_type("random")

    def test_error_message_includes_valid_types(self):
        """Test that error message lists valid types."""
        from bot.services.participant_service import validate_constraint_type
        
        with pytest.raises(ValueError) as exc_info:
            validate_constraint_type("invalid")
        
        error_msg = str(exc_info.value)
        assert "if_joins" in error_msg
        assert "if_attends" in error_msg
        assert "unless_joins" in error_msg


class TestValidateLogAction:
    """Tests for validate_log_action function."""

    def test_function_exists(self):
        """Verify validate_log_action function exists."""
        from bot.services.participant_service import validate_log_action
        assert callable(validate_log_action)

    def test_valid_actions_normalized(self):
        """Test that valid actions are normalized."""
        from bot.services.participant_service import validate_log_action
        
        assert validate_log_action("join") == "join"
        assert validate_log_action("JOIN") == "join"
        assert validate_log_action("  confirm  ") == "confirm"
        assert validate_log_action("Enrich_Hashtag") == "enrich_hashtag"

    def test_v35_new_actions(self):
        """Test that v3.5 new actions are valid."""
        from bot.services.participant_service import validate_log_action
        
        assert validate_log_action("relinquish") == "relinquish"
        assert validate_log_action("enrich_idea") == "enrich_idea"
        assert validate_log_action("enrich_memory") == "enrich_memory"
        assert validate_log_action("lock") == "lock"
        assert validate_log_action("complete") == "complete"
        assert validate_log_action("collapse") == "collapse"

    def test_invalid_actions_raise_error(self):
        """Test that invalid actions raise ValueError."""
        from bot.services.participant_service import validate_log_action
        
        with pytest.raises(ValueError):
            validate_log_action("invalid_action")
        
        with pytest.raises(ValueError):
            validate_log_action("")


class TestIntegrationWithService:
    """Integration tests with ParticipantService class."""

    def test_service_can_access_constants(self):
        """Verify ParticipantService can access validation constants."""
        from bot.services.participant_service import ParticipantService, VALID_CONSTRAINT_TYPES, VALID_LOG_ACTIONS
        
        # Constants should be accessible
        assert ParticipantService.VALID_CONSTRAINT_TYPES is VALID_CONSTRAINT_TYPES
        assert ParticipantService.VALID_LOG_ACTIONS is VALID_LOG_ACTIONS


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
