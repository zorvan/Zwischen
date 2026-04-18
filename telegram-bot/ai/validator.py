#!/usr/bin/env python3
"""LLM Output Validator for v3.5.

This module provides:
- ValidationResult dataclass for structured validation results
- validate_action_result() for validating LLM output against action registry

PRD v3.5 Section 3.4: Output contract enforcement before dispatch.
"""
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

@dataclass
class ValidationResult:
    """Result of validating an LLM action inference."""
    valid: bool
    reason: Optional[str] = None
    recoverable: bool = False
    missing_params: Optional[List[str]] = None
    recovery_prompt: Optional[str] = None


def validate_action_result(result: Dict[str, Any], registry: Dict[str, Any]) -> ValidationResult:
    """
    Validate LLM action inference result against the action registry.
    
    This function enforces the output contract before dispatch:
    1. Result must be a dict
    2. Action must be known in the registry
    3. All required params must be present and non-empty
    
    Args:
        result: The parsed JSON result from LLM inference
        registry: The action registry (typically ACTIONS from ai.actions)
        
    Returns:
        ValidationResult with validation status and recovery info if needed
    """
    # Check result is a dict
    if not isinstance(result, dict):
        return ValidationResult(
            valid=False,
            reason=f"Result is not a dict, got: {type(result).__name__}",
            recoverable=False
        )
    
    # Extract action name
    action = result.get("action")
    if not action:
        return ValidationResult(
            valid=False,
            reason="Missing 'action' field in result",
            recoverable=False
        )
    
    # Check action exists in registry
    if action not in registry:
        return ValidationResult(
            valid=False,
            reason=f"Unknown action: {action!r}",
            recoverable=False
        )
    
    # Get action definition
    action_def = registry[action]
    required = action_def.get("required_params", [])
    
    # Check params exist
    params = result.get("params")
    if params is None:
        params = {}
    
    if not isinstance(params, dict):
        return ValidationResult(
            valid=False,
            reason=f"'params' must be a dict, got: {type(params).__name__}",
            recoverable=False
        )
    
    # Check all required params are present and non-empty
    missing = []
    for param in required:
        value = params.get(param)
        # Consider None, empty string, or missing key as missing
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(param)
    
    if missing:
        # Build recovery prompt based on what's missing
        if "event_id" in missing:
            recovery = (
                "Which event are you referring to? Here are your active events:"
            )
        else:
            recovery = f"I need a bit more info: {', '.join(missing)}"
        
        return ValidationResult(
            valid=False,
            reason=f"Missing required params: {missing}",
            recoverable=True,
            missing_params=missing,
            recovery_prompt=recovery
        )
    
    # All checks passed
    return ValidationResult(valid=True)


def build_validation_schema_for_prompt(registry: Dict[str, Any]) -> str:
    """
    Build a compact schema description for LLM prompt injection.
    
    This creates a human-readable description of available actions
    suitable for inclusion in an LLM prompt.
    
    Args:
        registry: The action registry
        
    Returns:
        Multi-line string describing available actions
    """
    lines = []
    for name, meta in registry.items():
        req = ", ".join(meta.get("required_params", [])) or "none"
        desc = meta.get("description", "No description")
        lines.append(f'  "{name}": {desc} | required: [{req}]')
    
    return "\n".join(lines)


__all__ = [
    "ValidationResult",
    "validate_action_result",
    "build_validation_schema_for_prompt",
]
