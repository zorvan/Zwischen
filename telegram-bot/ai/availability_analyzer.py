#!/usr/bin/env python3
"""
LLM-powered availability analyzer for optimal event time slot selection.
Integrates with the existing LLM client to provide intelligent scheduling recommendations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from ai.llm import LLMClient
from db.models import Constraint, Event, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ConfidenceLevel(Enum):
    """Confidence level categories for availability."""
    VERY_LOW = (20, 40, "If nothing better comes up")
    LOW = (50, 60, "Good option, prefer if possible")
    HIGH = (70, 80, "Strong preference")
    VERY_HIGH = (90, 100, "Definite commitment")


@dataclass
class TimeSlot:
    """Represents a time slot for event scheduling."""
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    
    def __post_init__(self):
        if self.duration_minutes is None:
            self.duration_minutes = int((self.end_time - self.start_time).total_seconds() / 60)


@dataclass
class UserAvailability:
    """User availability with confidence."""
    user_id: int
    start_time: datetime
    end_time: datetime
    confidence: int
    metadata: Dict[str, Any]


@dataclass
class TimeSlotRecommendation:
    """LLM-generated time slot recommendation."""
    time_slot: TimeSlot
    confidence_score: int
    participant_coverage: float
    reasoning: str
    risk_factors: List[str]
    alternatives: List[TimeSlotRecommendation]
    participant_details: List[Dict[str, Any]]


@dataclass
class AvailabilityAnalysis:
    """Complete availability analysis result."""
    event_id: int
    recommendations: List[TimeSlotRecommendation]
    analysis_summary: str
    total_participants: int
    response_rate: float
    confidence_distribution: Dict[str, int]
    optimal_time_windows: List[TimeSlot]


class EventPreferences:
    """Event type preferences for time optimization."""
    
    PREFERENCES = {
        'social': {
            'optimal_hours': [(18, 22), (14, 18)],  # Evening, Afternoon
            'weekend_bonus': 10,
            'confidence_threshold': 70,
            'duration_preferences': [60, 90, 120, 180]  # minutes
        },
        'work': {
            'optimal_hours': [(9, 17)],  # Business hours
            'weekday_bonus': 15,
            'confidence_threshold': 80,
            'duration_preferences': [30, 60, 90, 120]
        },
        'sports': {
            'optimal_hours': [(16, 20), (9, 12)],  # Afternoon, Morning
            'weekend_bonus': 5,
            'confidence_threshold': 60,
            'duration_preferences': [60, 90, 120, 150]
        },
        'study': {
            'optimal_hours': [(18, 22), (14, 18)],  # Evening, Afternoon
            'weekday_bonus': 5,
            'confidence_threshold': 75,
            'duration_preferences': [60, 90, 120, 180]
        }
    }


class AvailabilityAnalyzer:
    """LLM-powered availability analyzer for optimal event scheduling."""
    
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.event_preferences = EventPreferences()
    
    async def analyze_and_recommend(
        self, 
        event: Event, 
        user_availabilities: List[UserAvailability],
        session: AsyncSession
    ) -> AvailabilityAnalysis:
        """
        Analyze availability data and generate LLM-powered recommendations.
        
        Args:
            event: Event details
            user_availabilities: List of user availabilities with confidence
            session: Database session for additional queries
            
        Returns:
            Complete availability analysis with recommendations
        """
        logger.info(f"Starting availability analysis for event {event.event_id}")
        
        # Generate time slot candidates
        candidates = self._generate_time_candidates(event, user_availabilities)
        
        # Calculate base confidences
        scored_candidates = []
        for candidate in candidates:
            confidence = self._calculate_time_slot_confidence(
                user_availabilities, 
                candidate.start_time, 
                candidate.end_time
            )
            candidate.base_confidence = confidence
            scored_candidates.append(candidate)
        
        # LLM enhancement
        prompt = self._generate_analysis_prompt(event, user_availabilities, scored_candidates)
        llm_response = await self.llm_client.generate(prompt)
        
        # Process LLM recommendations
        recommendations = self._process_llm_recommendations(
            scored_candidates, llm_response, user_availabilities
        )
        
        # Create analysis summary
        analysis = AvailabilityAnalysis(
            event_id=event.event_id,
            recommendations=recommendations,
            analysis_summary=llm_response.get("analysis_summary", ""),
            total_participants=len(user_availabilities),
            response_rate=1.0,  # All provided availabilities
            confidence_distribution=self._calculate_confidence_distribution(user_availabilities),
            optimal_time_windows=self._extract_optimal_windows(recommendations)
        )
        
        logger.info(f"Analysis complete for event {event.event_id}: {len(recommendations)} recommendations")
        return analysis
    
    def _generate_time_candidates(
        self, 
        event: Event, 
        user_availabilities: List[UserAvailability]
    ) -> List[TimeSlot]:
        """
        Generate candidate time slots based on availability overlaps and event preferences.
        """
        candidates = []
        
        # Find overlapping time windows
        overlaps = self._find_overlapping_windows(user_availabilities)
        
        # Generate candidates from overlaps
        for overlap in overlaps:
            # Generate multiple slot variants within the overlap
            variants = self._generate_slot_variants(overlap, event)
            candidates.extend(variants)
        
        # Add event-specific preferred times if no good overlaps found
        if not candidates:
            candidates = self._generate_preferred_time_slots(event)
        
        # Sort by potential coverage
        candidates.sort(
            key=lambda x: self._estimate_coverage(x, user_availabilities),
            reverse=True
        )
        
        # Return top candidates
        return candidates[:20]  # Limit to prevent LLM context overflow
    
    def _find_overlapping_windows(
        self, 
        user_availabilities: List[UserAvailability]
    ) -> List[Tuple[datetime, datetime]]:
        """
        Find time windows where multiple users are available.
        """
        if len(user_availabilities) < 2:
            return []
        
        overlaps = []
        
        # Check all pairs for overlaps
        for i in range(len(user_availabilities)):
            for j in range(i + 1, len(user_availabilities)):
                av1, av2 = user_availabilities[i], user_availabilities[j]
                
                # Find overlap between two availabilities
                overlap_start = max(av1.start_time, av2.start_time)
                overlap_end = min(av1.end_time, av2.end_time)
                
                if overlap_start < overlap_end:
                    overlaps.append((overlap_start, overlap_end))
        
        # Merge overlapping windows
        merged_overlaps = self._merge_overlapping_windows(overlaps)
        return merged_overlaps
    
    def _merge_overlapping_windows(
        self, 
        windows: List[Tuple[datetime, datetime]]
    ) -> List[Tuple[datetime, datetime]]:
        """
        Merge overlapping time windows.
        """
        if not windows:
            return []
        
        # Sort by start time
        windows.sort(key=lambda x: x[0])
        
        merged = [windows[0]]
        
        for current_start, current_end in windows[1:]:
            last_start, last_end = merged[-1]
            
            if current_start <= last_end:
                # Overlapping, merge them
                merged[-1] = (last_start, max(last_end, current_end))
            else:
                # Non-overlapping, add new window
                merged.append((current_start, current_end))
        
        return merged
    
    def _generate_slot_variants(
        self, 
        overlap: Tuple[datetime, datetime], 
        event: Event
    ) -> List[TimeSlot]:
        """
        Generate time slot variants within an overlap window.
        """
        start_time, end_time = overlap
        variants = []
        
        # Standard duration options
        durations = [60, 90, 120, 180]  # minutes
        
        for duration in durations:
            # Generate slots starting at different times within the overlap
            current_start = start_time
            while current_start + timedelta(minutes=duration) <= end_time:
                slot = TimeSlot(
                    start_time=current_start,
                    end_time=current_start + timedelta(minutes=duration),
                    duration_minutes=duration
                )
                variants.append(slot)
                current_start += timedelta(minutes=30)  # 30-minute increments
        
        return variants
    
    def _generate_preferred_time_slots(self, event: Event) -> List[TimeSlot]:
        """
        Generate preferred time slots based on event type when no good overlaps exist.
        """
        preferences = self.event_preferences.PREFERENCES.get(event.event_type, {})
        optimal_hours = preferences.get('optimal_hours', [(9, 17)])
        durations = preferences.get('duration_preferences', [60, 90, 120])
        
        candidates = []
        
        # Generate slots for next 7 days
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for day_offset in range(7):
            current_date = base_date + timedelta(days=day_offset)
            
            for start_hour, end_hour in optimal_hours:
                for duration in durations:
                    slot_start = current_date.replace(hour=start_hour, minute=0)
                    slot_end = slot_start + timedelta(minutes=duration)
                    
                    # Only include if within optimal hours
                    if slot_end.hour <= end_hour:
                        candidates.append(TimeSlot(slot_start, slot_end, duration))
        
        return candidates
    
    def _calculate_time_slot_confidence(
        self, 
        user_availabilities: List[UserAvailability], 
        start_time: datetime, 
        end_time: datetime
    ) -> int:
        """
        Calculate confidence score for a specific time slot.
        
        Formula: Weighted average of individual confidences based on overlap duration
        """
        total_weight = 0
        weighted_confidence = 0
        
        for availability in user_availabilities:
            if self._time_overlaps(availability, start_time, end_time):
                # Calculate overlap duration
                overlap_start = max(availability.start_time, start_time)
                overlap_end = min(availability.end_time, end_time)
                overlap_duration = (overlap_end - overlap_start).total_seconds() / 60
                
                # Weight by confidence level and overlap duration
                weight = (availability.confidence / 100) * overlap_duration
                weighted_confidence += weight
                total_weight += overlap_duration
        
        if total_weight == 0:
            return 0
        
        base_confidence = (weighted_confidence / total_weight)
        
        # Apply modifiers
        final_confidence = self._apply_confidence_modifiers(
            base_confidence, user_availabilities, start_time, end_time
        )
        
        return min(100, max(0, int(final_confidence)))
    
    def _time_overlaps(
        self, 
        availability: UserAvailability, 
        start_time: datetime, 
        end_time: datetime
    ) -> bool:
        """Check if availability overlaps with time slot."""
        return (availability.start_time < end_time and 
                availability.end_time > start_time)
    
    def _apply_confidence_modifiers(
        self, 
        base_confidence: float, 
        user_availabilities: List[UserAvailability],
        start_time: datetime,
        end_time: datetime
    ) -> float:
        """
        Apply various modifiers to base confidence calculation.
        """
        confidence = base_confidence
        
        # Participant coverage modifier
        available_count = sum(
            1 for av in user_availabilities 
            if self._time_overlaps(av, start_time, end_time)
        )
        coverage_ratio = available_count / len(user_availabilities)
        
        if coverage_ratio >= 0.8:
            confidence += 10
        elif coverage_ratio >= 0.6:
            confidence += 5
        elif coverage_ratio < 0.4:
            confidence -= 10
        
        # Time of day modifier
        hour = start_time.hour
        if 18 <= hour <= 22:  # Evening
            confidence += 5
        elif 9 <= hour <= 17:  # Business hours
            confidence += 3
        elif hour < 6 or hour > 23:  # Late night/early morning
            confidence -= 5
        
        # Weekend modifier
        if start_time.weekday() >= 5:  # Saturday or Sunday
            confidence += 2
        
        return confidence
    
    def _estimate_coverage(
        self, 
        time_slot: TimeSlot, 
        user_availabilities: List[UserAvailability]
    ) -> float:
        """Estimate participant coverage for a time slot."""
        available_count = sum(
            1 for av in user_availabilities 
            if self._time_overlaps(av, time_slot.start_time, time_slot.end_time)
        )
        return available_count / len(user_availabilities)
    
    def _generate_analysis_prompt(
        self, 
        event: Event, 
        user_availabilities: List[UserAvailability],
        candidates: List[TimeSlot]
    ) -> str:
        """
        Generate comprehensive prompt for LLM analysis.
        """
        # Format event details
        event_details = f"""
Event Details:
- Type: {event.event_type}
- Duration: {event.duration_minutes or 'Not specified'} minutes
- Description: {event.description or 'No description'}
- Scheduled Time: {event.scheduled_time or 'Not specified'}
- Minimum Participants: {event.min_participants}
- Target Participants: {event.target_participants}
"""
        
        # Format user availabilities
        availability_data = []
        for av in user_availabilities:
            availability_data.append({
                "user_id": av.user_id,
                "start_time": av.start_time.strftime("%Y-%m-%d %H:%M"),
                "end_time": av.end_time.strftime("%Y-%m-%d %H:%M"),
                "confidence": av.confidence,
                "metadata": av.metadata
            })
        
        # Format candidate time slots
        candidate_data = []
        for candidate in candidates[:10]:  # Limit to top 10
            candidate_data.append({
                "start_time": candidate.start_time.strftime("%Y-%m-%d %H:%M"),
                "end_time": candidate.end_time.strftime("%Y-%m-%d %H:%M"),
                "duration_minutes": candidate.duration_minutes,
                "base_confidence": getattr(candidate, 'base_confidence', 0)
            })
        
        prompt = f"""
You are an expert event scheduling assistant. Analyze the availability data and recommend optimal time slots for the event.

{event_details}

User Availability Data:
{availability_data}

Candidate Time Slots:
{candidate_data}

Your task:
1. Analyze the overlap patterns and confidence levels
2. Consider event type preferences and optimal timing
3. Identify the top 3 most suitable time slots
4. Calculate confidence scores for each recommendation
5. Assess potential risks and factors
6. Provide reasoning for each recommendation

Return your analysis in this JSON format:
{{
    "recommendations": [
        {{
            "start_time": "YYYY-MM-DD HH:MM",
            "end_time": "YYYY-MM-DD HH:MM",
            "confidence_score": 85,
            "participant_coverage": 0.8,
            "reasoning": "Detailed explanation of why this time slot is optimal",
            "risk_factors": ["List of potential risks or concerns"],
            "participant_details": [
                {{
                    "user_id": 123,
                    "available": true,
                    "confidence": 90,
                    "overlap_percentage": 100
                }}
            ]
        }}
    ],
    "analysis_summary": "Overall assessment of the availability situation",
    "key_insights": [
        "Important patterns or observations from the data"
    ],
    "recommendation_confidence": 75
}}

Focus on finding times that maximize both attendance probability and participant confidence levels.
"""
        return prompt
    
    def _process_llm_recommendations(
        self, 
        candidates: List[TimeSlot],
        llm_response: Dict[str, Any],
        user_availabilities: List[UserAvailability]
    ) -> List[TimeSlotRecommendation]:
        """
        Process LLM response and create structured recommendations.
        """
        recommendations = []
        
        try:
            llm_recs = llm_response.get("recommendations", [])
            
            for rec in llm_recs:
                # Parse time slot
                start_time = datetime.strptime(rec["start_time"], "%Y-%m-%d %H:%M")
                end_time = datetime.strptime(rec["end_time"], "%Y-%m-%d %H:%M")
                
                time_slot = TimeSlot(
                    start_time=start_time,
                    end_time=end_time,
                    duration_minutes=int((end_time - start_time).total_seconds() / 60)
                )
                
                # Create recommendation
                recommendation = TimeSlotRecommendation(
                    time_slot=time_slot,
                    confidence_score=rec["confidence_score"],
                    participant_coverage=rec["participant_coverage"],
                    reasoning=rec["reasoning"],
                    risk_factors=rec.get("risk_factors", []),
                    alternatives=[],  # Will be populated later
                    participant_details=rec.get("participant_details", [])
                )
                
                recommendations.append(recommendation)
        
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error processing LLM recommendations: {e}")
            # Fallback to basic recommendations
            recommendations = self._create_fallback_recommendations(candidates, user_availabilities)
        
        # Sort by confidence score
        recommendations.sort(key=lambda x: x.confidence_score, reverse=True)
        
        return recommendations[:5]  # Return top 5
    
    def _create_fallback_recommendations(
        self, 
        candidates: List[TimeSlot],
        user_availabilities: List[UserAvailability]
    ) -> List[TimeSlotRecommendation]:
        """
        Create fallback recommendations when LLM processing fails.
        """
        recommendations = []
        
        for candidate in candidates[:3]:
            confidence = self._calculate_time_slot_confidence(
                user_availabilities, candidate.start_time, candidate.end_time
            )
            coverage = self._estimate_coverage(candidate, user_availabilities)
            
            recommendation = TimeSlotRecommendation(
                time_slot=candidate,
                confidence_score=confidence,
                participant_coverage=coverage,
                reasoning=f"Based on availability overlap and confidence levels",
                risk_factors=[],
                alternatives=[],
                participant_details=[]
            )
            
            recommendations.append(recommendation)
        
        return recommendations
    
    def _calculate_confidence_distribution(
        self, 
        user_availabilities: List[UserAvailability]
    ) -> Dict[str, int]:
        """Calculate distribution of confidence levels."""
        distribution = {"20-40": 0, "50-60": 0, "70-80": 0, "90-100": 0}
        
        for av in user_availabilities:
            if av.confidence <= 40:
                distribution["20-40"] += 1
            elif av.confidence <= 60:
                distribution["50-60"] += 1
            elif av.confidence <= 80:
                distribution["70-80"] += 1
            else:
                distribution["90-100"] += 1
        
        return distribution
    
    def _extract_optimal_windows(
        self, 
        recommendations: List[TimeSlotRecommendation]
    ) -> List[TimeSlot]:
        """Extract optimal time windows from recommendations."""
        optimal_windows = []
        
        for rec in recommendations:
            if rec.confidence_score >= 70:  # High confidence threshold
                optimal_windows.append(rec.time_slot)
        
        return optimal_windows


# Utility functions for database operations
async def get_event_availabilities(
    session: AsyncSession, 
    event_id: int
) -> List[UserAvailability]:
    """
    Retrieve all user availabilities for an event.
    """
    from sqlalchemy import select
    
    # Query constraints for the event
    result = await session.execute(
        select(Constraint).where(
            Constraint.event_id == event_id,
            Constraint.type == "availability_range"
        )
    )
    
    constraints = result.scalars().all()
    
    # Convert to UserAvailability objects
    availabilities = []
    for constraint in constraints:
        if constraint.metadata and 'start_time' in constraint.metadata:
            availability = UserAvailability(
                user_id=constraint.user_id,
                start_time=datetime.fromisoformat(constraint.metadata['start_time']),
                end_time=datetime.fromisoformat(constraint.metadata['end_time']),
                confidence=constraint.confidence,
                metadata=constraint.metadata or {}
            )
            availabilities.append(availability)
    
    return availabilities


async def save_availability_constraint(
    session: AsyncSession,
    user_id: int,
    event_id: int,
    start_time: datetime,
    end_time: datetime,
    confidence: int,
    metadata: Optional[Dict[str, Any]] = None
) -> Constraint:
    """
    Save availability constraint to database.
    """
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
