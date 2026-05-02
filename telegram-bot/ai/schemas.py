"""
LLM Output Schema Validation - Pydantic models for LLM response validation.
PRD v2 Priority 4: Production Hardening (TODO-016).

This module provides schema validation for all LLM outputs to ensure:
- Type safety
- Required fields present
- Value ranges validated
- Clear error logging
"""

from typing import Any, Callable, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, validator, ValidationError


# ============================================================================
# Constraint Inference Schema
# ============================================================================


class ConstraintInference(BaseModel):
    """Schema for constraint inference from natural language."""

    constraint_type: Literal["if_joins", "if_attends", "unless_joins"]
    target_username: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.6)
    sanitized_summary: str = Field(max_length=500, default="")

    @validator("target_username")
    def username_not_empty(cls, v: Optional[str]) -> Optional[str]:
        """Ensure username is not empty string."""
        if v is not None and len(v.strip()) == 0:
            return None
        return v.strip() if v else None

    @validator("sanitized_summary")
    def ensure_summary_not_empty(cls, v: str, values: Dict[str, Any]) -> str:
        """Ensure summary has content."""
        if not v or len(v.strip()) == 0:
            # Fallback to constraint type description
            constraint_type = values.get("constraint_type", "constraint")
            return f"User set {constraint_type} constraint"
        return v.strip()


# ============================================================================
# Event Draft Patch Schema
# ============================================================================


class EventDraftPatch(BaseModel):
    """Schema for event draft modification patches."""

    description: Optional[str] = Field(max_length=500, default=None)
    event_type: Optional[Literal["social", "sports", "work"]] = None
    scheduled_time_iso: Optional[str] = Field(max_length=25, default=None)
    clear_time: bool = False
    duration_minutes: Optional[int] = Field(ge=30, le=720, default=None)
    min_participants: Optional[int] = Field(ge=1, le=200, default=None)
    target_participants: Optional[int] = Field(ge=1, le=200, default=None)
    invitees_add: List[str] = Field(default_factory=list)
    invitees_remove: List[str] = Field(default_factory=list)
    invite_all_members: Optional[bool] = None
    scheduling_mode: Optional[Literal["fixed", "flexible"]] = None
    location_type: Optional[Literal["home", "outdoor", "cafe", "office", "gym"]] = None
    budget_level: Optional[Literal["free", "low", "medium", "high"]] = None
    transport_mode: Optional[Literal["walk", "public_transit", "drive", "any"]] = None
    note: Optional[str] = Field(max_length=500, default=None)

    @validator("invitees_add", "invitees_remove")
    def normalize_handles(cls, v: List[str]) -> List[str]:
        """Normalize Telegram handles (add @ prefix, lowercase)."""
        normalized = []
        for handle in v:
            h = str(handle).strip()
            if not h:
                continue
            if not h.startswith("@"):
                h = f"@{h}"
            normalized.append(h.lower())
        return normalized


# ============================================================================
# Event Draft from Context Schema
# ============================================================================


class InferredConstraint(BaseModel):
    """Schema for a single inferred constraint from chat context."""

    constraint_type: Literal["if_joins", "if_attends", "unless_joins"]
    target_username: str = Field(max_length=50, min_length=1)
    note: str = Field(max_length=200, default="")


class EventDraftFromContext(BaseModel):
    """Schema for event draft generated from chat context."""

    description: str = Field(max_length=500, default="Group planned event")
    event_type: Literal["social", "sports", "work"] = "social"
    scheduled_time: Optional[str] = Field(max_length=25, default=None)
    duration_minutes: int = Field(ge=30, le=720, default=120)
    min_participants: int = Field(ge=1, le=200, default=3)
    target_participants: int = Field(ge=1, le=200, default=5)
    invite_all_members: bool = True
    invitees: List[str] = Field(default_factory=list)
    planning_notes: List[str] = Field(default_factory=list)
    date_preset: Optional[
        Literal["today", "tomorrow", "weekend", "nextweek", "custom"]
    ] = None
    time_window: Optional[
        Literal["early-morning", "morning", "afternoon", "evening", "night"]
    ] = None
    location_type: Optional[Literal["home", "outdoor", "cafe", "office", "gym"]] = None
    budget_level: Optional[Literal["free", "low", "medium", "high"]] = None
    transport_mode: Optional[Literal["walk", "public_transit", "drive", "any"]] = None
    inferred_constraints: List[InferredConstraint] = Field(default_factory=list)

    @validator("invitees")
    def normalize_invitees(cls, v: List[str]) -> List[str]:
        """Normalize invitee handles."""
        normalized = []
        for handle in v:
            h = str(handle).strip()
            if not h:
                continue
            if not h.startswith("@"):
                h = f"@{h}"
            normalized.append(h.lower())
        return normalized

    @validator("planning_notes")
    def validate_notes(cls, v: List[str]) -> List[str]:
        """Validate planning notes."""
        validated = []
        for note in v:
            n = str(note).strip()[:300]
            if n:
                validated.append(n)
        return validated


# ============================================================================
# Group Mention Action Schema
# ============================================================================


class GroupMentionAction(BaseModel):
    """Schema for group mention action inference."""

    action_type: Literal[
        "opinion",
        "organize_event",
        "organize_event_flexible",
        "status",
        "event_details",
        "suggest_time",
        "constraint_add",
        "join",
        "confirm",
        "cancel",
        "lock",
        "request_confirmations",
    ] = "opinion"
    event_id: Optional[int] = Field(default=None)
    target_username: Optional[str] = None
    constraint_type: Optional[Literal["if_joins", "if_attends", "unless_joins"]] = None
    assistant_response: str = Field(max_length=500, default="")

    @validator("target_username")
    def username_not_empty(cls, v: Optional[str]) -> Optional[str]:
        """Ensure username is not empty string."""
        if v is not None and len(v.strip()) == 0:
            return None
        return v.strip().lstrip("@") if v else None

    @validator("assistant_response")
    def ensure_response_not_empty(cls, v: str) -> str:
        """Ensure response has content."""
        if not v or len(v.strip()) == 0:
            return "I understood your request and will help with that."
        return v.strip()


# ============================================================================
# Conflict Resolution Schema
# ============================================================================


class ConflictResolution(BaseModel):
    """Schema for scheduling conflict resolution."""

    conflict_detected: bool = True
    suggested_time: str = Field(max_length=25, default="TBD")
    reasoning: str = Field(max_length=500, default="")
    compromises: List[str] = Field(default_factory=list)

    @validator("compromises")
    def validate_compromises(cls, v: List[str]) -> List[str]:
        """Validate compromise suggestions."""
        validated = []
        for comp in v:
            c = str(comp).strip()[:200]
            if c:
                validated.append(c)
        return validated[:5]  # Max 5 compromises


# ============================================================================
# Constraint Analysis Schema
# ============================================================================


class ConstraintConflict(BaseModel):
    """Schema for constraint conflict analysis."""

    user: int
    target: int
    condition: str = Field(max_length=300, default="")


class ConstraintAnalysis(BaseModel):
    """Schema for constraint analysis result."""

    conflicts: List[ConstraintConflict] = Field(default_factory=list)


# ============================================================================
# Memory Weave Schema (for structured LLM output)
# ============================================================================


class MemoryWeaveFragment(BaseModel):
    """Schema for individual memory fragment in weave."""

    text: str = Field(max_length=500)
    tone_tag: str = Field(max_length=50, default="neutral")
    display_order: int = Field(ge=1, default=1)


class MemoryWeaveOutput(BaseModel):
    """Schema for LLM-generated memory weave."""

    weave_text: str = Field(max_length=2000)
    fragments_used: int = Field(ge=0, default=0)


# ============================================================================
# Validation Helper Functions
# ============================================================================


def validate_llm_output(
    schema_class: type[BaseModel],
    raw_response: str,
    fallback_factory: Optional[Callable[[], Dict[str, Any]]] = None,
    logger: Any = None,
) -> Dict[str, Any]:
    """
    Validate LLM output against Pydantic schema.

    Args:
        schema_class: Pydantic model class to validate against
        raw_response: Raw JSON string from LLM
        fallback_factory: Optional callable to generate fallback response
        logger: Optional logger for error logging

    Returns:
        Validated dict or fallback response

    Example:
        result = validate_llm_output(
            ConstraintInference,
            llm_response,
            fallback_factory=lambda: {"constraint_type": "if_joins", ...},
            logger=logger
        )
    """
    import json

    try:
        # Parse JSON
        parsed = json.loads(raw_response)

        # Validate against schema
        validated = schema_class(**parsed)

        return validated.dict()

    except json.JSONDecodeError as e:
        if logger:
            logger.warning(
                "LLM output JSON parse error: %s",
                e,
                extra={"raw_response": raw_response[:200]},
            )
        if fallback_factory:
            return fallback_factory()
        raise

    except ValidationError as e:
        if logger:
            logger.warning(
                "LLM output schema validation error: %s",
                e.errors(),
                extra={"raw_response": raw_response[:200]},
            )
        if fallback_factory:
            return fallback_factory()
        raise

    except Exception as e:
        if logger:
            logger.exception(
                "LLM output validation failed: %s",
                e,
                extra={"raw_response": raw_response[:200]},
            )
        if fallback_factory:
            return fallback_factory()
        raise
