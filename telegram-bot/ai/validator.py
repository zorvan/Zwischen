"""
LLM Output Validator - Phase 1: LLM Infrastructure
v3.4 Rebuild Specification Section 3.2.2

This module enforces the output contract before dispatching actions.
It validates:
- Action exists in registry
- Required params are present
- Optional params are valid if present
- Confidence values are in range

When validation fails, it returns a ValidationResult with:
- valid: True/False
- reason: Human-readable explanation
- recoverable: True if user can provide missing info
- missing_params: List of missing required params (if recoverable)
"""

from typing import Any, Dict, List, Optional, Tuple
from ai.actions import ActionsRegistry


class ValidationResult:
    """
    Result of action validation.

    Attributes:
        valid: Whether the action is valid
        reason: Explanation if invalid
        recoverable: Whether user can fix by providing missing info
        missing_params: List of missing required params (if recoverable)
    """

    def __init__(
        self,
        valid: bool,
        reason: str = "",
        recoverable: bool = False,
        missing_params: Optional[List[str]] = None,
    ):
        self.valid = valid
        self.reason = reason
        self.recoverable = recoverable
        self.missing_params = missing_params or []

    def __repr__(self):
        if self.valid:
            return "ValidationResult(valid=True)"
        return f"ValidationResult(valid=False, reason='{self.reason}', recoverable={self.recoverable})"


class ActionValidator:
    """
    Validates LLM action inference output against the action registry.

    v3.4 Design:
    - Single validation point before dispatch
    - Distinguishes recoverable (missing params) vs non-recoverable (bad action) errors
    - Recoverable errors trigger user clarification, not silent fallback
    """

    def __init__(self, registry: Dict[str, Dict[str, Any]]):
        self.registry = registry

    def validate(self, result: Dict[str, Any]) -> ValidationResult:
        """
        Validate an LLM action inference result.

        Args:
            result: The LLM output dict with keys: action, params, confidence, (optional) assistant_response

        Returns:
            ValidationResult indicating validity and any issues
        """
        if not isinstance(result, dict):
            return ValidationResult(
                valid=False,
                reason="LLM output must be a JSON object",
                recoverable=False,
            )

        action = result.get("action")
        if not action or not isinstance(action, str):
            return ValidationResult(
                valid=False,
                reason="Missing or invalid 'action' field",
                recoverable=False,
            )

        if action not in self.registry:
            return ValidationResult(
                valid=False,
                reason=f"Unknown action: '{action}'. Valid actions: {', '.join(self.registry.keys())}",
                recoverable=False,
            )

        params = result.get("params", {})
        if not isinstance(params, dict):
            return ValidationResult(
                valid=False,
                reason="'params' must be a JSON object",
                recoverable=False,
            )

        missing = self._check_required_params(action, params)
        if missing:
            return ValidationResult(
                valid=False,
                reason=f"Missing required parameters: {', '.join(missing)}",
                recoverable=True,
                missing_params=missing,
            )

        invalid = self._check_param_types(action, params)
        if invalid:
            return ValidationResult(
                valid=False,
                reason=f"Invalid parameter types: {invalid}",
                recoverable=False,
            )

        confidence = result.get("confidence")
        if confidence is not None:
            if not isinstance(confidence, (int, float)):
                return ValidationResult(
                    valid=False,
                    reason="'confidence' must be a number",
                    recoverable=False,
                )
            if not (0.0 <= confidence <= 1.0):
                return ValidationResult(
                    valid=False,
                    reason="'confidence' must be between 0.0 and 1.0",
                    recoverable=False,
                )

        return ValidationResult(valid=True)

    def _check_required_params(self, action: str, params: Dict[str, Any]) -> List[str]:
        """Check that all required params are present and not None."""
        required = self.registry[action].get("required_params", [])
        missing = []
        for param in required:
            if param not in params or params[param] is None:
                missing.append(param)
        return missing

    def _check_param_types(self, action: str, params: Dict[str, Any]) -> Dict[str, str]:
        """Check that optional params have valid types."""
        invalid = {}
        optional = self.registry[action].get("optional_params", [])

        for param in optional:
            if param not in params:
                continue

            value = params[param]

            if param in ["event_id", "constraint_id"]:
                if not isinstance(value, int):
                    invalid[param] = f"expected int, got {type(value).__name__}"

            elif param == "confidence":
                if not isinstance(value, (int, float)):
                    invalid[param] = f"expected float, got {type(value).__name__}"

            elif param in [
                "description",
                "content",
                "reason",
                "question",
                "assistant_response",
            ]:
                if not isinstance(value, str):
                    invalid[param] = f"expected string, got {type(value).__name__}"

            elif param == "event_type":
                valid_types = ["social", "sports", "work"]
                if value not in valid_types:
                    invalid[param] = f"expected one of {valid_types}, got {value}"

            elif param == "group_id":
                if not isinstance(value, int):
                    invalid[param] = f"expected int, got {type(value).__name__}"

            elif param == "filter_state":
                valid_states = [
                    "proposed",
                    "interested",
                    "confirmed",
                    "locked",
                    "completed",
                    "cancelled",
                ]
                if value not in valid_states:
                    invalid[param] = f"expected one of {valid_states}, got {value}"

            elif param == "duration_minutes":
                if not isinstance(value, int) or value < 1 or value > 720:
                    invalid[param] = "expected int between 1 and 720"

            elif param == "min_participants" or param == "target_participants":
                if not isinstance(value, int) or value < 1 or value > 200:
                    invalid[param] = "expected int between 1 and 200"

            elif param == "invitees_add" or param == "invitees_remove":
                if not isinstance(value, list):
                    invalid[param] = f"expected list, got {type(value).__name__}"

            elif param == "time_slots":
                if not isinstance(value, list):
                    invalid[param] = f"expected list, got {type(value).__name__}"

            elif param == "target_username":
                if not isinstance(value, str):
                    invalid[param] = f"expected string, got {type(value).__name__}"

        return invalid

    def get_missing_params_message(self, missing: List[str]) -> str:
        """Generate a user-friendly message for missing parameters."""
        if "event_id" in missing:
            return "Which event are you referring to?"
        return f"Please provide: {', '.join(missing)}"


def create_validator() -> ActionValidator:
    """Create a validator with the canonical action registry."""
    return ActionValidator(ActionsRegistry.get_actions())
