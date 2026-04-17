"""
End-to-end tests to catch database schema mismatches.
"""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
import pytest

from db.models import Base, Event, EventLiveCard, GroupSettings, EventMemory


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
        # Drop all tables first to ensure clean slate
        Base.metadata.drop_all(engine)
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
        }

        assert expected_columns.issubset(event_columns), (
            f"Database missing columns: {expected_columns - event_columns}"
        )
    finally:
        engine.dispose()
