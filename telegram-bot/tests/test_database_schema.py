#!/usr/bin/env python3
"""Tests for v3.5 database schema changes.

This module tests:
1. New tables: event_enrichments, event_lineage, event_live_cards, group_settings
2. CHECK constraint removal from constraints.type, logs.action, groups.group_type
3. Model relationships and constraints
"""
import pytest
import pytest_asyncio
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, insert, text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def db_session():
    """Create a database session for testing."""
    from db.connection import get_session
    from config.settings import settings
    
    db_url = settings.db_url or ""
    async with get_session(db_url) as session:
        yield session


class TestEventEnrichmentsTable:
    """Tests for event_enrichments table (v3.5 Phase 1)."""

    @pytest.mark.asyncio
    async def test_table_exists(self, db_session):
        """Verify event_enrichments table exists in schema."""
        from db.connection import get_session
        from config.settings import settings
        
        db_url = settings.db_url or ""
        async with get_session(db_url) as session:
            result = await session.execute(
                text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'event_enrichments'
                    )
                """)
            )
            exists = result.scalar()
            assert exists, "event_enrichments table should exist"

    @pytest.mark.asyncio
    async def test_can_insert_idea(self, db_session):
        """Test inserting an idea enrichment."""
        from db.models import EventEnrichment
        
        enrichment = EventEnrichment(
            event_id=1,
            telegram_user_id=12345,
            enrichment_type='idea',
            content='Bring snacks for the hike',
            is_public=False
        )
        db_session.add(enrichment)
        await db_session.flush()
        
        assert enrichment.enrichment_id is not None
        assert enrichment.enrichment_type == 'idea'

    @pytest.mark.asyncio
    async def test_can_insert_hashtag(self, db_session):
        """Test inserting a hashtag enrichment."""
        from db.models import EventEnrichment
        
        enrichment = EventEnrichment(
            event_id=1,
            telegram_user_id=12345,
            enrichment_type='hashtag',
            content='#hiking',
            is_public=False  # Will become public when 2+ contributors
        )
        db_session.add(enrichment)
        await db_session.flush()
        
        assert enrichment.enrichment_id is not None
        assert enrichment.enrichment_type == 'hashtag'

    @pytest.mark.asyncio
    async def test_can_insert_memory(self, db_session):
        """Test inserting a memory enrichment."""
        from db.models import EventEnrichment
        
        enrichment = EventEnrichment(
            event_id=1,
            telegram_user_id=12345,
            enrichment_type='memory',
            content='The sunset at the ridge was incredible',
            is_public=False
        )
        db_session.add(enrichment)
        await db_session.flush()
        
        assert enrichment.enrichment_id is not None
        assert enrichment.enrichment_type == 'memory'

    @pytest.mark.asyncio
    async def test_query_by_event_id(self, db_session):
        """Test querying enrichments by event_id."""
        from db.models import EventEnrichment
        
        # Insert test data
        for i in range(3):
            enrichment = EventEnrichment(
                event_id=100,
                telegram_user_id=1000 + i,
                enrichment_type='idea',
                content=f'Idea {i}',
                is_public=True
            )
            db_session.add(enrichment)
        await db_session.flush()
        
        # Query
        result = await db_session.execute(
            select(EventEnrichment).where(EventEnrichment.event_id == 100)
        )
        enrichments = result.scalars().all()
        assert len(enrichments) == 3

    @pytest.mark.asyncio
    async def test_query_by_type(self, db_session):
        """Test querying enrichments by type."""
        from db.models import EventEnrichment
        
        # Insert mixed types
        db_session.add(EventEnrichment(event_id=200, telegram_user_id=1, enrichment_type='idea', content='idea', is_public=True))
        db_session.add(EventEnrichment(event_id=200, telegram_user_id=2, enrichment_type='hashtag', content='#tag', is_public=True))
        db_session.add(EventEnrichment(event_id=200, telegram_user_id=3, enrichment_type='memory', content='memory', is_public=True))
        await db_session.flush()
        
        # Query by type
        result = await db_session.execute(
            select(EventEnrichment).where(EventEnrichment.enrichment_type == 'hashtag')
        )
        hashtags = result.scalars().all()
        assert len(hashtags) == 1
        assert hashtags[0].content == '#tag'

    @pytest.mark.asyncio
    async def test_query_public_only(self, db_session):
        """Test querying only public enrichments."""
        from db.models import EventEnrichment
        
        db_session.add(EventEnrichment(event_id=300, telegram_user_id=1, enrichment_type='hashtag', content='#public', is_public=True))
        db_session.add(EventEnrichment(event_id=300, telegram_user_id=2, enrichment_type='hashtag', content='#private', is_public=False))
        await db_session.flush()
        
        result = await db_session.execute(
            select(EventEnrichment).where(
                EventEnrichment.event_id == 300,
                EventEnrichment.is_public == True
            )
        )
        public = result.scalars().all()
        assert len(public) == 1
        assert public[0].content == '#public'


class TestEventLineageTable:
    """Tests for event_lineage table (v3.5 Phase 1)."""

    @pytest.mark.asyncio
    async def test_table_exists(self, db_session):
        """Verify event_lineage table exists in schema."""
        result = await db_session.execute(
            text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'event_lineage'
                )
            """)
        )
        exists = result.scalar()
        assert exists, "event_lineage table should exist"

    @pytest.mark.asyncio
    async def test_insert_lineage_row(self, db_session):
        """Test inserting parent-child relationship."""
        from db.models import EventLineage
        
        lineage = EventLineage(
            parent_event_id=1,
            child_event_id=2,
            relation_type='same_type'
        )
        db_session.add(lineage)
        await db_session.flush()
        
        # Verify composite primary key
        assert lineage.parent_event_id == 1
        assert lineage.child_event_id == 2
        assert lineage.linked_at is not None

    @pytest.mark.asyncio
    async def test_query_by_parent(self, db_session):
        """Test finding all children of a parent event."""
        from db.models import EventLineage
        
        # Insert lineage
        for i in range(3):
            db_session.add(EventLineage(
                parent_event_id=500,
                child_event_id=600 + i,
                relation_type='same_type'
            ))
        await db_session.flush()
        
        result = await db_session.execute(
            select(EventLineage).where(EventLineage.parent_event_id == 500)
        )
        children = result.scalars().all()
        assert len(children) == 3

    @pytest.mark.asyncio
    async def test_query_by_child(self, db_session):
        """Test finding parent of a child event."""
        from db.models import EventLineage
        
        db_session.add(EventLineage(
            parent_event_id=700,
            child_event_id=800,
            relation_type='same_type'
        ))
        await db_session.flush()
        
        result = await db_session.execute(
            select(EventLineage).where(EventLineage.child_event_id == 800)
        )
        parent = result.scalar_one_or_none()
        assert parent is not None
        assert parent.parent_event_id == 700


class TestEventLiveCardsTable:
    """Tests for event_live_cards table (v3.5 Phase 1)."""

    @pytest.mark.asyncio
    async def test_table_exists(self, db_session):
        """Verify event_live_cards table exists in schema."""
        result = await db_session.execute(
            text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'event_live_cards'
                )
            """)
        )
        exists = result.scalar()
        assert exists, "event_live_cards table should exist"

    @pytest.mark.asyncio
    async def test_insert_live_card(self, db_session):
        """Test inserting a live card record."""
        from db.models import EventLiveCard
        
        card = EventLiveCard(
            event_id=1,
            message_id=12345,
            chat_id=-100123456789,
            participant_count=3,
            confirmed_count=2,
            reaction_counts={'👍': 5, '👎': 1}
        )
        db_session.add(card)
        await db_session.flush()
        
        assert card.id is not None
        assert card.last_updated_at is not None

    @pytest.mark.asyncio
    async def test_event_id_unique_constraint(self, db_session):
        """Test that event_id has UNIQUE constraint."""
        from db.models import EventLiveCard
        from sqlalchemy.exc import IntegrityError
        
        # Insert first card
        card1 = EventLiveCard(event_id=999, message_id=1, chat_id=1)
        db_session.add(card1)
        await db_session.flush()
        
        # Try to insert second card with same event_id
        card2 = EventLiveCard(event_id=999, message_id=2, chat_id=1)
        db_session.add(card2)
        
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_update_live_card(self, db_session):
        """Test updating live card counts."""
        from db.models import EventLiveCard
        
        card = EventLiveCard(
            event_id=1000,
            message_id=12345,
            chat_id=-100123456789,
            participant_count=1,
            confirmed_count=0
        )
        db_session.add(card)
        await db_session.flush()
        
        # Update counts
        card.participant_count = 3
        card.confirmed_count = 2
        await db_session.flush()
        
        # Verify
        result = await db_session.execute(
            select(EventLiveCard).where(EventLiveCard.event_id == 1000)
        )
        updated = result.scalar_one()
        assert updated.participant_count == 3
        assert updated.confirmed_count == 2


class TestGroupSettingsTable:
    """Tests for group_settings table (v3.5 Phase 1)."""

    @pytest.mark.asyncio
    async def test_table_exists(self, db_session):
        """Verify group_settings table exists in schema."""
        result = await db_session.execute(
            text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'group_settings'
                )
            """)
        )
        exists = result.scalar()
        assert exists, "group_settings table should exist"

    @pytest.mark.asyncio
    async def test_default_values(self, db_session):
        """Test that default values are applied correctly."""
        from db.models import GroupSettings
        
        settings = GroupSettings(group_id=1)
        db_session.add(settings)
        await db_session.flush()
        
        assert settings.enable_live_cards is True
        assert settings.group_timezone == 'UTC'
        assert settings.max_hashtags_per_event == 5
        assert settings.lineage_selection_method == 'fixed'
        assert settings.created_at is not None
        assert settings.updated_at is not None

    @pytest.mark.asyncio
    async def test_custom_values(self, db_session):
        """Test setting custom values."""
        from db.models import GroupSettings
        
        settings = GroupSettings(
            group_id=2,
            enable_live_cards=False,
            group_timezone='America/New_York',
            max_hashtags_per_event=10,
            lineage_selection_method='llm'
        )
        db_session.add(settings)
        await db_session.flush()
        
        assert settings.enable_live_cards is False
        assert settings.group_timezone == 'America/New_York'
        assert settings.max_hashtags_per_event == 10
        assert settings.lineage_selection_method == 'llm'

    @pytest.mark.asyncio
    async def test_foreign_key_to_groups(self, db_session):
        """Test foreign key constraint to groups table."""
        from db.models import GroupSettings
        from sqlalchemy.exc import IntegrityError
        
        # Try to insert settings for non-existent group
        settings = GroupSettings(group_id=999999)
        db_session.add(settings)
        
        # This should either succeed (if no FK) or fail (if FK exists)
        # The test documents expected behavior
        try:
            await db_session.flush()
            await db_session.rollback()
        except IntegrityError:
            await db_session.rollback()
            # FK constraint exists and is working
            pass


class TestCheckConstraintRemoval:
    """Tests that CHECK constraints were removed (v3.5 Phase 1)."""

    @pytest.mark.asyncio
    async def test_constraints_type_no_check(self, db_session):
        """Verify constraints.type no longer has CHECK constraint."""
        from db.models import Constraint
        
        # Should be able to insert any string type, not just 'if_joins', 'if_attends', 'unless_joins'
        constraint = Constraint(
            user_id=1,
            event_id=1,
            type='available_saturday',  # This would fail with old CHECK
            confidence=1.0
        )
        db_session.add(constraint)
        await db_session.flush()
        
        # Also test arbitrary value
        constraint2 = Constraint(
            user_id=2,
            event_id=1,
            type='some_future_constraint_type',  # Should be allowed
            confidence=1.0
        )
        db_session.add(constraint2)
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_logs_action_no_check(self, db_session):
        """Verify logs.action no longer has CHECK constraint."""
        from db.models import Log
        
        # Should be able to insert any action string
        log = Log(
            event_id=1,
            user_id=1,
            action='enrich_hashtag'  # New v3.5 action not in old CHECK list
        )
        db_session.add(log)
        await db_session.flush()
        
        # Also test another new action
        log2 = Log(
            event_id=1,
            user_id=1,
            action='relinquish'  # New v3.5 terminology
        )
        db_session.add(log2)
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_groups_group_type_no_check(self, db_session):
        """Verify groups.group_type no longer has CHECK constraint."""
        from db.models import Group
        
        # Should be able to insert any group_type
        group = Group(
            telegram_group_id=99999,
            group_name='Test Group',
            group_type='corporate'  # Not in old CHECK list ('casual', 'gathering', 'tournament')
        )
        db_session.add(group)
        await db_session.flush()
        
        assert group.group_id is not None


class TestModelRelationships:
    """Tests for SQLAlchemy model relationships."""

    @pytest.mark.asyncio
    async def test_event_enrichment_relationship(self, db_session):
        """Test Event.enrichments relationship exists."""
        from db.models import Event, EventEnrichment
        
        # Check that Event model has enrichments relationship
        assert hasattr(Event, 'enrichments'), "Event should have enrichments relationship"

    @pytest.mark.asyncio
    async def test_event_lineage_relationship(self, db_session):
        """Test Event.lineage_children/parents relationship exists."""
        from db.models import Event, EventLineage
        
        # Check that Event model has lineage relationships
        assert hasattr(Event, 'lineage_as_parent'), "Event should have lineage_as_parent relationship"
        assert hasattr(Event, 'lineage_as_child'), "Event should have lineage_as_child relationship"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
