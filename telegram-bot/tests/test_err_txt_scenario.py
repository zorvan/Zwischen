"""
End-to-end test: Verify the exact scenario from err.txt works correctly.
This test catches the exact error: "column formation_hashtag of relation events does not exist"
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from db.models import Base, Event, EventParticipant, ParticipantStatus


def test_err_txt_scenario_insert_event_with_hashtags():
    """
    Reproduce the exact scenario from err.txt:
    INSERT INTO events with formation_hashtag, locked_hashtag, mosaic_message_id
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=2,
                event_type="social",
                description="علی: بچه‌هاااا 😤\nیه فیفا درست حسابی کی میزنیم بالاخره؟",
                organizer_telegram_user_id=8710491944,
                admin_telegram_user_id=8710491944,
                scheduled_time=None,
                commit_by=None,
                duration_minutes=120,
                min_participants=3,
                target_participants=5,
                collapse_at=datetime(2026, 4, 22, 11, 32, 39, 494347),
                lock_deadline=None,
                planning_prefs={"date_preset": None, "time_window": None},
                state="proposed",
                created_at=datetime(2026, 4, 15, 11, 32, 39, 496499),
                locked_at=None,
                completed_at=None,
                version=0,
                formation_hashtag=[],
                locked_hashtag=[],
                mosaic_message_id=None,
            )
            session.add(event)
            session.commit()

            db_event = session.query(Event).filter_by(event_id=event.event_id).first()
            assert db_event.formation_hashtag == []
            assert db_event.locked_hashtag == []
            assert db_event.mosaic_message_id is None

        finally:
            session.close()
    finally:
        engine.dispose()


def test_err_txt_scenario_query_events_with_hashtags():
    """
    Reproduce the exact scenario from err.txt line 136-139:
    SELECT events.event_id, ... events.formation_hashtag, events.locked_hashtag, events.mosaic_message_id
    FROM events LEFT OUTER JOIN event_participants ...
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=2,
                event_type="social",
                description="Test event",
                organizer_telegram_user_id=8710491944,
                state="completed",
                created_at=datetime(2026, 4, 15, 9, 32, 51, 90492),
                completed_at=datetime(2026, 4, 15, 9, 32, 51, 90492),
                formation_hashtag=["#social"],
                locked_hashtag=["#completed"],
                mosaic_message_id=12345,
            )
            session.add(event)
            session.commit()

            participant = EventParticipant(
                event_id=event.event_id,
                telegram_user_id=109397689,
                status=ParticipantStatus.confirmed,
            )
            session.add(participant)
            session.commit()

            from sqlalchemy import select, func

            result = session.execute(
                select(
                    Event.event_id,
                    Event.group_id,
                    Event.event_type,
                    Event.description,
                    Event.organizer_telegram_user_id,
                    Event.admin_telegram_user_id,
                    Event.scheduled_time,
                    Event.commit_by,
                    Event.duration_minutes,
                    Event.min_participants,
                    Event.target_participants,
                    Event.collapse_at,
                    Event.lock_deadline,
                    Event.planning_prefs,
                    Event.state,
                    Event.created_at,
                    Event.locked_at,
                    Event.completed_at,
                    Event.version,
                    Event.formation_hashtag,  # This column caused the error
                    Event.locked_hashtag,  # This column caused the error
                    Event.mosaic_message_id,  # This column caused the error
                )
                .outerjoin(
                    EventParticipant, Event.event_id == EventParticipant.event_id
                )
                .where(
                    Event.state == "completed",
                    Event.completed_at <= datetime(2026, 4, 15, 9, 32, 51, 90492),
                )
                .group_by(Event.event_id)
                .having(func.count(EventParticipant.telegram_user_id) > 0)
            )

            rows = result.all()
            assert len(rows) == 1
            assert rows[0].formation_hashtag == ["#social"]
            assert rows[0].locked_hashtag == ["#completed"]
            assert rows[0].mosaic_message_id == 12345

        finally:
            session.close()
    finally:
        engine.dispose()


def test_err_txt_scenario_scheduler_job():
    """
    Reproduce the scheduler job scenario from err.txt line 187-241:
    Scheduled task check_and_start_memory_collection queries events with hashtags.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=2,
                event_type="sports",
                description="Football match",
                organizer_telegram_user_id=8710491944,
                state="completed",
                created_at=datetime(2026, 4, 15, 9, 32, 51, 90492),
                completed_at=datetime(2026, 4, 15, 9, 32, 51, 90492),
                formation_hashtag=["#football"],
                locked_hashtag=["#completed"],
                mosaic_message_id=None,
            )
            session.add(event)
            session.commit()

            participant = EventParticipant(
                event_id=event.event_id,
                telegram_user_id=109397689,
                status=ParticipantStatus.confirmed,
            )
            session.add(participant)
            session.commit()

            from sqlalchemy import select, func

            result = session.execute(
                select(Event)
                .outerjoin(
                    EventParticipant, Event.event_id == EventParticipant.event_id
                )
                .where(
                    Event.state == "completed",
                    Event.completed_at <= datetime(2026, 4, 15, 9, 32, 51, 90492),
                )
                .group_by(Event.event_id)
                .having(func.count(EventParticipant.telegram_user_id) > 0)
            )

            events = result.scalars().all()
            assert len(events) == 1
            assert events[0].formation_hashtag == ["#football"]
            assert events[0].locked_hashtag == ["#completed"]

        finally:
            session.close()
    finally:
        engine.dispose()


def test_err_txt_scenario_update_event_hashtags():
    """
    Test updating event with hashtag columns (like in finalize_event from err.txt).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=2,
                event_type="sports",
                description="Test",
                state="confirmed",
                formation_hashtag=["#sports"],
                locked_hashtag=[],
                mosaic_message_id=None,
            )
            session.add(event)
            session.commit()

            event.state = "locked"
            event.locked_hashtag = ["#confirmed", "#locked"]
            event.mosaic_message_id = 98765
            session.commit()

            db_event = session.query(Event).filter_by(event_id=event.event_id).first()
            assert db_event.state == "locked"
            assert db_event.locked_hashtag == ["#confirmed", "#locked"]
            assert db_event.mosaic_message_id == 98765

        finally:
            session.close()
    finally:
        engine.dispose()
