#!/usr/bin/env python3
"""Tests for Mosaic Assembly - Phase 4 v3.5.

Tests assembling private memories from event_enrichments into
a public mosaic when events complete.

PRD v3.5 Section 4.4: Memory Loop Completion
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


class TestMosaicAssembler:
    """Tests for the MosaicAssembler class."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        return MagicMock()

    @pytest.fixture
    def sample_memories(self):
        """Create sample memory enrichments."""
        return [
            MagicMock(
                id=1,
                event_id=1,
                enrichment_type="memory",
                content="Great hiking trip to the mountains!",
                telegram_user_id=1001,
                is_public=False,
                created_at=datetime.now(timezone.utc),
            ),
            MagicMock(
                id=2,
                event_id=1,
                enrichment_type="memory",
                content="The sunset was amazing that day.",
                telegram_user_id=1002,
                is_public=False,
                created_at=datetime.now(timezone.utc),
            ),
            MagicMock(
                id=3,
                event_id=1,
                enrichment_type="memory",
                content="We should do this again next month!",
                telegram_user_id=1003,
                is_public=False,
                created_at=datetime.now(timezone.utc),
            ),
        ]

    @pytest.mark.asyncio
    async def test_assemble_mosaic_basic(self, mock_session, sample_memories):
        """Test basic mosaic assembly."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        assembler = MosaicAssembler(mock_session)
        
        with patch.object(assembler, '_fetch_memories', return_value=sample_memories):
            with patch.object(assembler, '_update_memory_visibility', new_callable=AsyncMock) as mock_update:
                result = await assembler.assemble_mosaic(event_id=1)
                
                assert result is not None
                assert "event_id" in result
                assert result["event_id"] == 1
                assert "fragments" in result
                assert len(result["fragments"]) == 3

    @pytest.mark.asyncio
    async def test_assemble_mosaic_no_memories(self, mock_session):
        """Test mosaic assembly with no memories."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        assembler = MosaicAssembler(mock_session)
        
        with patch.object(assembler, '_fetch_memories', return_value=[]):
            result = await assembler.assemble_mosaic(event_id=1)
            
            # Should return empty mosaic
            assert result is not None
            assert result["fragments"] == []
            assert result["participant_count"] == 0

    @pytest.mark.asyncio
    async def test_assemble_mosaic_with_memories_only(self, mock_session):
        """Test that mosaic only includes memory enrichments."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        # Only memories (as _fetch_memories would return)
        memory_enrichments = [
            MagicMock(enrichment_type="memory", content="Memory 1", is_public=False),
            MagicMock(enrichment_type="memory", content="Memory 2", is_public=False),
        ]

        assembler = MosaicAssembler(mock_session)
        
        with patch.object(assembler, '_fetch_memories', return_value=memory_enrichments):
            with patch.object(assembler, '_update_memory_visibility', new_callable=AsyncMock):
                result = await assembler.assemble_mosaic(event_id=1)
                
                # All fetched items should be in mosaic as fragments
                assert len(result["fragments"]) == 2
                for fragment in result["fragments"]:
                    assert fragment["type"] == "memory"

    @pytest.mark.asyncio
    async def test_mosaic_marks_memories_public(self, mock_session, sample_memories):
        """Test that mosaic assembly marks memories as public."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        assembler = MosaicAssembler(mock_session)
        
        with patch.object(assembler, '_fetch_memories', return_value=sample_memories):
            with patch.object(assembler, '_update_memory_visibility', new_callable=AsyncMock) as mock_update:
                await assembler.assemble_mosaic(event_id=1)
                
                # Should update visibility for all memories
                assert mock_update.call_count == len(sample_memories)

    @pytest.mark.asyncio
    async def test_mosaic_generates_summary(self, mock_session, sample_memories):
        """Test that mosaic generates a summary."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        assembler = MosaicAssembler(mock_session)
        
        with patch.object(assembler, '_fetch_memories', return_value=sample_memories):
            with patch.object(assembler, '_update_memory_visibility', new_callable=AsyncMock):
                with patch.object(assembler, '_generate_summary', return_value="Test summary"):
                    result = await assembler.assemble_mosaic(event_id=1)
                    
                    assert "summary" in result
                    assert result["summary"] == "Test summary"


class TestMosaicFragmentStructure:
    """Tests for mosaic fragment structure."""

    def test_fragment_contains_required_fields(self):
        """Test that fragments have all required fields."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        memory = MagicMock(
            id=1,
            event_id=1,
            content="Test memory",
            telegram_user_id=1001,
            created_at=datetime.now(timezone.utc),
            is_public=False,
        )

        assembler = MosaicAssembler(MagicMock())
        fragment = assembler._create_fragment(memory)

        # MosaicFragment is a dataclass - access attributes, not keys
        assert fragment.id == 1
        assert fragment.content == "Test memory"
        assert fragment.author_id == 1001
        assert fragment.created_at is not None
        assert fragment.type == "memory"

    def test_fragment_truncate_long_content(self):
        """Test that very long memories are truncated."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        long_content = "A" * 5000  # Way over limit
        memory = MagicMock(
            id=1,
            content=long_content,
            telegram_user_id=1001,
            created_at=datetime.now(timezone.utc),
        )

        assembler = MosaicAssembler(MagicMock())
        fragment = assembler._create_fragment(memory)

        # Should be truncated to reasonable length
        assert len(fragment.content) < 5000


class TestMosaicLineage:
    """Tests for event lineage tracking."""

    @pytest.mark.asyncio
    async def test_mosaic_tracks_lineage(self):
        """Test that mosaic records lineage information."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        
        assembler = MosaicAssembler(mock_session)
        
        with patch.object(assembler, '_fetch_memories', return_value=[]):
            with patch.object(assembler, '_update_memory_visibility', new_callable=AsyncMock):
                result = await assembler.assemble_mosaic(event_id=1, parent_event_id=5)
                
                # Should record lineage - check result has lineage info
                assert result is not None
                assert "lineage" in result


class TestMosaicStorage:
    """Tests for mosaic persistence."""

    @pytest.mark.asyncio
    async def test_mosaic_stored_in_event_memory(self):
        """Test that assembled mosaic is stored."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        
        assembler = MosaicAssembler(mock_session)
        
        # Mock _fetch_memories to return a memory
        mock_memory = MagicMock()
        mock_memory.id = 1
        mock_memory.content = "Test memory"
        mock_memory.telegram_user_id = 1001
        mock_memory.created_at = datetime.now(timezone.utc)

        with patch.object(assembler, '_fetch_memories', return_value=[mock_memory]):
            with patch.object(assembler, '_update_memory_visibility', new_callable=AsyncMock):
                with patch.object(assembler, '_store_mosaic', new_callable=AsyncMock) as mock_store:
                    with patch.object(assembler, '_append_to_event_memory', new_callable=AsyncMock):
                        await assembler.assemble_and_store(event_id=1)
                        
                        # Should call store mosaic
                        mock_store.assert_called_once()


class TestMosaicLLMIntegration:
    """Tests for LLM-based mosaic enhancement."""

    @pytest.mark.asyncio
    async def test_mosaic_uses_llm_for_summary(self):
        """Test that mosaic uses LLM to generate summary."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        # Create mock LLM client
        mock_llm = MagicMock()
        mock_llm.summarize_memories = AsyncMock(return_value={"summary": "Summary of hiking memories"})
        
        assembler = MosaicAssembler(MagicMock(), llm_client=mock_llm)
        
        memories = [
            MagicMock(content="Great hiking trip"),
            MagicMock(content="Amazing sunset"),
        ]
        
        summary = await assembler._generate_llm_summary(memories)
        
        # Should use LLM and return summary
        assert summary is not None
        assert summary == "Summary of hiking memories"

    @pytest.mark.asyncio
    async def test_mosaic_fallback_without_llm(self):
        """Test mosaic works without LLM availability."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        # No LLM client provided
        assembler = MosaicAssembler(MagicMock())
        
        memories = [
            MagicMock(content="Memory 1"),
            MagicMock(content="Memory 2"),
        ]
        
        # Should use fallback summary generation
        summary = await assembler._generate_summary(memories)
        
        assert summary is not None
        assert "2" in summary  # Should mention participant count


class TestMosaicCompletesEventMemory:
    """Tests integrating mosaic with EventMemory."""

    @pytest.mark.asyncio
    async def test_mosaic_updates_event_memory_fragments(self):
        """Test that mosaic fragments are added to EventMemory."""
        from bot.services.mosaic_assembly_service import MosaicAssembler

        mock_session = MagicMock()
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        
        assembler = MosaicAssembler(mock_session)
        
        # Mock _fetch_memories to return a memory
        mock_memory = MagicMock()
        mock_memory.id = 1
        mock_memory.content = "Test memory"
        mock_memory.telegram_user_id = 1001
        mock_memory.created_at = datetime.now(timezone.utc)

        with patch.object(assembler, '_fetch_memories', return_value=[mock_memory]):
            with patch.object(assembler, '_update_memory_visibility', new_callable=AsyncMock):
                with patch.object(assembler, '_append_to_event_memory', new_callable=AsyncMock) as mock_append:
                    await assembler.assemble_and_store(event_id=1)
                    
                    # Should append fragments to EventMemory
                    mock_append.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
