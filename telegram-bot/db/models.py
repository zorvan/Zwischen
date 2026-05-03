"""
Database models for the coordination bot - v2.
Aligned with Coordination Engine PRD: From Coordination Tool to Shared Experience Engine.
"""

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Float,
    DateTime,
    JSON,
    Text,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Enum as SQLEnum,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base: Any = declarative_base()


class User(Base):
    """Users table - global identity across groups."""

    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    telegram_user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), unique=True)
    display_name = Column(String(255))
    # NOTE: expertise_per_activity removed in v3.5 (behavioral scoring deprecated per spec)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    constraints = relationship(
        "Constraint", back_populates="user", foreign_keys="[Constraint.user_id]"
    )
    target_constraints = relationship(
        "Constraint",
        back_populates="target_user",
        foreign_keys="[Constraint.target_user_id]",
    )
    logs = relationship("Log", back_populates="user")
    preferences = relationship("UserPreference", back_populates="user", uselist=False)


class Group(Base):
    """Groups table - Telegram group context."""

    __tablename__ = "groups"

    group_id = Column(Integer, primary_key=True)
    telegram_group_id = Column(BigInteger, unique=True, nullable=False)
    group_name = Column(String(255))
    group_type = Column(String(50), default="casual")
    member_list = Column(JSON, default=list)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    events = relationship("Event", back_populates="group")


class Event(Base):
    """Events table - gathering lifecycle."""

    __tablename__ = "events"

    event_id = Column(Integer, primary_key=True)
    group_id = Column(
        Integer, ForeignKey("groups.group_id", ondelete="CASCADE"), nullable=True
    )
    event_type = Column(String(100), nullable=False)
    title = Column(String(300), nullable=True)
    description = Column(Text)
    organizer_telegram_user_id = Column(BigInteger)
    # NOTE: Renamed from admin_telegram_user_id in v3.5 for clarity
    emergency_admin_telegram_user_id = Column(BigInteger)
    scheduled_time = Column(DateTime(timezone=True))
    commit_by = Column(DateTime(timezone=True))
    duration_minutes = Column(Integer, default=120)
    # PRD v2: Explicit threshold fields (Section 2.1)
    min_participants = Column(Integer, default=2)  # Absolute floor for viability
    target_participants = Column(
        Integer, default=6
    )  # Desired count for optimal experience
    collapse_at = Column(
        DateTime(timezone=True)
    )  # Auto-cancel deadline for underthreshold events
    lock_deadline = Column(DateTime(timezone=True))  # Cutoff for attendance changes

    planning_prefs = Column(JSON, default=dict)
    state = Column(String(20), default="proposed")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    locked_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # PRD v2: Optimistic concurrency control (Priority 1)
    version = Column(Integer, default=0, nullable=False)

    group = relationship("Group", back_populates="events")
    constraints = relationship(
        "Constraint", back_populates="event", cascade="all, delete-orphan"
    )
    logs = relationship("Log", back_populates="event")
    # PRD v2: Normalized participants table (Priority 1)
    participants = relationship(
        "EventParticipant", back_populates="event", cascade="all, delete-orphan"
    )
    # PRD v2: Memory layer (Priority 3)
    memories = relationship(
        "EventMemory",
        back_populates="event",
        cascade="all, delete-orphan",
        uselist=False,
    )


class UserPreference(Base):
    """User preferences table - private preference profiles."""

    __tablename__ = "user_preferences"

    preference_id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    time_preference = Column(String(50), default="any")
    activity_preference = Column(String(100), default="any")
    budget_preference = Column(String(50), default="any")
    location_type_preference = Column(String(100), default="any")
    transport_preference = Column(String(50), default="any")
    language_preference = Column(String(10), default=None)
    privacy_settings = Column(JSON, default=dict)
    last_updated = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", back_populates="preferences")


class Constraint(Base):
    """Constraints table - conditional participation."""

    __tablename__ = "constraints"

    constraint_id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    target_user_id = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"))
    event_id = Column(
        Integer, ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    type = Column(String(50), nullable=False)
    confidence = Column(Float, default=1.0)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user = relationship("User", back_populates="constraints", foreign_keys=[user_id])
    target_user = relationship(
        "User", back_populates="target_constraints", foreign_keys=[target_user_id]
    )
    event = relationship("Event", back_populates="constraints")


class Log(Base):
    """Logs table - audit trail."""

    __tablename__ = "logs"

    log_id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.event_id", ondelete="SET NULL"))
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"))
    action = Column(String(100), nullable=False)
    timestamp = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    metadata_dict = Column("metadata", JSON, default=dict)

    event = relationship("Event", back_populates="logs")
    user = relationship("User", back_populates="logs")


# ============================================================================
# PRD v2: New Tables for Priority 1 - Structural Foundations
# ============================================================================


class ParticipantStatus(enum.Enum):
    """Participant status enum."""

    joined = "joined"
    confirmed = "confirmed"
    cancelled = "cancelled"
    no_show = "no_show"


class ParticipantRole(enum.Enum):
    """Participant role enum."""

    organizer = "organizer"
    participant = "participant"
    observer = "observer"


class EventParticipant(Base):
    """
    EventParticipant table - Normalized participation tracking.
    PRD v2 Section 2.1: Replaces attendance_list JSON column.
    """

    __tablename__ = "event_participants"

    event_id = Column(
        Integer,
        ForeignKey("events.event_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    telegram_user_id = Column(BigInteger, primary_key=True, nullable=False)
    status = Column(
        SQLEnum(ParticipantStatus, name="participant_status"),
        default=ParticipantStatus.joined,
        nullable=False,
    )
    role = Column(
        SQLEnum(ParticipantRole, name="participant_role"),
        default=ParticipantRole.participant,
        nullable=False,
    )
    joined_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    confirmed_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    source = Column(String(50))  # slash, callback, mention, dm

    event = relationship("Event", back_populates="participants")


class IdempotencyKey(Base):
    """
    IdempotencyKey table - Prevents duplicate command execution.
    PRD v2 Priority 1: Idempotent Command Execution.
    """

    __tablename__ = "idempotency_keys"

    idempotency_key = Column(String(255), primary_key=True)
    command_type = Column(String(100), nullable=False)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    event_id = Column(Integer, ForeignKey("events.event_id"))
    status = Column(String(50), default="pending")  # pending, completed, failed
    response_hash = Column(String(255))
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User")
    event = relationship("Event")


class EventStateTransition(Base):
    """
    EventStateTransition table - Audit trail for state changes.
    PRD v2 Section 2.1: Each transition records actor, timestamp, reason, source.
    """

    __tablename__ = "event_state_transitions"

    transition_id = Column(Integer, primary_key=True)
    event_id = Column(
        Integer, ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    from_state = Column(String(20), nullable=False)
    to_state = Column(String(20), nullable=False)
    actor_telegram_user_id = Column(BigInteger)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    reason = Column(Text)
    source = Column(String(50), nullable=False)  # slash, callback, AI mention

    event = relationship("Event")


class GroupEventTypeStats(Base):
    """
    GroupEventTypeStats table - Group-level coordination pattern tracking.
    PRD v3.2: Used only for the repeated failure pattern surface in meaning-formation.
    No individual user data. No attribution.
    """

    __tablename__ = "group_event_type_stats"

    stat_id = Column(Integer, primary_key=True)
    group_id = Column(
        Integer,
        ForeignKey("groups.group_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(100), nullable=False)
    attempt_count = Column(Integer, default=0, nullable=False)
    completed_count = Column(Integer, default=0, nullable=False)
    last_dropout_point = Column(Integer)  # participant count at last cancellation
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("group_id", "event_type", name="uq_group_event_type_stats"),
    )

    group = relationship("Group")


# ============================================================================
# PRD v2: New Tables for Priority 3 - Layer 3 Memory
# ============================================================================


class EventMemory(Base):
    """
    EventMemory table - Memory Weave storage.
    PRD v2 Section 2.3: Makes events mean something through shared narratives.
    """

    __tablename__ = "event_memories"

    memory_id = Column(Integer, primary_key=True)
    event_id = Column(
        Integer,
        ForeignKey("events.event_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    fragments = Column(JSON, default=list)
    # Each fragment: {text, contributor_hash, submitted_at, word_count}
    hashtags = Column(JSON, default=list)  # 1-3 natural language tags
    outcome_markers = Column(JSON, default=list)  # follow-on events, collaborations
    weave_text = Column(Text)  # Bot-generated weave posted to group
    lineage_event_ids = Column(JSON, default=list)  # References to prior similar events
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    event = relationship("Event", back_populates="memories")


# ============================================================================
# PRD v2: Waitlist Support (TODO-023)
# ============================================================================


class EventWaitlist(Base):
    """
    EventWaitlist table - Waitlist for oversubscribed events.
    PRD v2 Section 4.3: Waitlist support for Priority 3.

    When events reach capacity, users can join waitlist.
    Automatic promotion when confirmed participants cancel.
    """

    __tablename__ = "event_waitlist"

    waitlist_id = Column(Integer, primary_key=True)
    event_id = Column(
        Integer, ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    telegram_user_id = Column(BigInteger, nullable=False)
    # Legacy compatibility field. Active v3.2 ordering is by added_at only.
    position = Column(Integer, nullable=True)
    added_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True))  # When waitlist offer expires
    status = Column(
        String(20), default="waiting", nullable=False
    )  # waiting, offered, promoted, expired, cancelled

    __table_args__ = (
        UniqueConstraint("event_id", "telegram_user_id", name="uq_waitlist_event_user"),
    )

    event = relationship("Event", back_populates="waitlist")


# Add back-populates to Event model for waitlist
# (This needs to be added to the Event class definition)
Event.waitlist = relationship(
    "EventWaitlist",
    back_populates="event",
    cascade="all, delete-orphan",
    order_by="EventWaitlist.added_at",
)


# ============================================================================
# PRD v3.5: New Tables for Event Enrichments, Lineage, Live Cards, Group Settings
# ============================================================================


class EventEnrichment(Base):
    """
    EventEnrichment table - Member contributions during event formation.
    PRD v3.5 Section 2.3: Stores ideas, hashtags, and memories.

    All member-contributed content goes here. Organizer-level draft storage
    stays in planning_prefs. This boundary prevents the JSON blob from growing.
    """

    __tablename__ = "event_enrichments"

    enrichment_id = Column(BigInteger, primary_key=True)
    event_id = Column(
        BigInteger, ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    telegram_user_id = Column(BigInteger, nullable=False)
    enrichment_type = Column(
        String(30), nullable=False
    )  # 'idea' | 'hashtag' | 'memory'
    content = Column(Text, nullable=False)
    is_public = Column(Boolean, default=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    event = relationship("Event", back_populates="enrichments")


class EventLineage(Base):
    """
    EventLineage table - Parent-child relationships between events.
    PRD v3.5 Section 2.4: Tracks lineage for memory-first coordination.

    When a new event is created of the same type as a prior completed event
    in the same group, a lineage row is written linking them.
    """

    __tablename__ = "event_lineage"

    parent_event_id = Column(
        BigInteger, ForeignKey("events.event_id", ondelete="CASCADE"), primary_key=True
    )
    child_event_id = Column(
        BigInteger, ForeignKey("events.event_id", ondelete="CASCADE"), primary_key=True
    )
    relation_type = Column(String(30), default="same_type")
    linked_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EventLiveCard(Base):
    """
    EventLiveCard table - Tracks live card messages posted to group chats.
    PRD v3.5 Section 4.2: Makes events visible and alive during formation.

    The live card is the primary surface for gravity signals.
    """

    __tablename__ = "event_live_cards"

    id = Column(BigInteger, primary_key=True)
    event_id = Column(
        BigInteger,
        ForeignKey("events.event_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    message_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    participant_count = Column(Integer, default=0)
    confirmed_count = Column(Integer, default=0)
    reaction_counts = Column(JSON, default=dict)
    last_updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class GroupSettings(Base):
    """
    GroupSettings table - Per-group configuration.
    PRD v3.5 Section 2.6: Store timezone, live card settings, etc.

    Solves the timezone UX gap and enables group-level customization.
    """

    __tablename__ = "group_settings"

    group_id = Column(
        Integer, ForeignKey("groups.group_id", ondelete="CASCADE"), primary_key=True
    )
    enable_live_cards = Column(Boolean, default=True)
    group_timezone = Column(String(50), default="UTC")
    max_hashtags_per_event = Column(Integer, default=5)
    lineage_selection_method = Column(String(10), default="fixed")
    # 'fixed' = most recent fragment | 'llm' = context-aware
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# Add back-populates to Event model for enrichments
Event.enrichments = relationship(
    "EventEnrichment",
    back_populates="event",
    cascade="all, delete-orphan",
    order_by="EventEnrichment.created_at",
)

# Add back-populates to Event model for lineage
Event.lineage_as_parent = relationship(
    "EventLineage",
    foreign_keys="EventLineage.parent_event_id",
    cascade="all, delete-orphan",
)
Event.lineage_as_child = relationship(
    "EventLineage",
    foreign_keys="EventLineage.child_event_id",
    cascade="all, delete-orphan",
)
