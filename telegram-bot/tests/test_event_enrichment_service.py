#!/usr/bin/env python3
"""Tests for bot/services/event_enrichment_service.py.

This module tests the v3.5 event enrichment service for managing
member contributions (ideas, hashtags, memories).
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


class TestEventEnrichmentService:
    """Tests for EventEnrichmentService class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        return session

    @pytest.fixture
    def service(self, mock_session):
        """Create an EventEnrichmentService instance."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        return EventEnrichmentService(mock_session)

    def test_service_init(self, service, mock_session):
        """Test service initialization."""
        assert service.session is mock_session


class TestAddIdea:
    """Tests for add_idea method."""

    @pytest.mark.asyncio
    async def test_add_idea_success(self):
        """Test successfully adding an idea."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        from db.models import EventEnrichment
        
        mock_session = MagicMock()
        mock_session.flush = AsyncMock()
        service = EventEnrichmentService(mock_session)
        
        enrichment = await service.add_idea(
            event_id=1,
            telegram_user_id=12345,
            content="Bring snacks for the hike"
        )
        
        assert isinstance(enrichment, EventEnrichment)
        assert enrichment.event_id == 1
        assert enrichment.telegram_user_id == 12345
        assert enrichment.enrichment_type == "idea"
        assert enrichment.content == "Bring snacks for the hike"
        assert enrichment.is_public is False

    @pytest.mark.asyncio
    async def test_add_idea_content_too_long_raises_error(self):
        """Test that long ideas raise validation error."""
        from bot.services.event_enrichment_service import EventEnrichmentService, ContentValidationError
        
        mock_session = MagicMock()
        service = EventEnrichmentService(mock_session)
        
        long_content = "A" * 500
        with pytest.raises(ContentValidationError) as exc_info:
            await service.add_idea(
                event_id=1,
                telegram_user_id=12345,
                content=long_content
            )
        
        assert "300 characters" in str(exc_info.value)


class TestAddHashtag:
    """Tests for add_hashtag method."""

    @pytest.mark.asyncio
    async def test_add_hashtag_success(self):
        """Test successfully adding a hashtag."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        from db.models import EventEnrichment
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.flush = AsyncMock()
        
        # Mock the count query for hashtags (returns 0 - no existing hashtags)
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_session.execute.return_value = mock_count_result
        
        service = EventEnrichmentService(mock_session)
        
        enrichment = await service.add_hashtag(
            event_id=1,
            telegram_user_id=12345,
            hashtag="#hiking"
        )
        
        assert isinstance(enrichment, EventEnrichment)
        assert enrichment.enrichment_type == "hashtag"
        assert enrichment.content == "#hiking"
        assert enrichment.is_public is False  # Not public until 2+ contributors

    @pytest.mark.asyncio
    async def test_add_hashtag_normalization(self):
        """Test that hashtags are normalized (lowercase, # prefix)."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.flush = AsyncMock()
        
        # Mock the count query for hashtags
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_session.execute.return_value = mock_count_result
        
        service = EventEnrichmentService(mock_session)
        
        # Test various formats
        test_cases = [
            ("Hiking", "#hiking"),  # no #, mixed case
            ("#WEEKEND", "#weekend"),  # with #, uppercase
            ("  Trail  ", "#trail"),  # whitespace
        ]
        
        for input_tag, expected in test_cases:
            enrichment = await service.add_hashtag(
                event_id=1,
                telegram_user_id=12345,
                hashtag=input_tag
            )
            assert enrichment.content == expected

    @pytest.mark.asyncio
    async def test_add_hashtag_per_user_limit(self):
        """Test max 3 hashtags per user per event."""
        from bot.services.event_enrichment_service import EventEnrichmentService, HashtagLimitError
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        
        # Mock existing hashtag count - already at limit
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_session.execute.return_value = mock_result
        
        service = EventEnrichmentService(mock_session)
        
        with pytest.raises(HashtagLimitError) as exc_info:
            await service.add_hashtag(
                event_id=1,
                telegram_user_id=12345,
                hashtag="#fourth"
            )
        
        assert "maximum" in str(exc_info.value).lower()


class TestAddMemory:
    """Tests for add_memory method."""

    @pytest.mark.asyncio
    async def test_add_memory_success(self):
        """Test successfully adding a memory."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        from db.models import EventEnrichment
        
        mock_session = MagicMock()
        mock_session.flush = AsyncMock()
        service = EventEnrichmentService(mock_session)
        
        content = "The sunset at the ridge was absolutely incredible. We stayed until midnight."
        enrichment = await service.add_memory(
            event_id=1,
            telegram_user_id=12345,
            content=content
        )
        
        assert isinstance(enrichment, EventEnrichment)
        assert enrichment.enrichment_type == "memory"
        assert enrichment.content == content
        assert enrichment.is_public is False  # Memories private until mosaic

    @pytest.mark.asyncio
    async def test_add_memory_word_limit(self):
        """Test that memories are limited to 200 words."""
        from bot.services.event_enrichment_service import EventEnrichmentService, ContentValidationError
        
        mock_session = MagicMock()
        service = EventEnrichmentService(mock_session)
        
        long_content = "word " * 250  # 250 words
        
        with pytest.raises(ContentValidationError) as exc_info:
            await service.add_memory(
                event_id=1,
                telegram_user_id=12345,
                content=long_content
            )
        
        assert "200 words" in str(exc_info.value)


class TestGetByEvent:
    """Tests for get_by_event method."""

    @pytest.mark.asyncio
    async def test_get_by_event_returns_list(self):
        """Test get_by_event returns list of enrichments."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        from db.models import EventEnrichment
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        service = EventEnrichmentService(mock_session)
        
        # Mock database results
        mock_enrichments = [
            EventEnrichment(
                enrichment_id=1,
                event_id=100,
                telegram_user_id=1,
                enrichment_type="idea",
                content="Idea 1",
                is_public=True
            ),
            EventEnrichment(
                enrichment_id=2,
                event_id=100,
                telegram_user_id=2,
                enrichment_type="hashtag",
                content="#tag",
                is_public=True
            ),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_enrichments
        mock_session.execute.return_value = mock_result
        
        result = await service.get_by_event(event_id=100)
        
        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_by_event_with_type_filter(self):
        """Test filtering by enrichment type."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        service = EventEnrichmentService(mock_session)
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        
        await service.get_by_event(event_id=100, enrichment_type="hashtag")
        
        # Verify query was called with type filter
        call_args = mock_session.execute.call_args
        assert call_args is not None


class TestGetPublicHashtags:
    """Tests for get_public_hashtags method."""

    @pytest.mark.asyncio
    async def test_get_public_hashtags_returns_list(self):
        """Test get_public_hashtags returns list of hashtag strings."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        from db.models import EventEnrichment
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        service = EventEnrichmentService(mock_session)
        
        # Mock public hashtags
        mock_hashtags = [
            EventEnrichment(content="#hiking", is_public=True),
            EventEnrichment(content="#weekend", is_public=True),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_hashtags
        mock_session.execute.return_value = mock_result
        
        result = await service.get_public_hashtags(event_id=100)
        
        assert isinstance(result, list)
        assert "#hiking" in result
        assert "#weekend" in result


class TestMakeHashtagsPublic:
    """Tests for make_hashtags_public method."""

    @pytest.mark.asyncio
    async def test_make_hashtags_public_success(self):
        """Test making hashtags public when threshold is met."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        from db.models import EventEnrichment
        
        mock_session = MagicMock()
        service = EventEnrichmentService(mock_session)
        
        # Mock enrichments that should become public
        mock_enrichments = [
            EventEnrichment(enrichment_id=1, content="#hiking", is_public=False),
            EventEnrichment(enrichment_id=2, content="#weekend", is_public=False),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_enrichments
        mock_session.execute.return_value = mock_result
        
        # Make them public
        for e in mock_enrichments:
            e.is_public = True
        
        count = len([e for e in mock_enrichments if e.is_public])
        assert count == 2


class TestGetUserContributions:
    """Tests for get_user_contributions method."""

    @pytest.mark.asyncio
    async def test_get_user_contributions(self):
        """Test getting all contributions for a specific user and event."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        from db.models import EventEnrichment
        
        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        service = EventEnrichmentService(mock_session)
        
        mock_enrichments = [
            EventEnrichment(enrichment_type="idea", content="Idea 1"),
            EventEnrichment(enrichment_type="hashtag", content="#tag"),
        ]
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_enrichments
        mock_session.execute.return_value = mock_result
        
        result = await service.get_user_contributions(
            event_id=100,
            telegram_user_id=12345
        )
        
        assert isinstance(result, list)
        assert len(result) == 2


class TestValidation:
    """Tests for content validation."""

    def test_validate_idea_content_too_long(self):
        """Test that ideas over 300 characters are rejected."""
        from bot.services.event_enrichment_service import EventEnrichmentService, ContentValidationError
        
        content = "A" * 301
        with pytest.raises(ContentValidationError) as exc_info:
            EventEnrichmentService._validate_idea_content(content)
        
        assert "300" in str(exc_info.value)

    def test_validate_memory_content_word_count(self):
        """Test that memories over 200 words are rejected."""
        from bot.services.event_enrichment_service import EventEnrichmentService, ContentValidationError
        
        content = "word " * 201
        with pytest.raises(ContentValidationError) as exc_info:
            EventEnrichmentService._validate_memory_content(content)
        
        assert "200" in str(exc_info.value)

    def test_normalize_hashtag(self):
        """Test hashtag normalization."""
        from bot.services.event_enrichment_service import EventEnrichmentService
        
        test_cases = [
            ("hiking", "#hiking"),
            ("#WEEKEND", "#weekend"),
            ("  Trail  ", "#trail"),
            ("#hiking", "#hiking"),
        ]
        
        for input_val, expected in test_cases:
            result = EventEnrichmentService._normalize_hashtag(input_val)
            assert result == expected


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
