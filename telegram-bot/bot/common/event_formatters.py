"""Human-readable formatters for event planning preferences with context."""

from typing import Optional, Dict, Any
from datetime import datetime


# Mapping dictionaries for human-readable labels
DATE_PRESET_LABELS = {
    "today": "Today",
    "tomorrow": "Tomorrow",
    "weekend": "This Weekend",
    "nextweek": "Next Week",
    "custom": "Custom Date",
}

TIME_WINDOW_LABELS = {
    "early-morning": "Early Morning (6AM-9AM)",
    "morning": "Morning (9AM-12PM)",
    "afternoon": "Afternoon (12PM-5PM)",
    "evening": "Evening (6PM-10PM)",
    "night": "Night (10PM-2AM)",
}

LOCATION_TYPE_LABELS = {
    "home": "Indoor (Home/Residential)",
    "outdoor": "Outdoor Activity",
    "cafe": "Cafe/Restaurant",
    "office": "Office/Workspace",
    "gym": "Gym/Fitness Center",
}

BUDGET_LEVEL_LABELS = {
    "free": "Free/Low-cost",
    "low": "Budget-friendly",
    "medium": "Moderate Cost",
    "high": "Premium/High-cost",
}

TRANSPORT_MODE_LABELS = {
    "walk": "Walking Distance",
    "public_transit": "Public Transit",
    "drive": "Driving Required",
    "any": "Flexible/Any Transport",
}

STATE_LABELS = {
    "proposed": "Proposed (Gathering Interest)",
    "interested": "Interest Confirmed (Awaiting Commitment)",
    "confirmed": "Confirmed (Ready to Lock)",
    "locked": "Locked (Finalized)",
    "completed": "Completed",
    "cancelled": "Cancelled",
}


def format_date_preset(
    value: Optional[str], context: Optional[Dict[str, Any]] = None
) -> str:
    """Format date preset with human-readable label and optional context."""
    if not value:
        return "Not specified (flexible)"

    label = DATE_PRESET_LABELS.get(value, value.replace("_", " ").title())

    # Add context if available
    if context and context.get("source_date"):
        return f"{label} (mentioned on {context['source_date']})"

    return label


def format_time_window(
    value: Optional[str], context: Optional[Dict[str, Any]] = None
) -> str:
    """Format time window with human-readable label and optional context."""
    if not value:
        return "Not specified (flexible)"

    label = TIME_WINDOW_LABELS.get(value, value.replace("_", " ").title())

    if context and context.get("source_time"):
        return f"{label} (mentioned at {context['source_time']})"

    return label


def format_location_type(
    value: Optional[str], context: Optional[Dict[str, Any]] = None
) -> str:
    """Format location type with human-readable label and optional context."""
    if not value:
        return "Not specified (to be discussed)"

    label = LOCATION_TYPE_LABELS.get(value, value.replace("_", " ").title())

    if context and context.get("mentioned_by"):
        return f"{label} (suggested by {context['mentioned_by']})"

    return label


def format_budget_level(
    value: Optional[str], context: Optional[Dict[str, Any]] = None
) -> str:
    """Format budget level with human-readable label and optional context."""
    if not value:
        return "Not specified (flexible)"

    label = BUDGET_LEVEL_LABELS.get(value, value.replace("_", " ").title())

    if context and context.get("mentioned_by"):
        return f"{label} (suggested by {context['mentioned_by']})"

    return label


def format_transport_mode(
    value: Optional[str], context: Optional[Dict[str, Any]] = None
) -> str:
    """Format transport mode with human-readable label and optional context."""
    if not value:
        return "Not specified (flexible)"

    label = TRANSPORT_MODE_LABELS.get(value, value.replace("_", " ").title())

    if context and context.get("mentioned_by"):
        return f"{label} (suggested by {context['mentioned_by']})"

    return label


def format_event_state(value: Optional[str]) -> str:
    """Format event state with human-readable label."""
    if not value:
        return "Unknown"

    return STATE_LABELS.get(value, value.replace("_", " ").title())


def format_duration(minutes: Optional[int]) -> str:
    """Format duration in minutes to human-readable string."""
    if not minutes:
        return "2 hours (default)"

    if minutes < 60:
        return f"{minutes} minutes"
    elif minutes == 60:
        return "1 hour"
    elif minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hours"
    else:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"


def format_scheduled_time(scheduled_time, include_flexible_note: bool = True) -> str:
    """Format scheduled time with context-appropriate messaging."""
    if scheduled_time:
        # Handle both datetime objects and strings
        if isinstance(scheduled_time, datetime):
            return scheduled_time.strftime("%Y-%m-%d %H:%M")
        return str(scheduled_time)

    if include_flexible_note:
        return "Not yet scheduled (use /suggest_time to find optimal time)"
    return "TBD"


def format_commit_by(commit_by, include_context: bool = True) -> str:
    """Format commit-by deadline with context."""
    if commit_by:
        if isinstance(commit_by, datetime):
            return commit_by.strftime("%Y-%m-%d %H:%M")
        return str(commit_by)

    if include_context:
        return "Not set (members can commit flexibly)"
    return "N/A"


def format_planning_prefs_with_context(
    planning_prefs: Dict[str, Any], context_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """
    Format all planning preferences with human-readable labels and context.

    Args:
        planning_prefs: Raw planning preferences from event.planning_prefs
        context_metadata: Optional context like:
            - source_date: When preferences were discussed
            - source_time: What time preferences were discussed
            - mentioned_by: Who suggested certain preferences
            - discussion_summary: Brief summary of discussion

    Returns:
        Dictionary with formatted labels ready for display
    """
    if not planning_prefs:
        planning_prefs = {}

    if not context_metadata:
        context_metadata = {}

    return {
        "date_preset": format_date_preset(
            planning_prefs.get("date_preset"),
            context_metadata.get("date_preset_context"),
        ),
        "time_window": format_time_window(
            planning_prefs.get("time_window"),
            context_metadata.get("time_window_context"),
        ),
        "location_type": format_location_type(
            planning_prefs.get("location_type"),
            context_metadata.get("location_context"),
        ),
        "budget_level": format_budget_level(
            planning_prefs.get("budget_level"), context_metadata.get("budget_context")
        ),
        "transport_mode": format_transport_mode(
            planning_prefs.get("transport_mode"),
            context_metadata.get("transport_context"),
        ),
    }


def format_hashtags(hashtags: list[str]) -> str:
    """Format hashtags for display."""
    if not hashtags:
        return ""

    return " ".join(f"#{tag}" for tag in hashtags)


def format_lineage_door(lineage_fragment: Optional[str], event_type: str) -> str:
    """Format lineage door for event creation context."""
    if not lineage_fragment:
        return ""

    first_sentence = (
        lineage_fragment.split(".")[0] if "." in lineage_fragment else lineage_fragment
    )

    return (
        f"Last time your group did a {event_type} event, "
        f'someone said: "{first_sentence}".'
    )
