# Availability UI Design & LLM Inference System

## Overview

This document outlines the comprehensive design for an enhanced availability system that supports date/time intervals with confidence levels, and includes an LLM-powered inference system for optimal event time slot selection.

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Enhanced Data Model](#enhanced-data-model)
3. [UI Flow Design](#ui-flow-design)
4. [LLM Inference System](#llm-inference-system)
5. [Confidence Margin Algorithms](#confidence-margin-algorithms)
6. [Technical Implementation](#technical-implementation)
7. [API Specifications](#api-specifications)
8. [Testing Strategy](#testing-strategy)

---

## Current State Analysis

### Existing Implementation
```python
# Current Constraint structure
Constraint(
    user_id: int,
    event_id: int,
    type: f"available:{slot_str}",  # e.g., "available:2026-04-17 15:59"
    target_user_id: None
)
```

### Limitations
- Binary availability (available/not available)
- Fixed time slots (9 predefined options)
- No confidence levels
- No time interval support
- Limited flexibility

---

## Enhanced Data Model

### New Constraint Structure
```python
class Constraint(Base):
    __tablename__ = "constraints"
    
    constraint_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False)
    event_id = Column(BigInteger, ForeignKey("events.event_id"), nullable=False)
    type = Column(String(50), nullable=False)  # "availability_range"
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    confidence = Column(Integer, nullable=False)  # 20-100 in steps of 10
    metadata = Column(JSON)  # Additional preferences, notes
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="constraints")
    event = relationship("Event", back_populates="constraints")
```

### Availability Data Examples
```python
# Single time slot with high confidence
{
    "start_time": "2026-04-18 18:00",
    "end_time": "2026-04-18 20:00", 
    "confidence": 90,
    "metadata": {"note": "Prefer earlier if possible", "flexible": True}
}

# Multiple day interval with medium confidence
{
    "start_time": "2026-04-19 14:00",
    "end_time": "2026-04-19 16:00",
    "confidence": 60,
    "metadata": {"note": "Weekend afternoon", "recurring": "weekly"}
}
```

---

## UI Flow Design

### Stage 1: Interval Type Selection
```
Set Availability Time

[Single Time Slot]     [Time Range]
[Multiple Days]       [Flexible Time]
[Recurring Pattern]   [Custom Schedule]
```

### Stage 2: Date Selection
```
Select Date(s)

[Today] [Tomorrow] [This Week]
[Weekend] [Next Week] [Custom Range]
[Multiple Dates] [Recurring]
```

### Stage 3: Time Interval Selection
```
Select Time Range

Morning:   [06:00] - [12:00]  (6 hours)
Afternoon: [12:00] - [18:00]  (6 hours)  
Evening:   [18:00] - [22:00]  (4 hours)
Night:     [22:00] - [02:00]  (4 hours)
Custom:    [HH:MM] - [HH:MM]
```

### Stage 4: Confidence Level Selection
```
Set Confidence Level

[20%] [30%] [40%] [50%]
[60%] [70%] [80%] [90%] [100%]

Legend:
20-40%: If nothing better comes up
50-70%: Good option, prefer if possible
80-90%: Strong preference  
100%: Definite commitment
```

### Visual Confidence Indicators
- **20%**: `20%` (Gray)
- **40%**: `40%` (Red)
- **60%**: `60%` (Orange)
- **80%**: `80%` (Yellow)
- **100%**: `100%` (Green)

---

## LLM Inference System

### System Architecture
```
User Availability Inputs
        |
        v
Availability Aggregation
        |
        v
LLM Analysis & Optimization
        |
        v
Time Slot Ranking with Confidence
        |
        v
Final Event Recommendation
```

### LLM Prompt Structure
```python
def generate_availability_prompt(event_info, user_availabilities):
    prompt = f"""
    Analyze availability data for optimal event scheduling:
    
    Event Details:
    - Type: {event_info['type']}
    - Duration: {event_info['duration_minutes']} minutes
    - Participants: {event_info['participant_count']}
    - Preferred Time Range: {event_info.get('preferred_range', 'Any')}
    
    User Availability Data:
    {format_user_availabilities(user_availabilities)}
    
    Task: 
    1. Identify overlapping time windows
    2. Calculate confidence scores for each window
    3. Consider event type preferences
    4. Rank top 3 optimal time slots
    5. Provide reasoning for each recommendation
    
    Output Format:
    {{
        "recommendations": [
            {{
                "start_time": "YYYY-MM-DD HH:MM",
                "end_time": "YYYY-MM-DD HH:MM", 
                "confidence_score": 85,
                "participant_coverage": 0.8,
                "reasoning": "High overlap during evening hours",
                "risk_factors": ["Low confidence from 2 participants"]
            }}
        ],
        "analysis_summary": "Overall assessment and key insights"
    }}
    """
    return prompt
```

### Confidence Calculation Algorithm
```python
def calculate_time_slot_confidence(availabilities, start_time, end_time):
    """
    Calculate confidence score for a specific time slot based on user availabilities.
    
    Formula: Weighted average of individual confidences
    """
    total_weight = 0
    weighted_confidence = 0
    
    for availability in availabilities:
        if time_overlaps(availability, start_time, end_time):
            # Weight by confidence level and duration overlap
            overlap_duration = calculate_overlap_duration(
                availability, start_time, end_time
            )
            weight = (availability.confidence / 100) * overlap_duration
            weighted_confidence += weight
            total_weight += overlap_duration
    
    if total_weight == 0:
        return 0
    
    base_confidence = (weighted_confidence / total_weight) * 100
    
    # Apply modifiers
    modifiers = {
        'participant_count': apply_participant_count_modifier,
        'event_type': apply_event_type_modifier,
        'time_preference': apply_time_preference_modifier,
        'historical_success': apply_historical_modifier
    }
    
    final_confidence = apply_modifiers(base_confidence, availabilities, modifiers)
    return min(100, max(0, final_confidence))
```

### Optimization Factors

#### 1. Participant Coverage
```python
def calculate_participant_coverage(availabilities, time_slot):
    available_participants = 0
    total_participants = len(availabilities)
    
    for availability in availabilities:
        if time_overlaps(availability, time_slot.start, time_slot.end):
            available_participants += 1
    
    return available_participants / total_participants
```

#### 2. Event Type Preferences
```python
EVENT_TYPE_PREFERENCES = {
    'social': {
        'optimal_hours': [(18, 22), (14, 18)],  # Evening, Afternoon
        'weekend_bonus': 10,
        'confidence_threshold': 70
    },
    'work': {
        'optimal_hours': [(9, 17)],  # Business hours
        'weekday_bonus': 15,
        'confidence_threshold': 80
    },
    'sports': {
        'optimal_hours': [(16, 20), (9, 12)],  # Afternoon, Morning
        'weekend_bonus': 5,
        'confidence_threshold': 60
    }
}
```

#### 3. Historical Success Patterns
```python
def analyze_historical_patterns(user_id, event_type):
    """
    Analyze past event participation success rates.
    """
    # Query historical data
    # Calculate success rates by time slot
    # Identify patterns
    # Return modifier based on historical success
    pass
```

---

## Confidence Margin Algorithms

### Base Confidence Calculation
```python
def calculate_base_confidence(user_availabilities, time_slot):
    """
    Calculate base confidence from user availabilities.
    """
    if not user_availabilities:
        return 0
    
    # Weighted average of individual confidences
    total_confidence = sum(av.confidence for av in user_availabilities)
    avg_confidence = total_confidence / len(user_availabilities)
    
    # Adjust for availability overlap
    overlap_factor = calculate_overlap_percentage(user_availabilities, time_slot)
    
    return avg_confidence * overlap_factor
```

### Risk Assessment
```python
def assess_risk_factors(recommendation):
    """
    Identify potential risks for a time slot recommendation.
    """
    risks = []
    
    # Low confidence participants
    low_conf_users = [
        av for av in recommendation['availabilities'] 
        if av.confidence < 50
    ]
    if len(low_conf_users) > len(recommendation['availabilities']) * 0.3:
        risks.append("High number of low-confidence participants")
    
    # Time conflicts
    if has_known_conflicts(recommendation['time_slot']):
        risks.append("Known conflicts with other events")
    
    # Last-minute scheduling
    days_until_event = (recommendation['time_slot'].start - datetime.now()).days
    if days_until_event < 2:
        risks.append("Last-minute scheduling may reduce attendance")
    
    return risks
```

### Confidence Margin Calculation
```python
def calculate_confidence_margin(base_confidence, risk_factors, modifiers):
    """
    Calculate final confidence with margins for uncertainty.
    """
    margin = 0
    
    # Risk-based margin reduction
    for risk in risk_factors:
        if risk['severity'] == 'high':
            margin -= 15
        elif risk['severity'] == 'medium':
            margin -= 10
        elif risk['severity'] == 'low':
            margin -= 5
    
    # Positive modifiers
    for modifier in modifiers:
        margin += modifier['bonus']
    
    final_confidence = base_confidence + margin
    
    # Ensure bounds
    return min(100, max(0, final_confidence))
```

---

## Technical Implementation

### Database Schema Changes
```sql
-- Add new columns to constraints table
ALTER TABLE constraints 
ADD COLUMN start_time TIMESTAMP NOT NULL,
ADD COLUMN end_time TIMESTAMP NOT NULL,
ADD COLUMN confidence INTEGER NOT NULL CHECK (confidence >= 20 AND confidence <= 100),
ADD COLUMN metadata JSON;

-- Update existing availability constraints
UPDATE constraints 
SET 
    start_time = TO_TIMESTAMP(SUBSTRING(type FROM 12), 'YYYY-MM-DD HH24:MI'),
    end_time = TO_TIMESTAMP(SUBSTRING(type FROM 12), 'YYYY-MM-DD HH24:MI') + INTERVAL '1 hour',
    confidence = 100,
    metadata = '{}'
WHERE type LIKE 'available:%';
```

### API Endpoints

#### Set Availability
```python
@router.post("/events/{event_id}/availability")
async def set_availability(
    event_id: int,
    availability: AvailabilityCreate,
    current_user: User = Depends(get_current_user)
):
    """
    Set user availability for an event with confidence level.
    """
    constraint = Constraint(
        user_id=current_user.user_id,
        event_id=event_id,
        type="availability_range",
        start_time=availability.start_time,
        end_time=availability.end_time,
        confidence=availability.confidence,
        metadata=availability.metadata or {}
    )
    
    db.add(constraint)
    await db.commit()
    
    return {"message": "Availability set successfully"}
```

#### Get Optimal Time Slots
```python
@router.get("/events/{event_id}/optimal-slots")
async def get_optimal_time_slots(
    event_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    Get LLM-optimized time slot recommendations.
    """
    # Fetch event details
    event = await get_event(event_id)
    
    # Fetch all user availabilities
    availabilities = await get_event_availabilities(event_id)
    
    # LLM analysis
    llm_response = await llm_client.analyze_availability(
        event_info=event.to_dict(),
        user_availabilities=[av.to_dict() for av in availabilities]
    )
    
    # Process and rank recommendations
    recommendations = process_llm_response(llm_response)
    
    return {
        "event_id": event_id,
        "recommendations": recommendations,
        "analysis_summary": llm_response.get("analysis_summary")
    }
```

### LLM Integration
```python
class AvailabilityAnalyzer:
    def __init__(self, llm_client):
        self.llm_client = llm_client
    
    async def analyze_and_recommend(self, event_info, user_availabilities):
        """
        Analyze availability data and generate recommendations.
        """
        # Generate time slot candidates
        candidates = self.generate_time_candidates(event_info, user_availabilities)
        
        # Calculate base confidences
        scored_candidates = []
        for candidate in candidates:
            confidence = calculate_time_slot_confidence(
                user_availabilities, 
                candidate['start'], 
                candidate['end']
            )
            candidate['base_confidence'] = confidence
            scored_candidates.append(candidate)
        
        # LLM enhancement
        prompt = self.generate_analysis_prompt(event_info, user_availabilities, scored_candidates)
        llm_response = await self.llm_client.generate(prompt)
        
        # Process LLM recommendations
        enhanced_recommendations = self.process_llm_recommendations(
            scored_candidates, llm_response
        )
        
        return enhanced_recommendations
    
    def generate_time_candidates(self, event_info, user_availabilities):
        """
        Generate candidate time slots based on availability overlaps.
        """
        # Find overlapping time windows
        overlaps = find_overlapping_windows(user_availabilities)
        
        # Generate candidates from overlaps
        candidates = []
        for overlap in overlaps:
            candidates.extend(self.generate_slot_variants(overlap, event_info))
        
        return candidates
```

---

## API Specifications

### Data Models
```python
class AvailabilityCreate(BaseModel):
    start_time: datetime
    end_time: datetime
    confidence: int = Field(..., ge=20, le=100, multiple_of=10)
    metadata: Optional[Dict[str, Any]] = None

class TimeSlotRecommendation(BaseModel):
    start_time: datetime
    end_time: datetime
    confidence_score: int
    participant_coverage: float
    reasoning: str
    risk_factors: List[str]
    alternatives: List[TimeSlotRecommendation]

class AvailabilityAnalysis(BaseModel):
    event_id: int
    recommendations: List[TimeSlotRecommendation]
    analysis_summary: str
    total_participants: int
    response_rate: float
```

### Response Examples
```json
{
    "event_id": 123,
    "recommendations": [
        {
            "start_time": "2026-04-18T18:00:00Z",
            "end_time": "2026-04-18T20:00:00Z",
            "confidence_score": 85,
            "participant_coverage": 0.8,
            "reasoning": "High overlap during evening hours with strong confidence levels",
            "risk_factors": ["One participant has 60% confidence"],
            "alternatives": []
        }
    ],
    "analysis_summary": "Best time slot is Friday evening with 85% confidence. 4 out of 5 participants are available with high confidence levels.",
    "total_participants": 5,
    "response_rate": 1.0
}
```

---

## Testing Strategy

### Unit Tests
- Confidence calculation algorithms
- Time overlap detection
- Risk assessment logic
- LLM prompt generation

### Integration Tests  
- Database schema migrations
- API endpoint functionality
- LLM service integration
- End-to-end availability flow

### Performance Tests
- Large group availability analysis (100+ participants)
- Concurrent availability updates
- LLM response time optimization

### User Acceptance Tests
- UI flow usability
- Confidence level understanding
- Time slot selection accuracy
- Overall satisfaction metrics

---

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-2)
- Database schema updates
- Basic availability CRUD operations
- Simple confidence calculation
- Core UI flow implementation

### Phase 2: LLM Integration (Weeks 3-4)
- LLM service integration
- Enhanced confidence algorithms
- Risk assessment system
- Optimization factors implementation

### Phase 3: Advanced Features (Weeks 5-6)
- Historical pattern analysis
- Smart suggestions
- Conflict detection
- Bulk operations

### Phase 4: Polish & Optimization (Weeks 7-8)
- Performance optimization
- UI refinements
- Testing and bug fixes
- Documentation completion

---

## Success Metrics

### Technical Metrics
- API response time < 500ms
- LLM analysis accuracy > 85%
- Database query optimization
- 99.9% uptime

### User Metrics
- Availability completion rate > 80%
- Time slot acceptance rate > 70%
- User satisfaction score > 4.0/5.0
- Reduced scheduling conflicts by 60%

### Business Metrics
- Event attendance increase by 25%
- User engagement improvement
- Support ticket reduction
- Feature adoption rate

---

## Conclusion

This comprehensive availability system with LLM-powered optimization provides a robust foundation for intelligent event scheduling. The combination of user-friendly UI, sophisticated confidence modeling, and AI-driven recommendations will significantly improve the event organization experience and increase attendance rates.

The modular design allows for incremental implementation and future enhancements while maintaining backward compatibility with existing systems.
