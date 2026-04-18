#!/usr/bin/env python3
"""Tests for ai/actions.py - Canonical Action Registry.

This module tests the v3.5 canonical action registry and handler mappings.
"""
import pytest


class TestActionRegistry:
    """Tests for the ACTIONS registry."""

    def test_actions_dict_exists(self):
        """Verify ACTIONS dict is defined and not empty."""
        from ai.actions import ACTIONS
        
        assert isinstance(ACTIONS, dict)
        assert len(ACTIONS) > 0
        
        # Verify required actions exist
        required_actions = [
            "view_events", "view_event_panel", "join_event",
            "relinquish_event", "commit_event", "lock_event",
            "create_event", "add_constraint", "suggest_time", "opinion"
        ]
        for action in required_actions:
            assert action in ACTIONS, f"Required action '{action}' missing"

    def test_action_structure(self):
        """Verify each action has required fields."""
        from ai.actions import ACTIONS
        
        for name, action_def in ACTIONS.items():
            assert "description" in action_def, f"{name} missing description"
            assert "required_params" in action_def, f"{name} missing required_params"
            assert "optional_params" in action_def, f"{name} missing optional_params"
            
            assert isinstance(action_def["description"], str)
            assert isinstance(action_def["required_params"], list)
            assert isinstance(action_def["optional_params"], list)
            
            # Description should be non-empty
            assert len(action_def["description"]) > 0

    def test_view_events_action(self):
        """Test view_events action definition."""
        from ai.actions import ACTIONS
        
        action = ACTIONS["view_events"]
        assert action["required_params"] == []
        assert "group_id" in action["optional_params"]
        assert "user" in action["description"].lower() or "see" in action["description"].lower()

    def test_join_event_action(self):
        """Test join_event action definition."""
        from ai.actions import ACTIONS
        
        action = ACTIONS["join_event"]
        assert "event_id" in action["required_params"]
        assert action["optional_params"] == []

    def test_create_event_action(self):
        """Test create_event action definition."""
        from ai.actions import ACTIONS
        
        action = ACTIONS["create_event"]
        assert action["required_params"] == []
        assert "description" in action["optional_params"]
        assert "event_type" in action["optional_params"]
        assert "scheduled_time" in action["optional_params"]

    def test_commit_event_action(self):
        """Test commit_event action definition."""
        from ai.actions import ACTIONS
        
        action = ACTIONS["commit_event"]
        assert "event_id" in action["required_params"]
        assert "commit" in action["description"].lower() or "confirm" in action["description"].lower()

    def test_relinquish_event_action(self):
        """Test relinquish_event action definition."""
        from ai.actions import ACTIONS
        
        action = ACTIONS["relinquish_event"]
        assert "event_id" in action["required_params"]
        assert "relinquish" in action["description"].lower() or "leave" in action["description"].lower()

    def test_add_constraint_action(self):
        """Test add_constraint action definition."""
        from ai.actions import ACTIONS
        
        action = ACTIONS["add_constraint"]
        assert "event_id" in action["required_params"]
        assert "constraint_type" in action["required_params"]
        assert "target_username" in action["required_params"]

    def test_opinion_action(self):
        """Test opinion action (fallback) definition."""
        from ai.actions import ACTIONS
        
        action = ACTIONS["opinion"]
        assert action["required_params"] == []
        assert "assistant_response" in action["optional_params"]


class TestActionHandlers:
    """Tests for the ACTION_HANDLERS mapping."""

    def test_handlers_dict_exists(self):
        """Verify ACTION_HANDLERS dict is defined."""
        from ai.actions import ACTION_HANDLERS
        
        assert isinstance(ACTION_HANDLERS, dict)
        assert len(ACTION_HANDLERS) > 0

    def test_all_actions_have_handlers(self):
        """Verify every action in ACTIONS has a handler."""
        from ai.actions import ACTIONS, ACTION_HANDLERS
        
        for action_name in ACTIONS.keys():
            assert action_name in ACTION_HANDLERS, f"Action '{action_name}' has no handler"

    def test_handler_paths_are_strings(self):
        """Verify handler paths are valid module paths."""
        from ai.actions import ACTION_HANDLERS
        
        for action, handler_path in ACTION_HANDLERS.items():
            assert isinstance(handler_path, str), f"{action} handler must be a string"
            assert "." in handler_path, f"{action} handler should be a module path"

    def test_view_events_handler(self):
        """Test view_events handler mapping."""
        from ai.actions import ACTION_HANDLERS
        
        assert "bot.commands.events" in ACTION_HANDLERS["view_events"]

    def test_join_event_handler(self):
        """Test join_event handler mapping."""
        from ai.actions import ACTION_HANDLERS
        
        assert "bot.handlers.event_flow" in ACTION_HANDLERS["join_event"]

    def test_create_event_handler(self):
        """Test create_event handler mapping."""
        from ai.actions import ACTION_HANDLERS
        
        assert "bot.commands.events" in ACTION_HANDLERS["create_event"]


class TestValidationConstants:
    """Tests for validation constants exported from actions module."""

    def test_valid_constraint_types_exist(self):
        """Verify VALID_CONSTRAINT_TYPES is defined."""
        from ai.actions import VALID_CONSTRAINT_TYPES
        
        assert isinstance(VALID_CONSTRAINT_TYPES, set)
        assert "if_joins" in VALID_CONSTRAINT_TYPES
        assert "if_attends" in VALID_CONSTRAINT_TYPES
        assert "unless_joins" in VALID_CONSTRAINT_TYPES

    def test_valid_log_actions_exist(self):
        """Verify VALID_LOG_ACTIONS is defined."""
        from ai.actions import VALID_LOG_ACTIONS
        
        assert isinstance(VALID_LOG_ACTIONS, set)
        # Check for v3.5 actions
        assert "enrich_idea" in VALID_LOG_ACTIONS
        assert "enrich_hashtag" in VALID_LOG_ACTIONS
        assert "enrich_memory" in VALID_LOG_ACTIONS
        assert "relinquish" in VALID_LOG_ACTIONS


class TestHelperFunctions:
    """Tests for helper functions in actions module."""

    def test_validate_constraint_type_exists(self):
        """Verify validate_constraint_type function exists."""
        from ai.actions import validate_constraint_type
        assert callable(validate_constraint_type)

    def test_validate_constraint_type_valid(self):
        """Test validate_constraint_type with valid inputs."""
        from ai.actions import validate_constraint_type
        
        assert validate_constraint_type("if_joins") == "if_joins"
        assert validate_constraint_type("IF_JOINS") == "if_joins"  # normalized
        assert validate_constraint_type("  if_attends  ") == "if_attends"  # stripped

    def test_validate_constraint_type_invalid(self):
        """Test validate_constraint_type with invalid inputs."""
        from ai.actions import validate_constraint_type, ValidationError
        
        with pytest.raises((ValueError, ValidationError)):
            validate_constraint_type("invalid_type")
        
        with pytest.raises((ValueError, ValidationError)):
            validate_constraint_type("")

    def test_validate_log_action_exists(self):
        """Verify validate_log_action function exists."""
        from ai.actions import validate_log_action
        assert callable(validate_log_action)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
