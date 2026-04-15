"""
End-to-end integration tests for the Event model lifecycle.
Catches database schema mismatches and ensures all columns work correctly.
"""

from datetime import datetime

import pytest

from db.models import (
    Base,
    Event,
    EventLiveCard,
    GroupSettings,
    EventMemory,
    EventWaitlist,
    EventParticipant,
    ParticipantStatus,
)


@pytest.mark.asyncio
async def test_event_full_lifecycle_with_hashtags():
    """Test complete event lifecycle with hashtag columns."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=1,
                event_type="sports",
                description="Football match this Friday",
                scheduled_time=datetime(2026, 4, 18, 18, 0, 0),
                duration_minutes=120,
                min_participants=2,
                target_participants=6,
                state="proposed",
                formation_hashtag=["#football", "#friday"],
                locked_hashtag=[],
                mosaic_message_id=None,
            )
            session.add(event)
            session.commit()

            assert event.event_id is not None

            event.state = "interested"
            session.commit()

            event.state = "confirmed"
            event.locked_at = datetime.utcnow()
            event.locked_hashtag = ["#confirmed"]
            session.commit()

            event.state = "locked"
            event.mosaic_message_id = 12345
            session.commit()

            db_event = session.query(Event).filter_by(event_id=event.event_id).first()
            assert db_event.formation_hashtag == ["#football", "#friday"]
            assert db_event.locked_hashtag == ["#confirmed"]
            assert db_event.mosaic_message_id == 12345

        finally:
            session.close()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_event_live_card_creation():
    """Test EventLiveCard creation and relationships."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=1,
                event_type="sports",
                description="Test event",
                state="proposed",
            )
            session.add(event)
            session.commit()

            live_card = EventLiveCard(
                event_id=event.event_id,
                message_id=98765,
                chat_id=-100123456789,
                participant_count=3,
                confirmed_count=2,
                reaction_counts={"✅": 2, "❌": 1},
                hashtags=["#sports", "#test"],
            )
            session.add(live_card)
            session.commit()

            db_event = session.query(Event).filter_by(event_id=event.event_id).first()
            assert db_event.live_card is not None
            assert db_event.live_card.message_id == 98765

        finally:
            session.close()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_group_settings_creation():
    """Test GroupSettings creation and relationships."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            group = GroupSettings(
                group_id=1,
                enable_live_cards=1,
                memory_first_skip_enabled=0,
                lineage_selection_method="llm",
                max_hashtags=5,
            )
            session.add(group)
            session.commit()

            db_settings = session.query(GroupSettings).filter_by(group_id=1).first()
            assert db_settings is not None
            assert db_settings.enable_live_cards == 1
            assert db_settings.max_hashtags == 5

        finally:
            session.close()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_event_memory_with_lineage():
    """Test EventMemory with lineage fields."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=1,
                event_type="sports",
                description="Test event",
                state="completed",
            )
            session.add(event)
            session.commit()

            memory = EventMemory(
                event_id=event.event_id,
                fragments=[{"text": "Great match!", "contributor_hash": "abc123"}],
                hashtags=["#football", "#fun"],
                outcome_markers=["#next_week", "#tournament"],
                weave_text="This was an awesome football match!",
                lineage_event_ids=[1, 2, 3],
                is_lineage_door=1,
                selected_at=datetime.utcnow(),
            )
            session.add(memory)
            session.commit()

            db_memory = (
                session.query(EventMemory).filter_by(event_id=event.event_id).first()
            )
            assert db_memory is not None
            assert db_memory.is_lineage_door == 1
            assert db_memory.lineage_event_ids == [1, 2, 3]

        finally:
            session.close()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_event_participant_with_status():
    """Test EventParticipant with various statuses."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=1,
                event_type="sports",
                description="Test event",
                state="confirmed",
            )
            session.add(event)
            session.commit()

            participant = EventParticipant(
                event_id=event.event_id,
                telegram_user_id=123456789,
                status=ParticipantStatus.confirmed,
                role="participant",
                source="callback",
            )
            session.add(participant)
            session.commit()

            db_event = session.query(Event).filter_by(event_id=event.event_id).first()
            assert len(db_event.participants) == 1
            assert db_event.participants[0].status.value == "confirmed"

        finally:
            session.close()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_event_waitlist():
    """Test EventWaitlist functionality."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=1,
                event_type="sports",
                description="Test event",
                state="confirmed",
            )
            session.add(event)
            session.commit()

            waitlist_entry = EventWaitlist(
                event_id=event.event_id,
                telegram_user_id=999888777,
                status="waiting",
                added_at=datetime.utcnow(),
            )
            session.add(waitlist_entry)
            session.commit()

            db_event = session.query(Event).filter_by(event_id=event.event_id).first()
            assert len(db_event.waitlist) == 1
            assert db_event.waitlist[0].status == "waiting"

        finally:
            session.close()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_database_schema_columns():
    """Verify database schema has all expected columns from model."""
    from sqlalchemy import create_engine, MetaData

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)

        metadata = MetaData()
        metadata.reflect(bind=engine)

        events_table = metadata.tables["events"]
        event_columns = {col.name for col in events_table.columns}

        expected_columns = {
            "event_id",
            "group_id",
            "event_type",
            "description",
            "formation_hashtag",
            "locked_hashtag",
            "mosaic_message_id",
        }

        missing = expected_columns - event_columns
        assert not missing, f"Database missing columns: {missing}"

    finally:
        engine.dispose()
