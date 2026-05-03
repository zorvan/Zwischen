"""User preference handling helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import UserPreference


DEFAULT_TIME_PREFERENCES = ["any", "morning", "afternoon", "evening", "night"]
DEFAULT_ACTIVITY_PREFERENCES = ["any", "social", "sports", "work", "outdoor", "indoor"]
DEFAULT_BUDGET_PREFERENCES = ["any", "free", "low", "medium", "high"]
DEFAULT_LOCATION_PREFERENCES = ["any", "home", "outdoor", "cafe", "office", "gym"]
DEFAULT_TRANSPORT_PREFERENCES = ["any", "walk", "public_transit", "drive"]

PRIVACY_DEFAULTS = {
    "time": {
        "private": False,
        "share_with_organizer": True,
        "share_with_attendees": False,
    },
    "activity": {
        "private": False,
        "share_with_organizer": True,
        "share_with_attendees": False,
    },
    "budget": {
        "private": True,
        "share_with_organizer": True,
        "share_with_attendees": False,
    },
    "location_type": {
        "private": False,
        "share_with_organizer": True,
        "share_with_attendees": False,
    },
    "transport": {
        "private": True,
        "share_with_organizer": True,
        "share_with_attendees": False,
    },
}


def get_preference_defaults(preference_type: str) -> List[str]:
    """Get default values for a preference type."""
    defaults = {
        "time": DEFAULT_TIME_PREFERENCES,
        "activity": DEFAULT_ACTIVITY_PREFERENCES,
        "budget": DEFAULT_BUDGET_PREFERENCES,
        "location_type": DEFAULT_LOCATION_PREFERENCES,
        "transport": DEFAULT_TRANSPORT_PREFERENCES,
    }
    return defaults.get(preference_type, [])


def get_privacy_defaults(preference_type: str) -> Dict[str, Any]:
    """Get default privacy settings for a preference type."""
    return PRIVACY_DEFAULTS.get(
        preference_type, PRIVACY_DEFAULTS.get("time", {})
    ).copy()


async def get_user_preferences(
    session: AsyncSession, telegram_user_id: int
) -> Optional[UserPreference]:
    """Get user preferences or None if not set."""
    result = await session.execute(
        select(UserPreference).where(UserPreference.user_id == telegram_user_id)
    )
    return result.scalar_one_or_none()


async def create_or_update_user_preferences(
    session: AsyncSession,
    telegram_user_id: int,
    time_preference: Optional[str] = None,
    activity_preference: Optional[str] = None,
    budget_preference: Optional[str] = None,
    location_type_preference: Optional[str] = None,
    transport_preference: Optional[str] = None,
    language_preference: Optional[str] = None,
    privacy_settings: Optional[Dict[str, Any]] = None,
) -> UserPreference:
    """Create or update user preferences."""
    preferences = await get_user_preferences(session, telegram_user_id)

    if not preferences:
        preferences = UserPreference(
            user_id=telegram_user_id,
            time_preference=time_preference or "any",
            activity_preference=activity_preference or "any",
            budget_preference=budget_preference or "any",
            location_type_preference=location_type_preference or "any",
            transport_preference=transport_preference or "any",
            language_preference=language_preference,
            privacy_settings=privacy_settings or {},
        )
        session.add(preferences)
    else:
        if time_preference:
            preferences.time_preference = time_preference
        if activity_preference:
            preferences.activity_preference = activity_preference
        if budget_preference:
            preferences.budget_preference = budget_preference
        if location_type_preference:
            preferences.location_type_preference = location_type_preference
        if transport_preference:
            preferences.transport_preference = transport_preference
        if language_preference:
            preferences.language_preference = language_preference
        if privacy_settings:
            current_privacy = preferences.privacy_settings or {}
            current_privacy.update(privacy_settings)
            preferences.privacy_settings = current_privacy

    preferences.last_updated = datetime.utcnow()
    await session.flush()
    return preferences


async def delete_user_preferences(session: AsyncSession, telegram_user_id: int) -> bool:
    """Delete user preferences. Returns True if deleted."""
    preferences = await get_user_preferences(session, telegram_user_id)
    if preferences:
        await session.delete(preferences)
        await session.flush()
        return True
    return False


def get_preference_value(
    preferences: UserPreference,
    preference_type: str,
    is_private: bool = False,
    is_organizer: bool = False,
) -> Optional[str]:
    """Get preference value with privacy controls."""
    if not preferences:
        return None

    privacy = preferences.privacy_settings or {}

    if is_organizer or not is_private:
        return getattr(preferences, f"{preference_type}_preference", None)

    privacy_settings = privacy.get(
        preference_type, get_privacy_defaults(preference_type)
    )
    if privacy_settings.get("private", False):
        return None

    return getattr(preferences, f"{preference_type}_preference", None)


def merge_aggregate_preferences(
    preferences_list: List[UserPreference],
    preference_type: str,
) -> Dict[str, int]:
    """Merge preferences from multiple users for aggregate recommendations."""
    counts: Dict[str, int] = {}
    for pref in preferences_list:
        value = getattr(pref, f"{preference_type}_preference", None)
        if value and value != "any":
            counts[value] = counts.get(value, 0) + 1
        elif value == "any":
            continue

    return counts


PREFERENCE_DECAY_DAYS = 90
PREFERENCE_REFRESH_THRESHOLD_DAYS = 60


def should_refresh_preference(
    preferences: UserPreference, preference_type: str
) -> bool:
    """Check if a preference should be refreshed based on age."""
    last_updated = preferences.last_updated or preferences.created_at
    if not last_updated:
        return True

    days_since_update = (datetime.utcnow() - last_updated).days
    return days_since_update > PREFERENCE_REFRESH_THRESHOLD_DAYS


def apply_preference_decay(preferences: UserPreference) -> Dict[str, str]:
    """Apply confidence decay to preferences, marking them for refresh."""
    decayed: Dict[str, str] = {}
    last_updated = preferences.last_updated or preferences.created_at
    if not last_updated:
        return decayed

    days_since_update = (datetime.utcnow() - last_updated).days

    if days_since_update > PREFERENCE_DECAY_DAYS:
        for pref_type in ["time", "activity", "budget", "location_type", "transport"]:
            current_value = getattr(preferences, f"{pref_type}_preference", None)
            if current_value and current_value != "any":
                decayed[pref_type] = "any"

    return decayed


def get_aggregate_preference_counts(
    preferences_list: List[UserPreference],
    preference_type: str,
) -> tuple[Dict[str, int], int]:
    """Get aggregate preference counts with privacy filtering.

    Returns:
        Tuple of (preference_counts, total_non_private)
    """
    counts: Dict[str, int] = {}
    total_non_private = 0

    for pref in preferences_list:
        privacy = pref.privacy_settings or {}
        pref_type = preference_type.replace("_type", "")
        privacy_settings = privacy.get(pref_type, get_privacy_defaults(pref_type))

        if privacy_settings.get("private", False):
            continue

        value = getattr(pref, f"{preference_type}_preference", None)
        if value and value != "any":
            counts[value] = counts.get(value, 0) + 1
            total_non_private += 1

    return counts, total_non_private


def format_aggregate_preference(
    preference_type: str,
    counts: Dict[str, int],
    total_users: int,
) -> str:
    """Format aggregate preference for display in group chats."""
    if not counts:
        return f"{preference_type.replace('_', ' ').title()}: No preferences shared"

    sorted_prefs = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top_choice = sorted_prefs[0]

    percentage = (top_choice[1] / total_users * 100) if total_users > 0 else 0

    return (
        f"{preference_type.replace('_', ' ').title()}: {top_choice[0]} "
        f"({top_choice[1]}/{total_users} users, {percentage:.0f}%)"
    )


async def refresh_expired_preferences(
    session: AsyncSession, telegram_user_id: int
) -> Dict[str, str]:
    """Refresh preferences that have expired due to decay.

    Returns dict of preference_type -> old_value for changed preferences.
    """
    preferences = await get_user_preferences(session, telegram_user_id)
    if not preferences:
        return {}

    decayed = apply_preference_decay(preferences)

    if not decayed:
        return {}

    old_values: Dict[str, str] = {}
    for pref_type, new_value in decayed.items():
        old_value = getattr(preferences, f"{pref_type}_preference", None)
        old_values[pref_type] = old_value or ""
        setattr(preferences, f"{pref_type}_preference", new_value)

    preferences.last_updated = datetime.utcnow()
    await session.flush()

    return old_values


async def get_users_preferences(
    session: AsyncSession,
    user_ids: List[int],
) -> Dict[int, UserPreference]:
    """Get preferences for multiple users."""
    result = await session.execute(
        select(UserPreference).where(UserPreference.user_id.in_(user_ids))
    )
    prefs = result.scalars().all()
    return {p.user_id: p for p in prefs}


async def get_group_aggregate_preferences(
    session: AsyncSession,
    event_id: int,
    is_organizer: bool,
) -> Dict[str, str]:
    """Get aggregate preferences for all participants in an event.

    For non-organizers: only show aggregate (no individual preferences)
    For organizers: can show individual preferences if not marked private
    """
    from db.models import Event

    result = await session.execute(select(Event).where(Event.event_id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        return {}

    from db.users import get_user_ids_for_telegram_ids

    telegram_ids = [
        int(participant.telegram_user_id) for participant in (event.participants or [])
    ]

    if not telegram_ids:
        return {}

    user_ids_map = await get_user_ids_for_telegram_ids(session, telegram_ids)

    preferences_list = []
    for uid in user_ids_map.values():
        pref = await get_user_preferences(session, uid)
        if pref:
            preferences_list.append(pref)

    if not preferences_list:
        return {}

    result_dict: Dict[str, str] = {}

    for pref_type in ["time", "activity", "budget", "location_type", "transport"]:
        counts, total_non_private = get_aggregate_preference_counts(
            preferences_list, f"{pref_type}_preference"
        )

        if not is_organizer and total_non_private == 0:
            result_dict[pref_type] = "No preferences shared"
        elif not is_organizer:
            formatted = format_aggregate_preference(
                pref_type, counts, total_non_private
            )
            result_dict[pref_type] = formatted
        else:
            if total_non_private > 0:
                result_dict[pref_type] = format_aggregate_preference(
                    pref_type, counts, total_non_private
                )
            else:
                result_dict[pref_type] = "All preferences are private"

    return result_dict


def set_preference_private_mode(
    privacy_settings: Dict[str, Any],
    preference_type: str,
    private_mode: bool,
) -> Dict[str, Any]:
    """Set a preference to 'prefer not to share' mode."""
    if "private_mode" not in privacy_settings:
        privacy_settings["private_mode"] = {}

    privacy_settings["private_mode"][preference_type] = private_mode

    if private_mode:
        privacy_settings[preference_type] = {
            "private": True,
            "share_with_organizer": False,
            "share_with_attendees": False,
        }

    return privacy_settings


async def get_language_preference(
    session: AsyncSession, telegram_user_id: int
) -> Optional[str]:
    """Get user's language preference from DB."""
    preferences = await get_user_preferences(session, telegram_user_id)
    if preferences and preferences.language_preference:
        return preferences.language_preference
    return None


async def set_language_preference(
    session: AsyncSession, telegram_user_id: int, lang: str
) -> None:
    """Set user's language preference."""
    await create_or_update_user_preferences(
        session=session,
        telegram_user_id=telegram_user_id,
        language_preference=lang,
    )
