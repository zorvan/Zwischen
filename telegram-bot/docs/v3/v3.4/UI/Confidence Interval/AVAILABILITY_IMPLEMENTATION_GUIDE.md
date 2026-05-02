# Availability System Implementation Guide

## Overview

This guide provides step-by-step instructions for implementing the enhanced availability system with LLM-powered time slot optimization in your Telegram bot.

## Prerequisites

- Existing Telegram bot with database connection
- LLM client integration (`ai.llm.LLMClient`)
- SQLAlchemy models for `Constraint` and `Event`
- Async/await support throughout the codebase

## Implementation Steps

### Step 1: Database Schema Migration

Create a migration script to update the `constraints` table:

```python
# scripts/migrate_availability_constraints.py
"""
Migration script to update constraints table for availability ranges.
"""
from datetime import datetime, timezone
from sqlalchemy import text
from db.connection import get_session
from config.settings import settings

async def migrate_constraints():
    """Migrate existing availability constraints to new format."""

    async with get_session(settings.db_url) as session:
        # Add new columns
        await session.execute(text("""
            ALTER TABLE constraints
            ADD COLUMN IF NOT EXISTS start_time TIMESTAMP,
            ADD COLUMN IF NOT EXISTS end_time TIMESTAMP,
            ADD COLUMN IF NOT EXISTS confidence INTEGER DEFAULT 100,
            ADD COLUMN IF NOT EXISTS metadata JSON
        """))

        # Migrate existing availability constraints
        await session.execute(text("""
            UPDATE constraints
            SET
                start_time = TO_TIMESTAMP(SUBSTRING(type FROM 12), 'YYYY-MM-DD HH24:MI'),
                end_time = TO_TIMESTAMP(SUBSTRING(type FROM 12), 'YYYY-MM-DD HH24:MI') + INTERVAL '1 hour',
                confidence = 100,
                metadata = '{}'
            WHERE type LIKE 'available:%'
        """))

        await session.commit()
        print("Migration completed successfully")

if __name__ == "__main__":
    import asyncio
    asyncio.run(migrate_constraints())
```

### Step 2: Update Constraint Model

Modify `db/models.py` to include the new fields:

```python
# In db/models.py - update the Constraint class
class Constraint(Base):
    __tablename__ = "constraints"

    constraint_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    target_user_id = Column(BigInteger, ForeignKey("users.user_id"), ondelete="SET NULL"))
    event_id = Column(BigInteger, ForeignKey("events.event_id"), nullable=False)
    type = Column(String(50), nullable=False)

    # New fields for availability ranges
    start_time = Column(DateTime, nullable=True)  # Nullable for backward compatibility
    end_time = Column(DateTime, nullable=True)
    confidence = Column(Integer, default=100)  # 20-100 in steps of 10
    metadata = Column(JSON, default={})

    created_at = Column(DateTime, default=datetime.now(timezone.utc))
```

### Step 3: Integrate Availability Analyzer

Create a service layer for availability analysis:

```python
# bot/services/availability_service.py
"""
Service layer for availability management and analysis.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from ai.availability_analyzer import AvailabilityAnalyzer, UserAvailability
from ai.llm import LLMClient
from db.models import Constraint, Event
from db.connection import get_session

class AvailabilityService:
    """Service for managing availability and generating recommendations."""

    def __init__(self, llm_client: LLMClient):
        self.analyzer = AvailabilityAnalyzer(llm_client)

    async def set_user_availability(
        self,
        user_id: int,
        event_id: int,
        start_time: datetime,
        end_time: datetime,
        confidence: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Constraint:
        """Set user availability for an event."""

        async with get_session(settings.db_url) as session:
            # Check if availability already exists
            existing = await session.execute(
                select(Constraint).where(
                    Constraint.user_id == user_id,
                    Constraint.event_id == event_id,
                    Constraint.type == "availability_range"
                )
            )
            existing_constraint = existing.scalar_one_or_none()

            if existing_constraint:
                # Update existing constraint
                existing_constraint.start_time = start_time
                existing_constraint.end_time = end_time
                existing_constraint.confidence = confidence
                existing_constraint.metadata = metadata or {}
                constraint = existing_constraint
            else:
                # Create new constraint
                constraint = Constraint(
                    user_id=user_id,
                    event_id=event_id,
                    type="availability_range",
                    start_time=start_time,
                    end_time=end_time,
                    confidence=confidence,
                    metadata=metadata or {}
                )
                session.add(constraint)

            await session.commit()
            return constraint

    async def get_event_recommendations(
        self,
        event_id: int
    ) -> Dict[str, Any]:
        """Get LLM-powered recommendations for event timing."""

        async with get_session(settings.db_url) as session:
            # Get event details
            event_result = await session.execute(
                select(Event).where(Event.event_id == event_id)
            )
            event = event_result.scalar_one_or_none()

            if not event:
                return {"error": "Event not found"}

            # Get user availabilities
            availabilities = await self._get_event_availabilities(session, event_id)

            if not availabilities:
                return {"error": "No availability data found"}

            # Generate recommendations
            analysis = await self.analyzer.analyze_and_recommend(
                event, availabilities, session
            )

            return self._format_analysis_response(analysis)

    async def _get_event_availabilities(
        self,
        session: AsyncSession,
        event_id: int
    ) -> List[UserAvailability]:
        """Get all user availabilities for an event."""

        result = await session.execute(
            select(Constraint).where(
                Constraint.event_id == event_id,
                Constraint.type == "availability_range"
            )
        )

        constraints = result.scalars().all()

        availabilities = []
        for constraint in constraints:
            if constraint.start_time and constraint.end_time:
                availability = UserAvailability(
                    user_id=constraint.user_id,
                    start_time=constraint.start_time,
                    end_time=constraint.end_time,
                    confidence=constraint.confidence,
                    metadata=constraint.metadata or {}
                )
                availabilities.append(availability)

        return availabilities

    def _format_analysis_response(self, analysis) -> Dict[str, Any]:
        """Format analysis response for API/UI consumption."""

        return {
            "event_id": analysis.event_id,
            "recommendations": [
                {
                    "start_time": rec.time_slot.start_time.isoformat(),
                    "end_time": rec.time_slot.end_time.isoformat(),
                    "confidence_score": rec.confidence_score,
                    "participant_coverage": rec.participant_coverage,
                    "reasoning": rec.reasoning,
                    "risk_factors": rec.risk_factors
                }
                for rec in analysis.recommendations
            ],
            "analysis_summary": analysis.analysis_summary,
            "total_participants": analysis.total_participants,
            "confidence_distribution": analysis.confidence_distribution
        }
```

### Step 4: Update Event Details Command

Modify the availability handling in `bot/commands/event_details.py`:

```python
# In bot/commands/event_details.py - update availability functions

from bot.services.availability_service import AvailabilityService
from datetime import datetime, timedelta, timezone

# Initialize service (in your command handler setup)
availability_service = AvailabilityService(llm_client)

async def _show_enhanced_availability_options(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show enhanced availability options with confidence levels."""

    keyboard = [
        [
            InlineKeyboardButton(
                "Set Time Range", callback_data=f"avail_range_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "View Recommendations", callback_data=f"avail_recs_{event_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "Current Availability", callback_data=f"avail_current_{event_id}"
            )
        ],
        [
            InlineKeyboardButton("Back", callback_data=f"event_details_{event_id}")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Availability Options\n\n"
        "Set your availability with confidence levels "
        "or view AI-powered recommendations.",
        reply_markup=reply_markup
    )

async def _show_recommendations(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Show LLM-generated time slot recommendations."""

    try:
        recommendations = await availability_service.get_event_recommendations(event_id)

        if "error" in recommendations:
            await query.edit_message_text(f"Error: {recommendations['error']}")
            return

        # Format recommendations for display
        message = "AI-Powered Time Recommendations:\n\n"

        for i, rec in enumerate(recommendations["recommendations"][:3], 1):
            start_dt = datetime.fromisoformat(rec["start_time"])
            message += f"{i}. {start_dt.strftime('%a, %b %d %H:%M')}\n"
            message += f"   Confidence: {rec['confidence_score']}%\n"
            message += f"   Coverage: {rec['participant_coverage']*100:.0f}% participants\n"
            message += f"   {rec['reasoning']}\n\n"

        message += recommendations.get("analysis_summary", "")

        keyboard = [
            [InlineKeyboardButton("Set Availability", callback_data=f"avail_range_{event_id}")],
            [InlineKeyboardButton("Back", callback_data=f"avail_{event_id}")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        await query.edit_message_text("Error generating recommendations.")

async def _handle_time_range_selection(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int
) -> None:
    """Handle time range selection with confidence."""

    # Show date selection
    keyboard = []

    # Add common date options
    today = datetime.now(timezone.utc).date()
    for i in range(7):
        date = today + timedelta(days=i)
        date_str = date.strftime("%a, %b %d")
        if i == 0:
            date_str = f"Today ({date_str})"
        elif i == 1:
            date_str = f"Tomorrow ({date_str})"

        keyboard.append([
            InlineKeyboardButton(date_str, callback_data=f"avail_date_{event_id}_{i}")
        ])

    keyboard.append([InlineKeyboardButton("Back", callback_data=f"avail_{event_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Select date for availability:",
        reply_markup=reply_markup
    )

async def _handle_time_selection(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, day_offset: int
) -> None:
    """Handle time selection for chosen date."""

    # Store selected date in context
    selected_date = datetime.now(timezone.utc).date() + timedelta(days=day_offset)
    context.user_data["availability_date"] = selected_date.isoformat()

    # Show time range options
    keyboard = [
        [InlineKeyboardButton("Morning (6AM-12PM)", callback_data=f"avail_time_{event_id}_morning")],
        [InlineKeyboardButton("Afternoon (12PM-6PM)", callback_data=f"avail_time_{event_id}_afternoon")],
        [InlineKeyboardButton("Evening (6PM-10PM)", callback_data=f"avail_time_{event_id}_evening")],
        [InlineKeyboardButton("Custom Time", callback_data=f"avail_time_{event_id}_custom")],
        [InlineKeyboardButton("Back", callback_data=f"avail_{event_id}")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"Select time range for {selected_date.strftime('%A, %B %d')}:",
        reply_markup=reply_markup
    )

async def _handle_confidence_selection(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, time_range: str
) -> None:
    """Handle confidence level selection."""

    # Store time range in context
    context.user_data["availability_time_range"] = time_range

    # Show confidence options
    keyboard = [
        [
            InlineKeyboardButton("100%", callback_data=f"avail_conf_{event_id}_100"),
            InlineKeyboardButton("90%", callback_data=f"avail_conf_{event_id}_90"),
            InlineKeyboardButton("80%", callback_data=f"avail_conf_{event_id}_80")
        ],
        [
            InlineKeyboardButton("70%", callback_data=f"avail_conf_{event_id}_70"),
            InlineKeyboardButton("60%", callback_data=f"avail_conf_{event_id}_60"),
            InlineKeyboardButton("50%", callback_data=f"avail_conf_{event_id}_50")
        ],
        [
            InlineKeyboardButton("40%", callback_data=f"avail_conf_{event_id}_40"),
            InlineKeyboardButton("30%", callback_data=f"avail_conf_{event_id}_30"),
            InlineKeyboardButton("20%", callback_data=f"avail_conf_{event_id}_20")
        ],
        [InlineKeyboardButton("Back", callback_data=f"avail_{event_id}")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Set your confidence level:\n\n"
        "100%: Definite commitment\n"
        "80-90%: Strong preference\n"
        "60-70%: Good option\n"
        "20-50%: If nothing better comes up",
        reply_markup=reply_markup
    )

async def _save_enhanced_availability(
    query, context: ContextTypes.DEFAULT_TYPE, event_id: int, confidence: int
) -> None:
    """Save availability with time range and confidence."""

    try:
        # Get user info
        user_id = query.from_user.id
        date_str = context.user_data.get("availability_date")
        time_range = context.user_data.get("availability_time_range")

        if not date_str or not time_range:
            await query.edit_message_text("Missing date or time selection.")
            return

        # Parse date and time range
        selected_date = datetime.fromisoformat(date_str).date()

        # Convert time range to actual times
        if time_range == "morning":
            start_time = datetime.combine(selected_date, datetime.min.time()).replace(hour=6)
            end_time = datetime.combine(selected_date, datetime.min.time()).replace(hour=12)
        elif time_range == "afternoon":
            start_time = datetime.combine(selected_date, datetime.min.time()).replace(hour=12)
            end_time = datetime.combine(selected_date, datetime.min.time()).replace(hour=18)
        elif time_range == "evening":
            start_time = datetime.combine(selected_date, datetime.min.time()).replace(hour=18)
            end_time = datetime.combine(selected_date, datetime.min.time()).replace(hour=22)
        else:
            await query.edit_message_text("Custom time selection not implemented yet.")
            return

        # Convert to UTC
        start_time = start_time.replace(tzinfo=timezone.utc)
        end_time = end_time.replace(tzinfo=timezone.utc)

        # Save availability
        constraint = await availability_service.set_user_availability(
            user_id=user_id,
            event_id=event_id,
            start_time=start_time,
            end_time=end_time,
            confidence=confidence,
            metadata={"time_range": time_range, "source": "telegram_bot"}
        )

        # Clear context
        context.user_data.pop("availability_date", None)
        context.user_data.pop("availability_time_range", None)

        await query.edit_message_text(
            f"Availability saved successfully!\n\n"
            f"Time: {start_time.strftime('%a, %b %d %H:%M')} - {end_time.strftime('%H:%M')}\n"
            f"Confidence: {confidence}%\n"
            f"ID: {constraint.constraint_id}"
        )

    except Exception as e:
        logger.error(f"Error saving availability: {e}")
        await query.edit_message_text("Error saving availability. Please try again.")
```

### Step 5: Update Callback Handlers

Add new callback handlers to the event details handler:

```python
# In bot/commands/event_details.py - update handle_event_details callback
# Add these cases to your existing callback handling:

elif data and data.startswith("avail_range_"):
    event_id = int(data.replace("avail_range_", ""))
    await _handle_time_range_selection(query, context, event_id)

elif data and data.startswith("avail_date_"):
    parts = data.split("_")
    event_id = int(parts[2])
    day_offset = int(parts[3])
    await _handle_time_selection(query, context, event_id, day_offset)

elif data and data.startswith("avail_time_"):
    parts = data.split("_")
    event_id = int(parts[2])
    time_range = parts[3]
    await _handle_confidence_selection(query, context, event_id, time_range)

elif data and data.startswith("avail_conf_"):
    parts = data.split("_")
    event_id = int(parts[2])
    confidence = int(parts[3])
    await _save_enhanced_availability(query, context, event_id, confidence)

elif data and data.startswith("avail_recs_"):
    event_id = int(data.replace("avail_recs_", ""))
    await _show_recommendations(query, context, event_id)

elif data and data.startswith("avail_current_"):
    event_id = int(data.replace("avail_current_", ""))
    await _show_current_availability(query, context, event_id)
```

### Step 6: Add Service Initialization

Update your bot initialization to include the availability service:

```python
# In your main bot setup or service initialization
from ai.llm import LLMClient
from bot.services.availability_service import AvailabilityService

# Initialize LLM client
llm_client = LLMClient()

# Initialize availability service
availability_service = AvailabilityService(llm_client)

# Make it available to your command handlers
# (depending on your dependency injection pattern)
```

### Step 7: Testing

Create comprehensive tests for the new functionality:

```python
# tests/test_availability_system.py
"""
Tests for the enhanced availability system.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from ai.availability_analyzer import AvailabilityAnalyzer, UserAvailability, TimeSlot
from bot.services.availability_service import AvailabilityService

@pytest.mark.asyncio
async def test_availability_analyzer_basic():
    """Test basic availability analysis functionality."""

    # Mock LLM client
    llm_client = AsyncMock()
    llm_client.generate.return_value = {
        "recommendations": [
            {
                "start_time": "2026-04-18 18:00",
                "end_time": "2026-04-18 20:00",
                "confidence_score": 85,
                "participant_coverage": 0.8,
                "reasoning": "Good evening overlap",
                "risk_factors": []
            }
        ],
        "analysis_summary": "Evening slot recommended"
    }

    analyzer = AvailabilityAnalyzer(llm_client)

    # Create test data
    user_availabilities = [
        UserAvailability(
            user_id=1,
            start_time=datetime(2026, 4, 18, 17, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 4, 18, 21, 0, tzinfo=timezone.utc),
            confidence=90
        ),
        UserAvailability(
            user_id=2,
            start_time=datetime(2026, 4, 18, 18, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 4, 18, 22, 0, tzinfo=timezone.utc),
            confidence=80
        )
    ]

    # Create mock event
    event = MagicMock()
    event.event_id = 123
    event.event_type = "social"
    event.duration_minutes = 120
    event.description = "Test event"

    # Mock session
    session = AsyncMock()

    # Run analysis
    result = await analyzer.analyze_and_recommend(event, user_availabilities, session)

    # Verify results
    assert len(result.recommendations) == 1
    assert result.recommendations[0].confidence_score == 85
    assert result.total_participants == 2

@pytest.mark.asyncio
async def test_confidence_calculation():
    """Test confidence calculation algorithms."""

    analyzer = AvailabilityAnalyzer(AsyncMock())

    user_availabilities = [
        UserAvailability(
            user_id=1,
            start_time=datetime(2026, 4, 18, 18, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 4, 18, 20, 0, tzinfo=timezone.utc),
            confidence=90
        ),
        UserAvailability(
            user_id=2,
            start_time=datetime(2026, 4, 18, 19, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 4, 18, 21, 0, tzinfo=timezone.utc),
            confidence=70
        )
    ]

    # Test overlapping time slot
    confidence = analyzer._calculate_time_slot_confidence(
        user_availabilities,
        datetime(2026, 4, 18, 19, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 18, 20, 0, tzinfo=timezone.utc)
    )

    # Should be weighted average with modifiers
    assert confidence > 70
    assert confidence <= 100
```

## Deployment Checklist

- [ ] Run database migration script
- [ ] Update Constraint model
- [ ] Implement AvailabilityAnalyzer service
- [ ] Update event details command handlers
- [ ] Add new callback handlers
- [ ] Initialize services in bot startup
- [ ] Run comprehensive tests
- [ ] Monitor LLM API usage and costs
- [ ] Add error handling and fallbacks
- [ ] Document new features for users

## Monitoring and Optimization

### Key Metrics to Track
- LLM response times
- Recommendation accuracy (user acceptance rates)
- Availability completion rates
- API error rates
- Database query performance

### Optimization Tips
- Cache LLM responses for similar availability patterns
- Implement batch processing for large groups
- Use streaming responses for faster perceived performance
- Add confidence calibration based on user feedback

## Troubleshooting

### Common Issues
1. **LLM API timeouts**: Implement retry logic and fallback recommendations
2. **Database performance**: Add indexes on constraint queries
3. **Memory usage**: Limit candidate generation for large groups
4. **User confusion**: Add clear instructions and examples

### Error Handling
- Always provide fallback recommendations when LLM fails
- Gracefully handle malformed confidence values
- Validate time ranges before saving
- Provide clear error messages to users

This implementation guide provides a complete roadmap for integrating the enhanced availability system with LLM-powered optimization into your existing Telegram bot.
