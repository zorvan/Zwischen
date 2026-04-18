#!/usr/bin/env python3
"""Live Card Service for v3.5.

This service manages the creation, updating, and tracking of event cards
posted to group chats. Live cards make events visible and "alive" during
formation by displaying gravity signals (participant counts, hashtags, reactions).

PRD v3.5 Section 4.2: Live Cards and Engagement.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from telegram import Bot, InlineKeyboardMarkup

from db.models import Event, EventLiveCard, GroupSettings
from bot.services.event_enrichment_service import EventEnrichmentService


# =============================================================================
# Service Class
# =============================================================================

class LiveCardService:
    """
    Manages live cards for events in group chats.
    
    Live cards are posted when events are created and updated whenever
    participant counts change. They display gravity signals to make events
    feel alive and encourage participation.
    """
    
    def __init__(self, session: AsyncSession, bot: Bot):
        self.session = session
        self.bot = bot
        self._enrichment_service: Optional[EventEnrichmentService] = None
    
    @property
    def enrichment_service(self) -> EventEnrichmentService:
        """Lazy initialization of enrichment service."""
        if self._enrichment_service is None:
            self._enrichment_service = EventEnrichmentService(self.session)
        return self._enrichment_service
    
    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------
    
    async def create_live_card(
        self,
        event_id: int,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup,
        parse_mode: str = "Markdown",
    ) -> Optional[EventLiveCard]:
        """
        Create or update a live card for an event.
        
        If a card already exists for this event, updates it.
        If not, creates a new message and stores the reference.
        
        Respects group_settings.enable_live_cards setting.
        
        Args:
            event_id: Event being displayed
            chat_id: Telegram chat ID to post to
            text: Card content (Markdown formatted)
            reply_markup: Inline keyboard for actions
            parse_mode: Telegram parse mode
            
        Returns:
            EventLiveCard record or None if disabled/not created
        """
        # Check group settings
        if not await self._is_live_cards_enabled(chat_id):
            return None
        
        # Check for existing card
        existing = await self._get_existing_card(event_id)
        
        if existing:
            # Update existing card
            try:
                await self.bot.edit_message_text(
                    text=text,
                    chat_id=existing.chat_id,
                    message_id=existing.message_id,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                existing.last_updated_at = datetime.utcnow()
                await self.session.flush()
                return existing
            except Exception as e:
                # Message may have been deleted, create new one
                pass
        
        # Create new card
        try:
            message = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            
            card = EventLiveCard(
                event_id=event_id,
                message_id=message.message_id,
                chat_id=chat_id,
                participant_count=0,
                confirmed_count=0,
                reaction_counts={},
                last_updated_at=datetime.utcnow(),
            )
            
            self.session.add(card)
            await self.session.flush()
            
            return card
            
        except Exception as e:
            # Failed to create card (permissions, etc.)
            return None
    
    async def update_live_card(
        self,
        event_id: int,
        text: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        participant_count: Optional[int] = None,
        confirmed_count: Optional[int] = None,
        hashtags: Optional[List[str]] = None,
        parse_mode: str = "Markdown",
    ) -> bool:
        """
        Update an existing live card.
        
        Called automatically when participant counts change.
        
        Args:
            event_id: Event to update
            text: New card text (if None, uses existing)
            reply_markup: New keyboard (if None, keeps existing)
            participant_count: New participant count
            confirmed_count: New confirmed count
            hashtags: Public hashtags to display
            parse_mode: Telegram parse mode
            
        Returns:
            True if updated successfully, False if no card exists
        """
        card = await self._get_existing_card(event_id)
        if not card:
            return False
        
        # Update counts
        if participant_count is not None:
            card.participant_count = participant_count
        if confirmed_count is not None:
            card.confirmed_count = confirmed_count
        
        # Build new text if not provided
        if text is None:
            event_result = await self.session.execute(
                select(Event).where(Event.event_id == event_id)
            )
            event = event_result.scalar_one_or_none()
            if event:
                hashtags = hashtags or await self.enrichment_service.get_public_hashtags(event_id)
                text = self._build_card_text(
                    event,
                    card.participant_count,
                    card.confirmed_count,
                    hashtags,
                )
        
        try:
            await self.bot.edit_message_text(
                text=text or "📅 Event",
                chat_id=card.chat_id,
                message_id=card.message_id,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            card.last_updated_at = datetime.utcnow()
            await self.session.flush()
            return True
            
        except Exception as e:
            # Message may have been deleted
            return False
    
    async def delete_live_card(self, event_id: int) -> bool:
        """
        Delete a live card message.
        
        Called when event is cancelled or locked.
        
        Args:
            event_id: Event whose card should be deleted
            
        Returns:
            True if deleted successfully
        """
        card = await self._get_existing_card(event_id)
        if not card:
            return False
        
        try:
            await self.bot.delete_message(
                chat_id=card.chat_id,
                message_id=card.message_id,
            )
        except Exception:
            # Message may already be deleted
            pass
        
        # Remove from database
        await self.session.execute(
            select(EventLiveCard)
            .where(EventLiveCard.event_id == event_id)
        )
        await self.session.flush()
        return True
    
    async def record_reaction(
        self,
        event_id: int,
        emoji: str,
        delta: int = 1,
    ) -> bool:
        """
        Record a reaction on a live card.
        
        Tracks emoji reactions as gravity signals.
        
        Args:
            event_id: Event being reacted to
            emoji: Reaction emoji
            delta: +1 or -1 for add/remove
            
        Returns:
            True if recorded
        """
        card = await self._get_existing_card(event_id)
        if not card:
            return False
        
        # Update reaction count
        current = card.reaction_counts.get(emoji, 0)
        new_count = max(0, current + delta)
        
        if new_count == 0:
            card.reaction_counts.pop(emoji, None)
        else:
            card.reaction_counts[emoji] = new_count
        
        await self.session.flush()
        return True
    
    async def get_card_status(self, event_id: int) -> Optional[Dict[str, Any]]:
        """
        Get current status of a live card.
        
        Args:
            event_id: Event to query
            
        Returns:
            Dict with message_id, counts, reactions, or None if no card
        """
        card = await self._get_existing_card(event_id)
        if not card:
            return None
        
        return {
            "message_id": card.message_id,
            "chat_id": card.chat_id,
            "participant_count": card.participant_count,
            "confirmed_count": card.confirmed_count,
            "reactions": dict(card.reaction_counts),
            "last_updated": card.last_updated_at,
        }
    
    # -------------------------------------------------------------------------
    # Refresh Hooks (called by other services)
    # -------------------------------------------------------------------------
    
    async def refresh_on_join(
        self,
        event_id: int,
        new_count: int,
        hashtags: Optional[List[str]] = None,
    ) -> bool:
        """
        Refresh card when someone joins.
        
        Args:
            event_id: Event that changed
            new_count: New participant count
            hashtags: Updated hashtags
            
        Returns:
            True if refreshed
        """
        return await self.update_live_card(
            event_id=event_id,
            participant_count=new_count,
            hashtags=hashtags,
        )
    
    async def refresh_on_confirm(
        self,
        event_id: int,
        participant_count: int,
        confirmed_count: int,
        hashtags: Optional[List[str]] = None,
    ) -> bool:
        """
        Refresh card when someone confirms.
        
        Args:
            event_id: Event that changed
            participant_count: Total participants
            confirmed_count: Confirmed participants
            hashtags: Updated hashtags
            
        Returns:
            True if refreshed
        """
        return await self.update_live_card(
            event_id=event_id,
            participant_count=participant_count,
            confirmed_count=confirmed_count,
            hashtags=hashtags,
        )
    
    async def refresh_on_state_change(
        self,
        event_id: int,
        new_state: str,
        text: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> bool:
        """
        Refresh or delete card on state change.
        
        Args:
            event_id: Event that changed
            new_state: New event state
            text: Updated text (for state display)
            reply_markup: Updated keyboard
            
        Returns:
            True if handled
        """
        if new_state in ["cancelled", "locked"]:
            # Delete card for terminal states
            return await self.delete_live_card(event_id)
        
        return await self.update_live_card(
            event_id=event_id,
            text=text,
            reply_markup=reply_markup,
        )
    
    # -------------------------------------------------------------------------
    # Private Helpers
    # -------------------------------------------------------------------------
    
    async def _get_existing_card(self, event_id: int) -> Optional[EventLiveCard]:
        """Get existing card record for an event."""
        result = await self.session.execute(
            select(EventLiveCard).where(EventLiveCard.event_id == event_id)
        )
        return result.scalar_one_or_none()
    
    async def _is_live_cards_enabled(self, chat_id: int) -> bool:
        """Check if live cards are enabled for this group."""
        # For private chats (positive chat_id), always allow
        if chat_id > 0:
            return True
        
        # For groups, check settings
        # Find group_id from chat_id
        from db.models import Group
        group_result = await self.session.execute(
            select(Group).where(Group.telegram_group_id == abs(chat_id))
        )
        group = group_result.scalar_one_or_none()
        
        if not group:
            return True  # Default to enabled if no settings
        
        settings_result = await self.session.execute(
            select(GroupSettings).where(GroupSettings.group_id == group.group_id)
        )
        settings = settings_result.scalar_one_or_none()
        
        if not settings:
            return True  # Default enabled
        
        return settings.enable_live_cards
    
    @staticmethod
    def _build_card_text(
        event: Event,
        participant_count: int,
        confirmed_count: int,
        hashtags: Optional[List[str]] = None,
    ) -> str:
        """
        Build the text content for a live card.
        
        Displays event details and gravity signals.
        """
        lines = []
        
        # Header
        lines.append(f"📅 *Event #{event.event_id}*")
        lines.append(f"Type: {event.event_type}")
        
        # Description (truncated)
        if event.description:
            desc = event.description[:100] + "..." if len(event.description) > 100 else event.description
            lines.append(f"\n{desc}")
        
        # Time
        if event.scheduled_time:
            lines.append(f"\n🕐 {event.scheduled_time.strftime('%Y-%m-%d %H:%M')}")
        
        # State indicator
        state_emoji = {
            "proposed": "💡",
            "interested": "👀",
            "confirmed": "✅",
        }.get(event.state, "📋")
        lines.append(f"\n{state_emoji} Status: *{event.state.upper()}*")
        
        # Gravity signals - participant counts
        lines.append(f"\n👥 {participant_count} interested | ✅ {confirmed_count} confirmed")
        
        # Hashtags
        if hashtags:
            lines.append(f"\n{' '.join(hashtags)}")
        
        return "\n".join(lines)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "LiveCardService",
]
