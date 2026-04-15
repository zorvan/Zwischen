"""
End-to-end tests to catch database schema mismatches.
"""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
import pytest

from db.models import Base, Event, EventLiveCard, GroupSettings, EventMemory


@pytest.mark.asyncio
async def test_event_model_has_all_columns():
    """Test that Event model has all required columns including hashtag fields."""
    columns = [col.key for col in Event.__table__.columns]

    assert "event_id" in columns
    assert "group_id" in columns
    assert "event_type" in columns
    assert "description" in columns
    assert "formation_hashtag" in columns, (
        "Event model missing formation_hashtag column"
    )
    assert "locked_hashtag" in columns, "Event model missing locked_hashtag column"
    assert "mosaic_message_id" in columns, (
        "Event model missing mosaic_message_id column"
    )


def test_event_lifecycle_with_hashtags():
    """End-to-end test: create event and verify hashtag columns exist in DB."""
    engine = create_engine("sqlite:///:memory:", future=True)
    try:
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        try:
            event = Event(
                group_id=1,
                event_type="sports",
                description="Football match",
                scheduled_time=None,
                formation_hashtag=["#football", "#weekend"],
                locked_hashtag=["#confirmed"],
                mosaic_message_id=12345,
            )
            session.add(event)
            session.commit()

            db_event = session.query(Event).filter_by(event_id=event.event_id).first()
            assert db_event.formation_hashtag == ["#football", "#weekend"]
            assert db_event.locked_hashtag == ["#confirmed"]
            assert db_event.mosaic_message_id == 12345
        finally:
            session.close()
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_all_models_have_columns():
    """Verify all models have their expected columns defined in class, not dynamically."""
    from sqlalchemy.inspection import inspect

    models_to_check = [Event, EventLiveCard, GroupSettings, EventMemory]

    for model in models_to_check:
        mapper = inspect(model)
        for attr in mapper.attrs:
            if hasattr(attr, "columns"):
                for col in attr.columns:
                    assert col.table.name == model.__tablename__, (
                        f"{model.__name__}.{attr.key} references wrong table"
                    )


@pytest.mark.asyncio
async def test_database_schema_matches_model():
    """Test that the actual database schema matches the SQLAlchemy model definition."""
    from sqlalchemy import MetaData

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

        assert expected_columns.issubset(event_columns), (
            f"Database missing columns: {expected_columns - event_columns}"
        )
    finally:
        engine.dispose()
