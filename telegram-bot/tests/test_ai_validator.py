#!/usr/bin/env python3
"""Tests for ai/validator.py - LLM Output Validator.

This module tests the v3.5 output validation system for LLM action inference.
"""
import pytest
from dataclasses import dataclass


class TestValidationResult:
    """Tests for the ValidationResult dataclass."""

    def test_validation_result_exists(self):
        """Verify ValidationResult class exists."""
        from ai.validator import ValidationResult
        # Dataclass fields are in __annotations__, not class attributes
        annotations = ValidationResult.__annotations__
        assert 'valid' in annotations
        assert 'reason' in annotations
        assert 'recoverable' in annotations
        assert 'missing_params' in annotations
        assert 'recovery_prompt' in annotations

    def test_validation_result_defaults(self):
        """Test ValidationResult default values."""
        from ai.validator import ValidationResult
        
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.reason is None
        assert result.recoverable is False
        assert result.missing_params is None
        assert result.recovery_prompt is None

    def test_validation_result_with_missing_params(self):
        """Test ValidationResult with missing parameters."""
        from ai.validator import ValidationResult
        
        result = ValidationResult(
            valid=False,
            reason="Missing required params",
            recoverable=True,
            missing_params=["event_id"],
            recovery_prompt="Which event are you referring to?"
        )
        assert result.valid is False
        assert result.recoverable is True
        assert result.missing_params == ["event_id"]


class TestValidateActionResult:
    """Tests for validate_action_result function."""

    @pytest.fixture
    def sample_registry(self):
        """Provide a sample action registry for testing."""
        return {
            "view_events": {
                "description": "View events list",
                "required_params": [],
                "optional_params": ["group_id"],
            },
            "join_event": {
                "description": "Join an event",
                "required_params": ["event_id"],
                "optional_params": [],
            },
            "create_event": {
                "description": "Create new event",
                "required_params": [],
                "optional_params": ["description", "event_type"],
            },
        }

    def test_validate_valid_result_no_params(self, sample_registry):
        """Test validation of valid result with no required params."""
        from ai.validator import validate_action_result, ValidationResult
        
        result = {"action": "view_events", "params": {}, "confidence": 0.9}
        validation = validate_action_result(result, sample_registry)
        
        assert isinstance(validation, ValidationResult)
        assert validation.valid is True

    def test_validate_valid_result_with_params(self, sample_registry):
        """Test validation of valid result with required params."""
        from ai.validator import validate_action_result, ValidationResult
        
        result = {
            "action": "join_event",
            "params": {"event_id": 123},
            "confidence": 0.95
        }
        validation = validate_action_result(result, sample_registry)
        
        assert validation.valid is True

    def test_validate_invalid_not_dict(self, sample_registry):
        """Test validation fails when result is not a dict."""
        from ai.validator import validate_action_result, ValidationResult
        
        validation = validate_action_result("not a dict", sample_registry)
        
        assert validation.valid is False
        assert "not a dict" in validation.reason.lower() or "dict" in validation.reason.lower()

    def test_validate_unknown_action(self, sample_registry):
        """Test validation fails for unknown action."""
        from ai.validator import validate_action_result, ValidationResult
        
        result = {"action": "unknown_action", "params": {}}
        validation = validate_action_result(result, sample_registry)
        
        assert validation.valid is False
        assert "unknown" in validation.reason.lower()

    def test_validate_missing_action_key(self, sample_registry):
        """Test validation fails when action key is missing."""
        from ai.validator import validate_action_result, ValidationResult
        
        result = {"params": {}, "confidence": 0.5}
        validation = validate_action_result(result, sample_registry)
        
        assert validation.valid is False

    def test_validate_missing_required_param(self, sample_registry):
        """Test validation fails when required param is missing."""
        from ai.validator import validate_action_result, ValidationResult
        
        result = {
            "action": "join_event",
            "params": {},  # missing event_id
            "confidence": 0.8
        }
        validation = validate_action_result(result, sample_registry)
        
        assert validation.valid is False
        assert validation.recoverable is True
        assert "event_id" in validation.missing_params
        assert validation.recovery_prompt is not None

    def test_validate_null_required_param(self, sample_registry):
        """Test validation fails when required param is null."""
        from ai.validator import validate_action_result, ValidationResult
        
        result = {
            "action": "join_event",
            "params": {"event_id": None},
            "confidence": 0.8
        }
        validation = validate_action_result(result, sample_registry)
        
        assert validation.valid is False
        assert validation.recoverable is True
        assert "event_id" in validation.missing_params

    def test_validate_empty_string_param(self, sample_registry):
        """Test validation fails when required param is empty string."""
        from ai.validator import validate_action_result, ValidationResult
        
        result = {
            "action": "join_event",
            "params": {"event_id": ""},
            "confidence": 0.8
        }
        validation = validate_action_result(result, sample_registry)
        
        assert validation.valid is False
        assert "event_id" in validation.missing_params

    def test_validate_event_id_recovery_prompt(self, sample_registry):
        """Test specific recovery prompt for missing event_id."""
        from ai.validator import validate_action_result
        
        result = {
            "action": "join_event",
            "params": {},
            "confidence": 0.8
        }
        validation = validate_action_result(result, sample_registry)
        
        assert validation.recoverable is True
        assert "event" in validation.recovery_prompt.lower()

    def test_validate_other_missing_params_prompt(self, sample_registry):
        """Test generic recovery prompt for other missing params."""
        # Create registry with different required param
        registry = {
            "test_action": {
                "description": "Test",
                "required_params": ["some_param"],
                "optional_params": [],
            }
        }
        from ai.validator import validate_action_result
        
        result = {
            "action": "test_action",
            "params": {},
            "confidence": 0.8
        }
        validation = validate_action_result(result, registry)
        
        assert validation.recoverable is True
        assert "info" in validation.recovery_prompt.lower() or "more" in validation.recovery_prompt.lower()

    def test_validate_none_params(self, sample_registry):
        """Test validation when params is None."""
        from ai.validator import validate_action_result, ValidationResult
        
        result = {
            "action": "view_events",
            "params": None,
            "confidence": 0.9
        }
        validation = validate_action_result(result, sample_registry)
        
        # Should treat None as empty dict for actions with no required params
        assert validation.valid is True


class TestIntegrationWithActionsRegistry:
    """Integration tests with the actual actions registry."""

    def test_validate_against_real_registry(self):
        """Test validation against the actual ACTIONS registry."""
        from ai.validator import validate_action_result
        from ai.actions import ACTIONS
        
        # Valid create_event result
        result = {
            "action": "create_event",
            "params": {"description": "Hiking trip"},
            "confidence": 0.9,
            "assistant_response": "Let's plan your hiking trip!"
        }
        validation = validate_action_result(result, ACTIONS)
        assert validation.valid is True

    def test_validate_join_without_event_id(self):
        """Test join_event validation fails without event_id."""
        from ai.validator import validate_action_result
        from ai.actions import ACTIONS
        
        result = {
            "action": "join_event",
            "params": {},
            "confidence": 0.8
        }
        validation = validate_action_result(result, ACTIONS)
        assert validation.valid is False
        assert validation.recoverable is True


class TestEdgeCases:
    """Edge case tests."""

    def test_validate_with_extra_params(self):
        """Test validation passes with extra optional params."""
        from ai.validator import validate_action_result
        
        registry = {
            "test": {
                "description": "Test",
                "required_params": ["req1"],
                "optional_params": ["opt1"],
            }
        }
        
        result = {
            "action": "test",
            "params": {"req1": "value", "opt1": "optional", "extra": "ignored"},
            "confidence": 0.9
        }
        validation = validate_action_result(result, registry)
        assert validation.valid is True

    def test_validate_zero_confidence(self):
        """Test validation passes with zero confidence."""
        from ai.validator import validate_action_result
        
        registry = {
            "test": {
                "description": "Test",
                "required_params": [],
                "optional_params": [],
            }
        }
        
        result = {
            "action": "test",
            "params": {},
            "confidence": 0.0
        }
        validation = validate_action_result(result, registry)
        assert validation.valid is True

    def test_validate_boolean_param_values(self):
        """Test validation with boolean param values."""
        from ai.validator import validate_action_result
        
        registry = {
            "test": {
                "description": "Test",
                "required_params": ["flag"],
                "optional_params": [],
            }
        }
        
        # False should be a valid value
        result = {
            "action": "test",
            "params": {"flag": False},
            "confidence": 0.9
        }
        validation = validate_action_result(result, registry)
        assert validation.valid is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
