#!/usr/bin/env python3
"""Centralized in-memory state management with TTL, locks, and type safety.

This module provides the StateStore class, which wraps ``context.user_data``
and provides:

- **Typed access** to all state categories via dedicated methods
- **TTL-based expiration** on creation flows, enrichment sessions, and
  modification requests
- **Per-event locks** for atomic access to event-specific state
- **Lazy cleanup** — expired entries are removed on first access after
  expiration, avoiding periodic scan overhead

The StateStore is designed as a singleton accessible via
``get_state_store()``. It is backward compatible with existing
``context.user_data`` access patterns — handlers can migrate incrementally.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, overload

from .state_models import (
    ENRICHMENT_TTL,
    EVENT_FLOW_TTL,
    MODIFY_REQUEST_TTL,
    CREATION_INTENT_VALUES,
    ENRICHMENT_ACTION_VALUES,
    EVENT_FLOW_STAGES,
    EventFlow,
    EventFlowData,
    ModifyRequest,
    ModifyRequestText,
    PrivateEventFlow,
)


class _StateEntry:
    """Internal wrapper that tracks creation/access time for TTL."""

    __slots__ = ("value", "created_at", "last_accessed", "ttl")

    def __init__(
        self,
        value: Any,
        ttl: timedelta,
        created_at: datetime | None = None,
    ) -> None:
        self.value = value
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_accessed = self.created_at
        self.ttl = ttl

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) - self.last_accessed > self.ttl

    def touch(self) -> None:
        self.last_accessed = datetime.now(timezone.utc)


class StateStore:
    """Centralized in-memory state management backed by ``context.user_data``.

    Each instance is tied to a single user's ``context.user_data`` dict.
    Use ``get_state_store(user_id, context)`` to obtain or create one.
    """

    _instances: dict[int, StateStore] = {}
    _locks: dict[int, asyncio.Lock] = {}  # user_id -> lock for store creation

    def __init__(self, user_id: int, user_data: dict[str, Any] | None) -> None:
        self.user_id = user_id
        self._user_data = user_data if user_data is not None else {}
        self._event_locks: dict[int, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Event Flow Access
    # ------------------------------------------------------------------

    def get_event_flow(self, *, private: bool = False) -> EventFlow | None:
        """Get the current event creation flow, or None if expired/missing."""
        key = "private_event_flow" if private else "event_flow"
        entry = self._user_data.get(key)
        if isinstance(entry, _StateEntry):
            if entry.is_expired():
                self._user_data.pop(key, None)
                return None
            entry.touch()
            return entry.value
        if isinstance(entry, dict):
            return entry  # Legacy untyped dict — still usable
        return None

    def set_event_flow(self, flow: EventFlow, *, private: bool = False) -> None:
        """Store an event creation flow with TTL."""
        key = "private_event_flow" if private else "event_flow"
        self._user_data[key] = _StateEntry(flow, EVENT_FLOW_TTL)

    def clear_event_flow(self, *, private: bool = False) -> None:
        """Remove the current event creation flow."""
        key = "private_event_flow" if private else "event_flow"
        self._user_data.pop(key, None)

    def update_event_flow_data(self, updates: dict[str, Any]) -> bool:
        """Merge ``updates`` into the current flow's ``data`` dict.

        Returns ``True`` if the flow existed and was updated, ``False`` otherwise.
        """
        flow = self.get_event_flow()
        if flow is None:
            return False
        flow["data"].update(updates)
        return True

    def update_event_flow_stage(self, stage: EVENT_FLOW_STAGES) -> bool:
        """Advance the flow stage. Returns ``False`` if no flow exists."""
        flow = self.get_event_flow()
        if flow is None:
            return False
        flow["stage"] = stage
        return True

    # ------------------------------------------------------------------
    # Creation Intent
    # ------------------------------------------------------------------

    def get_creation_intent(self) -> str | None:
        """Get the user's creation intent (``specific`` | ``flexible``)."""
        return self._user_data.get("creation_intent")

    def set_creation_intent(self, intent: CREATION_INTENT_VALUES) -> None:
        self._user_data["creation_intent"] = intent

    def clear_creation_intent(self) -> None:
        self._user_data.pop("creation_intent", None)

    # ------------------------------------------------------------------
    # Enrichment Sessions (isolated by UUID)
    # ------------------------------------------------------------------

    def get_enrichment_session(self) -> dict[str, Any] | None:
        """Get the current enrichment session data.

        Returns a dict with keys ``session_id``, ``event_id``, ``action``,
        ``created_at`` — or ``None`` if no active session.
        """
        entry = self._user_data.get("enrich_session")
        if isinstance(entry, _StateEntry):
            if entry.is_expired():
                self._clear_enrichment_session()
                return None
            entry.touch()
            return entry.value
        if isinstance(entry, dict) and "session_id" in entry:
            return entry
        return None

    def set_enrichment_session(self, event_id: int, action: ENRICHMENT_ACTION_VALUES) -> str:
        """Create a new enrichment session, returning the session UUID."""
        session_id = uuid.uuid4().hex[:12]
        session: dict[str, Any] = {
            "session_id": session_id,
            "event_id": event_id,
            "action": action,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._user_data["enrich_session"] = _StateEntry(session, ENRICHMENT_TTL)
        # Also set legacy keys for backward compatibility
        self._user_data["enrich_event_id"] = event_id
        self._user_data["enrich_action"] = action
        return session_id

    def clear_enrichment_session(self) -> None:
        self._clear_enrichment_session()

    def _clear_enrichment_session(self) -> None:
        self._user_data.pop("enrich_session", None)
        self._user_data.pop("enrich_event_id", None)
        self._user_data.pop("enrich_action", None)

    # ------------------------------------------------------------------
    # Modification Requests (dynamic keys, UUID-scoped)
    # ------------------------------------------------------------------

    def set_modify_request(self, request: ModifyRequest) -> str:
        """Store a modification request, returning its ID."""
        request_id = uuid.uuid4().hex[:8]
        key = f"pending_modify_request_{request_id}"
        self._user_data[key] = _StateEntry(dict(request), MODIFY_REQUEST_TTL)
        return request_id

    def get_modify_request(self, request_id: str) -> ModifyRequest | None:
        entry = self._user_data.get(f"pending_modify_request_{request_id}")
        if isinstance(entry, _StateEntry):
            if entry.is_expired():
                self._user_data.pop(f"pending_modify_request_{request_id}", None)
                return None
            entry.touch()
            return entry.value
        if isinstance(entry, dict):
            return entry
        return None

    def pop_modify_request(self, request_id: str) -> ModifyRequest | None:
        """Get and remove a modification request."""
        key = f"pending_modify_request_{request_id}"
        entry = self._user_data.pop(key, None)
        if isinstance(entry, _StateEntry):
            if entry.is_expired():
                return None
            return entry.value
        return entry if isinstance(entry, dict) else None

    def set_modify_request_text(self, request_id: str, text_data: ModifyRequestText) -> None:
        key = f"pending_mod_text_{request_id}"
        self._user_data[key] = _StateEntry(dict(text_data), MODIFY_REQUEST_TTL)

    def pop_modify_request_text(self, request_id: str) -> ModifyRequestText | None:
        key = f"pending_mod_text_{request_id}"
        entry = self._user_data.pop(key, None)
        if isinstance(entry, _StateEntry):
            if entry.is_expired():
                return None
            return entry.value
        return entry if isinstance(entry, dict) else None

    # ------------------------------------------------------------------
    # Per-Event Locks
    # ------------------------------------------------------------------

    def get_event_lock(self, event_id: int) -> asyncio.Lock:
        """Get (or create) an asyncio.Lock for a specific event."""
        if event_id not in self._event_locks:
            self._event_locks[event_id] = asyncio.Lock()
        return self._event_locks[event_id]

    # ------------------------------------------------------------------
    # General Purpose Access (for keys not covered by typed methods)
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Get a raw value from user_data, with TTL check for _StateEntry."""
        entry = self._user_data.get(key)
        if isinstance(entry, _StateEntry):
            if entry.is_expired():
                self._user_data.pop(key, None)
                return default
            entry.touch()
            return entry.value
        return self._user_data.get(key, default)

    def set(self, key: str, value: Any, ttl: timedelta | None = None) -> None:
        """Set a value, optionally with TTL."""
        if ttl is not None:
            self._user_data[key] = _StateEntry(value, ttl)
        else:
            self._user_data[key] = value

    def pop(self, key: str, default: Any = None) -> Any:
        """Get and remove a value."""
        return self._user_data.pop(key, default)

    def has(self, key: str) -> bool:
        return key in self._user_data

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns the count of removed entries."""
        removed = 0
        expired_keys = []
        for key, entry in self._user_data.items():
            if isinstance(entry, _StateEntry) and entry.is_expired():
                expired_keys.append(key)
        for key in expired_keys:
            self._user_data.pop(key, None)
            removed += 1
        return removed

    # ------------------------------------------------------------------
    # Raw access (for backward compatibility during migration)
    # ------------------------------------------------------------------

    @property
    def raw(self) -> dict[str, Any]:
        """Access the underlying ``context.user_data`` dict directly.

        Use this sparingly — prefer the typed methods above.
        """
        return self._user_data


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_store_for_user: dict[int, StateStore] = {}


def get_state_store(user_id: int, user_data: dict[str, Any] | None = None) -> StateStore:
    """Get or create a StateStore for a user.

    Args:
        user_id: The Telegram user ID.
        user_data: The ``context.user_data`` dict (populated by the dispatcher).

    Returns:
        A StateStore instance bound to the user's data.
    """
    if user_id not in _store_for_user:
        _store_for_user[user_id] = StateStore(user_id, user_data)
    store = _store_for_user[user_id]
    # Sync raw dict in case it was replaced (e.g., after bot restart)
    store._user_data = user_data if user_data is not None else {}
    return store


def clear_state_store(user_id: int | None = None) -> None:
    """Clear cached StateStore instances.

    Args:
        user_id: If provided, clear only that user's store. Otherwise clear all.
    """
    if user_id is not None:
        _store_for_user.pop(user_id, None)
    else:
        _store_for_user.clear()
