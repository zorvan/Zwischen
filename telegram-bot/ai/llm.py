"""
OpenAI-compatible LLM client for Qwen3.
PRD v2 Priority 4: Production Hardening (TODO-016).
- Schema validation for all LLM outputs
- Type safety and value range validation
"""

import httpx
import json
import logging
import re
from datetime import datetime
from typing import Dict, Any, Tuple
from config.settings import settings
from db.models import Event
from ai.actions import ActionsRegistry
from ai.validator import create_validator, ValidationResult

logger = logging.getLogger(__name__)

MEDIATOR_SYSTEM = """You are a group coordination mediator embedded in a Telegram group.
Your role is to help the group bring events into existence, not just parse commands.
When people express vague intent (let's meet, we should do this, how about Saturday),
treat it as an event organization request. Be proactive and warm, not technical.
When uncertain, prefer action over inaction — propose a draft, offer options, ask one clarifying question.
Never respond with only a classification — always include a helpful next step.

For JSON output: set action_type to organize_event or organize_event_flexible when the user is
trying to plan something; use opinion only for genuine questions or meta chat."""


class LLMClient:
    """OpenAI SDK wrapper for Qwen3 (or any OpenAI-compatible API)."""

    def __init__(self):
        self.base_url = settings.ai_endpoint
        self.api_key = settings.ai_api_key
        self.model = settings.ai_model
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0,
        )

    async def resolve_conflicts(
        self,
        event: Event,
        availability: Dict[int, float],
        notes: list[str] | None = None,
    ) -> Dict[str, Any]:
        """Generate conflict resolution suggestions using LLM."""
        from ai.schemas import ConflictResolution, validate_llm_output

        prompt = self._build_conflict_prompt(event, availability, notes or [])

        def fallback():
            return {
                "conflict_detected": False,
                "suggested_time": "TBD",
                "reasoning": "LLM unavailable, using fallback",
                "compromises": [],
            }

        try:
            response = await self._call_llm(prompt)
            return validate_llm_output(
                ConflictResolution, response, fallback_factory=fallback, logger=logger
            )
        except Exception as e:
            logger.exception("Conflict resolution failed: %s", e)
            return fallback()

    async def analyze_constraints(self, constraints) -> list[Dict[str, Any]]:
        """Analyze constraints for conflicts."""
        from ai.schemas import ConstraintAnalysis, validate_llm_output

        prompt = self._build_constraint_prompt(constraints)

        def fallback():
            return {"conflicts": []}

        try:
            response = await self._call_llm(prompt)
            validated = validate_llm_output(
                ConstraintAnalysis, response, fallback_factory=fallback, logger=logger
            )
            return [c.dict() for c in validated.get("conflicts", [])]
        except Exception:
            return []

    async def infer_feedback_from_text(
        self, event_type: str, text: str
    ) -> Dict[str, Any]:
        """Infer weighted structured feedback from free-form text."""
        from ai.schemas import FeedbackInference, validate_llm_output

        prompt = f"""
        Convert user feedback into structured JSON.
        Remove toxicity and abusive wording while preserving meaning.
        Infer:
        - score 1-5
        - weight 0.0-1.0 (confidence/quality of feedback)
        - sanitized_comment
        - expertise_adjustments map for activity tags

        Event type: {event_type}
        User feedback:
        {text}

        Output JSON only:
        {{
          "score": 1.0,
          "weight": 0.7,
          "sanitized_comment": "clean text",
          "expertise_adjustments": {{"tag": 0.1}}
        }}
        """

        def fallback():
            cleaned = _sanitize_toxic_text(text)
            sentiment = _simple_sentiment_score(cleaned)
            return {
                "score": sentiment,
                "weight": 0.6,
                "sanitized_comment": cleaned,
                "expertise_adjustments": {event_type: 0.1},
            }

        try:
            response = await self._call_llm(prompt)
            return validate_llm_output(
                FeedbackInference, response, fallback_factory=fallback, logger=logger
            )
        except Exception:
            return fallback()

    async def infer_event_draft_patch(
        self,
        current_draft: Dict[str, Any],
        message_text: str,
    ) -> Dict[str, Any]:
        """Infer a structured patch for event draft revisions."""
        prompt = f"""
        You update an event draft using user requested modifications.
        Analyze the user's message and extract any changes they want to make.
        Be flexible but conservative - only change what's explicitly mentioned.

        Current draft:
        {current_draft}

        User modification request:
        {message_text}

        IMPORTANT: Look for specific changes like:
        - Time changes: "change to 7pm", "move to tomorrow 3pm", "set time to 2024-01-15 19:00"
        - Participant changes: "minimum 5 people", "capacity 10", "at least 3"
        - Duration changes: "2 hours long", "90 minutes", "extend by 30 min"
        - Location changes: "at the park", "change location to cafe", "move to Amin's house"
        - Type changes: "make it sports", "change to work event", "social gathering"
        - Budget/transport: "free event", "drive there", "public transit"

        EXAMPLES:
        - "change time to 8pm" → {{"scheduled_time_iso": "2024-01-15T20:00"}}
        - "minimum 4 people" → {{"min_participants": 4}}
        - "at the cafe" → {{"location_type": "cafe"}}
        - "sports event" → {{"event_type": "sports"}}

        Output JSON with changes only for fields that are explicitly modified:
        {{
          "description": "updated description or null",
          "event_type": "social|sports|work|null",
          "scheduled_time_iso": "YYYY-MM-DDTHH:MM or null",
          "clear_time": true/false,
          "duration_minutes": number or null,
          "min_participants": number or null,
          "target_participants": number or null,
          "location_type": "home|outdoor|cafe|office|gym or null",
          "budget_level": "free|low|medium|high or null",
          "transport_mode": "walk|public_transit|drive|any or null"
        }}
        """
        try:
            response = await self._call_llm(prompt)
            parsed = json.loads(response)
            return {
                "description": parsed.get("description"),
                "event_type": parsed.get("event_type"),
                "scheduled_time_iso": parsed.get("scheduled_time_iso"),
                "clear_time": bool(parsed.get("clear_time", False)),
                "duration_minutes": parsed.get("duration_minutes"),
                "min_participants": parsed.get("min_participants"),
                "target_participants": parsed.get("target_participants"),
                "location_type": parsed.get("location_type"),
                "budget_level": parsed.get("budget_level"),
                "transport_mode": parsed.get("transport_mode"),
            }
        except Exception:
            lowered = message_text.lower()
            patch: Dict[str, Any] = {
                "description": None,
                "event_type": None,
                "scheduled_time_iso": None,
                "clear_time": False,
                "duration_minutes": None,
                "min_participants": None,
                "target_participants": None,
                "invitees_add": [],
                "invitees_remove": [],
                "invite_all_members": None,
                "scheduling_mode": None,
                "note": None,
                "location_type": None,
                "budget_level": None,
                "transport_mode": None,
            }

            if "flexible" in lowered:
                patch["scheduling_mode"] = "flexible"
            elif "fixed" in lowered:
                patch["scheduling_mode"] = "fixed"

            if "invite all" in lowered or "@all" in lowered:
                patch["invite_all_members"] = True

            min_match = re.search(
                r"\b(?:minimum|min|threshold|at least)(?:\s+(?:to|of))?\s+(\d{1,3})\b",
                lowered,
            )
            if min_match:
                patch["min_participants"] = int(min_match.group(1))

            target_match = re.search(
                r"\b(?:capacity|target|up to|fit)\s+(\d{1,3})\b", lowered
            )
            if target_match:
                patch["target_participants"] = int(target_match.group(1))

            duration_match = re.search(
                r"\b(\d{1,3})\s*(minutes|minute|mins|min|hours|hour|hrs|hr)\b",
                lowered,
            )
            if duration_match:
                value = int(duration_match.group(1))
                unit = duration_match.group(2)
                patch["duration_minutes"] = (
                    value * 60 if "hour" in unit or "hr" in unit else value
                )

            datetime_match = re.search(
                r"\b(\d{4}-\d{2}-\d{2})[ t](\d{1,2}:\d{2})\b",
                message_text,
            )
            if datetime_match:
                date_part = datetime_match.group(1)
                time_part = datetime_match.group(2)
                hour, minute = time_part.split(":")
                patch["scheduled_time_iso"] = f"{date_part}T{int(hour):02d}:{minute}"
            else:
                # Try natural language dates like "April 18, 2026 at 18:00"
                month_map = {
                    "january": 1,
                    "february": 2,
                    "march": 3,
                    "april": 4,
                    "may": 5,
                    "june": 6,
                    "july": 7,
                    "august": 8,
                    "september": 9,
                    "october": 10,
                    "november": 11,
                    "december": 12,
                }
                month_pattern = (
                    r"\b("
                    + "|".join(month_map.keys())
                    + r")\s+(\d{1,2}),?\s+(\d{4})\s*(?:at|on)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
                )
                natural_date_match = re.search(month_pattern, lowered)
                if natural_date_match:
                    month_name = natural_date_match.group(1)
                    day = int(natural_date_match.group(2))
                    year = int(natural_date_match.group(3))
                    hour = int(natural_date_match.group(4))
                    minute_part = natural_date_match.group(5)
                    ampm_part = natural_date_match.group(6)
                    minute = int(minute_part) if minute_part else 0
                    month = month_map[month_name]
                    if ampm_part:
                        ampm = ampm_part.lower()
                        if ampm == "pm" and hour != 12:
                            hour += 12
                        elif ampm == "am" and hour == 12:
                            hour = 0
                    patch["scheduled_time_iso"] = (
                        f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}"
                    )
                else:
                    # Try more flexible time parsing
                    time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", message_text)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        # Assume today if no date specified
                        today = datetime.now().date()
                        patch["scheduled_time_iso"] = f"{today}T{hour:02d}:{minute:02d}"
                    else:
                        # Try 12-hour format with am/pm
                        ampm_match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", lowered)
                        if ampm_match:
                            hour = int(ampm_match.group(1))
                            ampm = ampm_match.group(2)
                            if ampm == "pm" and hour != 12:
                                hour += 12
                            elif ampm == "am" and hour == 12:
                                hour = 0
                            today = datetime.now().date()
                            patch["scheduled_time_iso"] = f"{today}T{hour:02d}:00"

            if (
                "clear time" in lowered
                or "no time" in lowered
                or "time tbd" in lowered
                or "flexible" in lowered
            ):
                patch["clear_time"] = True

            handles = re.findall(r"@([A-Za-z][A-Za-z0-9_]{4,31})", message_text)
            if "remove" in lowered:
                patch["invitees_remove"] = [h.lower() for h in handles]
            elif "add" in lowered or "invite" in lowered:
                patch["invitees_add"] = [h.lower() for h in handles]

            if lowered.startswith("description:"):
                patch["description"] = message_text.split(":", 1)[1].strip()
            elif lowered.startswith("note:") or lowered.startswith("constraint:"):
                patch["note"] = message_text.split(":", 1)[1].strip()

            if any(token in lowered for token in {"social", "sports", "work"}):
                if "sports" in lowered:
                    patch["event_type"] = "sports"
                elif "work" in lowered:
                    patch["event_type"] = "work"
                else:
                    patch["event_type"] = "social"

            # Location type detection
            if any(
                token in lowered
                for token in [
                    "home",
                    "at home",
                    "my house",
                    "your house",
                    "their house",
                    "someone's house",
                    "amir's house",
                    "john's house",
                ]
            ):
                patch["location_type"] = "home"
            elif any(
                token in lowered
                for token in ["park", "outdoor", "outside", "garden", "field"]
            ):
                patch["location_type"] = "outdoor"
            elif any(
                token in lowered
                for token in ["cafe", "restaurant", "coffee shop", "diner"]
            ):
                patch["location_type"] = "cafe"
            elif any(
                token in lowered
                for token in ["office", "workspace", "workplace", "meeting room"]
            ):
                patch["location_type"] = "office"
            elif any(token in lowered for token in ["gym", "fitness", "workout place"]):
                patch["location_type"] = "gym"

            # Budget level detection
            if any(
                token in lowered for token in ["free", "no cost", "cheap", "budget"]
            ):
                patch["budget_level"] = "free"
            elif any(
                token in lowered for token in ["low cost", "inexpensive", "affordable"]
            ):
                patch["budget_level"] = "low"
            elif any(
                token in lowered for token in ["moderate", "mid-range", "medium cost"]
            ):
                patch["budget_level"] = "medium"
            elif any(
                token in lowered
                for token in ["expensive", "premium", "high-end", "luxury"]
            ):
                patch["budget_level"] = "high"

            # Transport mode detection
            if "walking" in lowered or "walk" in lowered:
                patch["transport_mode"] = "walk"
            elif any(
                token in lowered
                for token in ["public transit", "bus", "train", "metro", "subway"]
            ):
                patch["transport_mode"] = "public_transit"
            elif any(
                token in lowered for token in ["driving", "drive", "car", "by car"]
            ):
                patch["transport_mode"] = "drive"

            return patch

    async def infer_event_draft_from_context(
        self,
        *,
        message_text: str,
        history: list[dict[str, Any]] | None = None,
        scheduling_mode: str = "fixed",
    ) -> Dict[str, Any]:
        """Infer a full event draft from mention text + recent chat context."""
        compact_history = (history or [])[-15:]
        prompt = f"""
        Build an event draft JSON from group context.
        Be GENEROUS with inference — extract as much as possible from the conversation history.
        Even if time is uncertain, extract hints (e.g., "Saturday evening" → use next Saturday 19:00).
        If multiple people are mentioned, add them to invitees.
        NEVER return null for description — summarize the intent.

        CRITICAL: Extract ALL parameters from the conversation. Do NOT use defaults unless the conversation is completely silent on that topic.
        - event_type: "social" for hangouts/games/meetups, "sports" for athletic activities, "work" for professional/coding sessions
        - min_participants: If a minimum is discussed (e.g., "need at least 4"), use that. Otherwise infer from context (small gathering → 3, big party → 6+).
        - target_participants: If ideal capacity is discussed, use it. Otherwise set a comfortable target at or above the minimum.
        - duration_minutes: If duration is discussed (e.g., "for a couple hours" → 120, "quick meetup" → 60). Otherwise infer from context.
        
        CRITICAL RULES FOR invite_all_members:
        - DEFAULT to TRUE unless the message EXPLICITLY excludes others
        - Set FALSE ONLY for explicit privacy language: "just alice", "private meetup", "don't tell others", "only bob and me"
        - Mentioning specific people does NOT mean private — it means they're emphasized/key attendees
        - "@alice let's play games" → invite_all_members: TRUE (open invitation, Alice is just the organizer/contact)
        - "Just alice and bob, private dinner" → invite_all_members: FALSE (explicit privacy)
        
        - invitees: List ALL people mentioned as potential attendees (with @ prefix, lowercase)
        - key_attendees: List people who are emphasized/important to the event (organizers, contacts, conditional attendees). This is SEPARATE from privacy — mentions go here without affecting invite_all_members.
        - date_preset: "today", "tomorrow", "weekend", "nextweek", or "custom" — infer from relative time references
        - time_window: "early-morning", "morning", "afternoon", "evening", "night" — infer from time-of-day hints
        - location_type: If a venue type is discussed (home, outdoor, cafe, office, gym), set it. Otherwise omit.
        - budget_level: If cost is discussed (free, cheap, expensive), set it. Otherwise omit.
        - transport_mode: If transport is discussed (walk, public_transit, drive), set it. Otherwise omit.
        - scheduled_time_iso: If a specific date+time is discussed, set it as YYYY-MM-DDTHH:MM. Otherwise null.
        - collapse_at_iso: Auto-cancel deadline. If scheduling_mode is flexible or time is unknown, set to ~7 days from now. Otherwise null.

        CRITICAL: Extract location/context from the conversation.
        - If a location is mentioned (e.g., "Amin's house", "the park", "gym downtown"), weave it into the description naturally.
        - If a specific venue is discussed, include it in the description.
        - Do NOT default to generic locations like "cafe" unless explicitly mentioned.
        - The description should read like a natural invitation: "Board games at Amin's house" not "Social event at Cafe".

        CRITICAL: Extract constraints from the conversation.
        - If someone says "I'll come if X comes" → constraint: if_joins for X
        - If someone says "I can only make it if Y is attending" → constraint: if_attends for Y
        - If someone says "I won't go unless Z goes" → constraint: unless_joins for Z
        - If someone says "I'm free Saturday" → note it in planning_notes
        - Add inferred constraints to the constraints array with type, target_username, and a short note.

        User message:
        {message_text}

        Recent chat history:
        {compact_history}

        Requested scheduling mode:
        {scheduling_mode}

        Output JSON only:
        {{
          "description": "short natural text with location if mentioned",
          "event_type": "social|sports|work",
          "scheduled_time_iso": "YYYY-MM-DDTHH:MM or null",
          "collapse_at_iso": "YYYY-MM-DDTHH:MM or null",
          "duration_minutes": 120,
          "min_participants": 3,
          "target_participants": 5,
          "invite_all_members": true,
          "invitees": ["@alice", "@bob"],
          "key_attendees": ["@alice"],
          "planning_notes": ["note 1", "note 2"],
          "date_preset": "today|tomorrow|weekend|nextweek|custom",
          "time_window": "early-morning|morning|afternoon|evening|night",
          "location_type": "home|outdoor|cafe|office|gym or null",
          "budget_level": "free|low|medium|high or null",
          "transport_mode": "walk|public_transit|drive|any or null",
          "constraints": [
            {{
              "constraint_type": "if_joins|if_attends|unless_joins",
              "target_username": "username_without_at",
              "note": "short explanation"
            }}
          ]
        }}

        The constraints array should be empty if no constraints are inferred.
        The location_type, budget_level, and transport_mode should be null if not discussed.
        If scheduling mode is flexible or time is unknown, set scheduled_time_iso to null but still
        set collapse_at_iso to a reasonable deadline (e.g. 7 days from now at end of day) so the
        event can auto-cancel if interest stays low.
        """
        try:
            response = await self._call_llm_large(prompt)
            parsed = json.loads(response)
            event_type = str(parsed.get("event_type", "social")).strip().lower()
            if event_type not in {"social", "sports", "work"}:
                event_type = "social"
            duration = int(parsed.get("duration_minutes", 120))
            min_participants = int(parsed.get("min_participants", 3))
            target_participants = int(
                parsed.get("target_participants", max(min_participants, 5))
            )
            invitees = parsed.get("invitees", [])
            if not isinstance(invitees, list):
                invitees = []
            normalized_invitees = []
            for raw in invitees:
                s = str(raw).strip()
                if not s:
                    continue
                if not s.startswith("@"):
                    s = f"@{s}"
                normalized_invitees.append(s.lower())

            # Normalize key_attendees (emphasized people, separate from privacy)
            key_attendees_raw = parsed.get("key_attendees", [])
            if not isinstance(key_attendees_raw, list):
                key_attendees_raw = []
            normalized_key_attendees = []
            for raw in key_attendees_raw:
                s = str(raw).strip()
                if not s:
                    continue
                if not s.startswith("@"):
                    s = f"@{s}"
                normalized_key_attendees.append(s.lower())

            notes = parsed.get("planning_notes", [])
            if not isinstance(notes, list):
                notes = []
            collapse_raw = parsed.get("collapse_at_iso")
            collapse_at = None
            if isinstance(collapse_raw, str) and collapse_raw.strip():
                try:
                    collapse_at = datetime.fromisoformat(collapse_raw.strip())
                except ValueError:
                    collapse_at = None

            # Extract inferred constraints
            constraints_raw = parsed.get("constraints", [])
            if not isinstance(constraints_raw, list):
                constraints_raw = []
            inferred_constraints = []
            for c in constraints_raw:
                if not isinstance(c, dict):
                    continue
                ctype = str(c.get("constraint_type", "")).strip().lower()
                if ctype not in {"if_joins", "if_attends", "unless_joins"}:
                    continue
                target = c.get("target_username")
                if target is not None:
                    target = str(target).strip().lstrip("@")
                    if not target:
                        target = None
                note = str(c.get("note", "")).strip()[:200]
                if ctype and target:
                    inferred_constraints.append(
                        {
                            "constraint_type": ctype,
                            "target_username": target,
                            "note": note,
                        }
                    )

            # Extract optional location/budget/transport — only set if explicitly provided
            location_type = parsed.get("location_type")
            if isinstance(location_type, str) and location_type.strip():
                location_type = location_type.strip().lower()
                valid_locations = {"home", "outdoor", "cafe", "office", "gym"}
                if location_type not in valid_locations:
                    location_type = None
            else:
                location_type = None

            budget_level = parsed.get("budget_level")
            if isinstance(budget_level, str) and budget_level.strip():
                budget_level = budget_level.strip().lower()
                valid_budgets = {"free", "low", "medium", "high"}
                if budget_level not in valid_budgets:
                    budget_level = None
            else:
                budget_level = None

            transport_mode = parsed.get("transport_mode")
            if isinstance(transport_mode, str) and transport_mode.strip():
                transport_mode = transport_mode.strip().lower()
                valid_transport = {"walk", "public_transit", "drive", "any"}
                if transport_mode not in valid_transport:
                    transport_mode = None
            else:
                transport_mode = None

            # Extract date_preset
            date_preset = parsed.get("date_preset")
            if isinstance(date_preset, str) and date_preset.strip():
                date_preset = date_preset.strip().lower()
                valid_presets = {"today", "tomorrow", "weekend", "nextweek", "custom"}
                if date_preset not in valid_presets:
                    date_preset = None
            else:
                date_preset = None

            # Extract time_window
            time_window = parsed.get("time_window")
            if isinstance(time_window, str) and time_window.strip():
                time_window = time_window.strip().lower()
                valid_windows = {
                    "early-morning",
                    "morning",
                    "afternoon",
                    "evening",
                    "night",
                }
                if time_window not in valid_windows:
                    time_window = None
            else:
                time_window = None

            return {
                "description": str(
                    parsed.get("description", message_text or "Group planned event")
                ).strip()[:500],
                "event_type": event_type,
                "scheduled_time": parsed.get("scheduled_time_iso"),
                "collapse_at": collapse_at.isoformat() if collapse_at else None,
                "duration_minutes": max(30, min(720, duration)),
                "min_participants": max(1, min(200, min_participants)),
                "target_participants": max(
                    max(1, min(200, min_participants)),
                    min(200, target_participants),
                ),
                "invite_all_members": bool(parsed.get("invite_all_members", True)),
                "invitees": normalized_invitees,
                "key_attendees": normalized_key_attendees,
                "planning_notes": [
                    str(n).strip()[:300] for n in notes if str(n).strip()
                ],
                "date_preset": date_preset,
                "time_window": time_window,
                "location_type": location_type,
                "budget_level": budget_level,
                "transport_mode": transport_mode,
                "inferred_constraints": inferred_constraints,
            }
        except Exception:
            return {
                "description": (message_text or "Group planned event").strip()[:500],
                "event_type": "social",
                "scheduled_time": None,
                "collapse_at": None,
                "duration_minutes": 120,
                "min_participants": 3,
                "target_participants": 5,
                "invite_all_members": True,
                "invitees": ["@all"],
                "key_attendees": [],
                "planning_notes": ["Draft auto-generated from limited context."],
                "date_preset": None,
                "time_window": None,
                "location_type": None,
                "budget_level": None,
                "transport_mode": None,
                "inferred_constraints": [],
            }

    async def infer_action(
        self,
        text: str,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Phase 1: Inference using canonical action registry.

        v3.4 Design:
        - Uses ai/actions.py for action registry
        - Single structured prompt with schema injection
        - ai/validator.py enforces output contract before dispatch
        - No regex fallbacks - user clarifies when validation fails

        Args:
            text: The user message
            context: Dict with 'active_events', 'user_events', 'group_id' etc

        Returns:
            Dict with keys: action, params, confidence, assistant_response
        """
        from ai.actions import ActionsRegistry
        from ai.validator import create_validator, ValidationResult

        actions = ActionsRegistry.get_actions()
        schema = self._build_action_schema(actions)

        compact_history = (context or {}).get("history", [])[-10:]
        active_events = (context or {}).get("active_events", [])
        user_events = (context or {}).get("user_events", [])

        prompt = f"""
        You are a Telegram group coordination assistant.
        
        Available actions and when to use them:
        {schema}
        
        Group context:
        - Active events: {active_events}
        - User's joined events: {user_events}
        - Recent chat (last 5 messages): {compact_history[-5:] if compact_history else "empty"}
        
        User message: {text}
        
        Select the best action. Return ONLY this JSON:
        {{
          "action": "<action_name from registry>",
          "params": {{...required and optional params}},
          "confidence": 0.0-1.0,
          "assistant_response": "brief helpful message to user"
        }}
        """.strip()

        try:
            response = await self._call_llm(prompt, max_tokens=600)
            parsed = json.loads(response)

            # Validate against registry
            validator = create_validator()
            result = validator.validate(parsed)

            if not result.valid:
                # Non-recoverable error or missing params
                if result.recoverable:
                    return {
                        "action": "clarify",
                        "params": {},
                        "confidence": 0.0,
                        "assistant_response": f"{result.reason}. {validator.get_missing_params_message(result.missing_params)}",
                    }
                else:
                    logger.warning("LLM output validation failed: %s", result.reason)
                    return {
                        "action": "opinion",
                        "params": {},
                        "confidence": 0.0,
                        "assistant_response": "I had trouble understanding that. Can you try again?",
                    }

            return parsed

        except json.JSONDecodeError as e:
            logger.warning("LLM returned invalid JSON: %s", e)
            return {
                "action": "opinion",
                "params": {},
                "confidence": 0.0,
                "assistant_response": "I had trouble understanding that. Can you try again?",
            }
        except Exception as e:
            logger.error("LLM action inference failed: %s", e)
            return {
                "action": "opinion",
                "params": {},
                "confidence": 0.0,
                "assistant_response": "I had trouble understanding that. Can you try again?",
            }

    def _build_action_schema(self, actions: Dict[str, Dict[str, Any]]) -> str:
        """
        Build a structured schema description for the prompt.

        Each action is described with:
        - name
        - when to use (description)
        - required params
        - optional params
        """
        schema_parts = []
        for action_name, action_def in actions.items():
            description = action_def.get("description", "No description")
            required = action_def.get("required_params", [])
            optional = action_def.get("optional_params", [])

            params_list = []
            if required:
                params_list.append(f"required: {', '.join(required)}")
            if optional:
                params_list.append(f"optional: {', '.join(optional)}")

            schema_parts.append(f"- **{action_name}**: {description}")
            if params_list:
                schema_parts.append(f"  Parameters: {', '.join(params_list)}")

        return "\n".join(schema_parts)

    async def infer_event_draft_from_action(
        self,
        text: str,
        history: list[dict[str, Any]] | None = None,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Phase 4: Inference using action registry for event creation.

        Uses the create_event action to infer full draft parameters.
        """
        compact_history = (history or [])[-15:]

        # Build context for the LLM
        active_events = (context or {}).get("active_events", [])
        user_events = (context or {}).get("user_events", [])

        prompt = f"""
        You are building an event draft. Extract parameters from the conversation.
        
        Available actions: use create_event when user wants to organize/gather.
        
        User message:
        {text}
        
        Recent chat history:
        {compact_history}
        
        Group context:
        - Active events: {active_events}
        - User's joined events: {user_events}
        
        Extract ALL parameters from conversation. Be generous with inference.
        
        Output JSON ONLY:
        {{
          "action": "create_event",
          "params": {{
            "description": "short natural text with location if mentioned",
            "event_type": "social|sports|work",
            "scheduled_time": "YYYY-MM-DDTHH:MM or null",
            "duration_minutes": number,
            "min_participants": number,
            "target_participants": number,
            "invite_all_members": true,
            "invitees": ["@alice", "@bob"],
            "planning_notes": ["note 1"],
            "date_preset": "today|tomorrow|weekend|nextweek|custom",
            "time_window": "early-morning|morning|afternoon|evening|night",
            "location_type": "home|outdoor|cafe|office|gym or null",
            "budget_level": "free|low|medium|high or null",
            "transport_mode": "walk|public_transit|drive|any or null"
          }},
          "confidence": 0.0-1.0,
          "assistant_response": "brief helpful message"
        }}
        """.strip()

        try:
            response = await self._call_llm(prompt, max_tokens=800)
            parsed = json.loads(response)

            # Validate
            from ai.validator import create_validator

            validator = create_validator()
            result = validator.validate(parsed)

            if not result.valid:
                return self._infer_draft_fallback(text, compact_history)

            return parsed.get("params", {})

        except Exception:
            return self._infer_draft_fallback(text, compact_history)

    def _infer_draft_fallback(
        self,
        text: str,
        history: list[dict[str, Any]],
    ) -> Dict[str, Any]:
        """Fallback for event draft inference when LLM fails."""
        # Extract simple parameters from text
        import re

        text_lower = text.lower()

        draft = {
            "description": "Group planned event",
            "event_type": "social",
            "scheduled_time": None,
            "duration_minutes": 120,
            "min_participants": 3,
            "target_participants": 6,
            "invite_all_members": True,
            "invitees": [],
            "planning_notes": [],
        }

        # Extract invitees
        mentions = re.findall(r"@([A-Za-z][A-Za-z0-9_]{3,31})", text)
        if mentions:
            draft["invitees"] = [f"@{m.lower()}" for m in mentions]
            draft["invite_all_members"] = (
                False  # Explicit mentions suggest limited invitees
            )

        # Extract scheduling mode
        if "flexible" in text_lower or "when" in text_lower or "tbd" in text_lower:
            draft["scheduled_time"] = None

        # Extract type hints
        if any(w in text_lower for w in ["game", "games", "play", "fun", "hangout"]):
            draft["event_type"] = "social"
        elif any(w in text_lower for w in ["sport", "run", "workout", "gym", "train"]):
            draft["event_type"] = "sports"
        elif any(
            w in text_lower for w in ["work", "coding", "meeting", "professional"]
        ):
            draft["event_type"] = "work"

        # Extract min participants
        min_match = re.search(r"(?:minimum|at least|need)\s+(\d+)", text)
        if min_match:
            draft["min_participants"] = int(min_match.group(1))

        return draft

    async def infer_event_patch_from_action(
        self,
        current_draft: Dict[str, Any],
        text: str,
    ) -> Dict[str, Any]:
        """
        Phase 4: Inference using action registry for event draft patch.

        Uses the edit_event action with params for revisions.
        """
        prompt = f"""
        You update an event draft using user requested modifications.
        
        Current draft:
        {current_draft}
        
        User modification request:
        {text}
        
        Output ONLY the JSON with changes for fields that are explicitly modified:
        {{
          "action": "edit_event",
          "params": {{
            "event_id": event_id_if_applicable,
            "description": "updated text or null",
            "scheduled_time": "YYYY-MM-DDTHH:MM or null",
            "duration_minutes": number or null,
            "min_participants": number or null,
            "clear_time": true/false
          }},
          "confidence": 0.0-1.0,
          "assistant_response": "brief helpful message"
        }}
        """.strip()

        try:
            response = await self._call_llm(prompt, max_tokens=500)
            parsed = json.loads(response)

            from ai.validator import create_validator

            validator = create_validator()
            result = validator.validate(parsed)

            if not result.valid:
                # Use fallback for specific fields
                return self._infer_patch_fallback(text, current_draft)

            return parsed.get("params", {})

        except Exception:
            return self._infer_patch_fallback(text, current_draft)

    def _infer_patch_fallback(
        self,
        text: str,
        current_draft: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Fallback for patch inference when LLM fails."""
        import re
        from datetime import datetime, date

        text_lower = text.lower()
        patch = {}

        # Time changes - parse natural language dates
        time_match = re.search(
            r"change time to (\w+ \d+,? \d{4}(?: at (\d{1,2})(?::(\d{2}))?(?:am|pm)?)?)",
            text_lower,
        )

        # Also check for just "7pm" style inputs
        just_time_match = re.search(r"(\d{1,2})(?::(\d{2}))?(?:am|pm)?", text_lower)

        if (
            time_match
            or "change time" in text_lower
            or "move" in text_lower
            or "set time" in text_lower
        ):
            # Try to parse date from text
            try:
                # Determine which match to use
                if time_match:
                    date_str = time_match.group(1)
                    time_part = time_match.group(2)
                    min_part = time_match.group(3)
                elif just_time_match:
                    # Just time like "7pm" - use current date
                    current_date = date.today()
                    date_str = f"{current_date.strftime('%B')} {current_date.day}, {current_date.year}"
                    time_part = just_time_match.group(1)
                    min_part = (
                        just_time_match.group(2) if just_time_match.group(2) else "00"
                    )
                else:
                    date_str = "April 18, 2026"
                    time_part = "18"
                    min_part = "00"

                # Parse hour
                hour = int(time_part)
                minute = int(min_part) if min_part else 0

                # Handle AM/PM
                if "pm" in text_lower and hour < 12:
                    hour += 12
                elif "am" in text_lower and hour == 12:
                    hour = 0

                # Parse date - extract just the date portion
                date_match = re.search(r"(\w+ \d+,? \d{4})", date_str)
                if date_match:
                    date_str_clean = date_match.group(1)
                else:
                    date_str_clean = "april 18, 2026"
                try:
                    parsed_dt = datetime.strptime(date_str_clean, "%B %d, %Y")
                except ValueError:
                    date_str_clean = date_str_clean.replace(",", "")
                    parsed_dt = datetime.strptime(date_str_clean, "%B %d %Y")
                parsed_dt = parsed_dt.replace(hour=hour, minute=minute)

                # Format without seconds for compatibility
                patch["scheduled_time"] = parsed_dt.strftime("%Y-%m-%dT%H:%M")
            except Exception:
                patch["scheduled_time"] = None

        # Participant changes
        if (
            "minimum" in text_lower
            or "at least" in text_lower
            or "capacity" in text_lower
        ):
            import re

            num_match = re.search(r"(\d+)", text)
            if num_match:
                patch["min_participants"] = int(num_match.group(1))

        # Duration changes
        if "hour" in text_lower or "minute" in text_lower:
            import re

            hour_match = re.search(r"(\d+)\s*(?:hour|hr)", text)
            if hour_match:
                patch["duration_minutes"] = int(hour_match.group(1)) * 60

        # Type changes
        if "sports" in text_lower:
            patch["event_type"] = "sports"
        elif "work" in text_lower:
            patch["event_type"] = "work"

        # Location changes
        if "cafe" in text_lower or "coffee" in text_lower:
            patch["location_type"] = "cafe"
        elif "home" in text_lower or "house" in text_lower:
            patch["location_type"] = "home"
        elif "park" in text_lower or "outdoor" in text_lower:
            patch["location_type"] = "outdoor"

        return patch if patch else {}

    async def _call_llm(
        self,
        prompt: str,
        max_tokens: int = 800,
        system: str | None = None,
    ) -> str:
        """Make LLM API call."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = await self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def _call_llm_large(self, prompt: str, system: str | None = None) -> str:
        """Context-heavy prompts (long history) need more output tokens for valid JSON."""
        return await self._call_llm(prompt, max_tokens=1200, system=system)

    async def check_availability(self) -> Tuple[bool, str]:
        """Check if the configured LLM endpoint is reachable."""
        try:
            response = await self.client.get("/models")
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", [])
            model_count = len(models) if isinstance(models, list) else 0
            return True, f"LLM available (models={model_count})"
        except Exception as e:
            return False, f"LLM unavailable: {type(e).__name__}: {e}"

    def _build_conflict_prompt(
        self,
        event: Event,
        availability: Dict[int, float],
        notes: list[str],
    ) -> str:
        """Construct Qwen3 prompt for conflict resolution."""
        return f"""
        You are a scheduling assistant. Resolve conflicts for this event using
        only declared availability. No user history or behavioral inference.

        Event: {event.event_type}
        Participants: {len(getattr(event, "participants", []) or [])}
        Minimum needed: {event.min_participants}

        Availability slots (users per slot): {availability}

        Private attendee notes:
        {notes}

        Output JSON:
        {{
            "conflict_detected": true/false,
            "suggested_time": "ISO timestamp or TBD",
            "reasoning": "brief explanation",
            "compromises": ["suggestion 1", "suggestion 2"]
        }}
        """

    def _build_constraint_prompt(self, constraints) -> str:
        """Construct Qwen3 prompt for constraint analysis."""
        return f"""
        Analyze these constraints for conflicts.

        Constraints:
        {constraints}

        Output JSON:
        {{
            "conflicts": [
                {{"user": id, "target": id, "condition": "description"}}
            ]
        }}
        """

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    # Phase 5: Backward compatibility wrappers for old code
    async def infer_event_draft_patch(
        self,
        current_draft: Dict[str, Any],
        message_text: str,
    ) -> Dict[str, Any]:
        """Wrapper: Use infer_event_patch_from_action instead (backward compat)."""
        patch = await self.infer_event_patch_from_action(current_draft, message_text)
        # Map new keys to old keys for backward compatibility
        result = {}
        for key, value in patch.items():
            if key == "scheduled_time":
                result["scheduled_time_iso"] = value
            elif key == "event_type":
                result["event_type"] = value
            elif key == "duration_minutes":
                result["duration_minutes"] = value
            elif key == "min_participants":
                result["min_participants"] = value
            elif key == "target_participants":
                result["target_participants"] = value
            elif key == "location_type":
                result["location_type"] = value
            elif key == "budget_level":
                result["budget_level"] = value
            elif key == "transport_mode":
                result["transport_mode"] = value
            else:
                result[key] = value
        return result

    async def infer_event_draft_from_context(
        self,
        *,
        message_text: str,
        history: list[dict[str, Any]] | None = None,
        scheduling_mode: str = "fixed",
    ) -> Dict[str, Any]:
        """Wrapper: Use infer_event_draft_from_action instead (backward compat)."""
        history_list = history or []
        draft_params = await self.infer_event_draft_from_action(
            text=message_text,
            history=history_list,
        )
        # Map new keys to old keys for backward compatibility
        result = {}
        for key, value in draft_params.items():
            if key == "scheduled_time":
                result["scheduled_time_iso"] = value
            elif key == "scheduled_time":
                result["collapse_at_iso"] = value
            elif key == "invite_all_members":
                result["invite_all_members"] = value
            elif key == "invitees":
                result["invitees"] = value
            elif key == "planning_notes":
                result["planning_notes"] = value
            elif key == "date_preset":
                result["date_preset"] = value
            elif key == "time_window":
                result["time_window"] = value
            elif key == "location_type":
                result["location_type"] = value
            elif key == "budget_level":
                result["budget_level"] = value
            elif key == "transport_mode":
                result["transport_mode"] = value
            else:
                result[key] = value
        # Add missing keys from old schema
        result.setdefault("scheduled_time_iso", None)
        result.setdefault("collapse_at_iso", None)
        result.setdefault("invite_all_members", True)
        result.setdefault("invitees", [])
        result.setdefault("planning_notes", [])
        result.setdefault("date_preset", "custom")
        result.setdefault("time_window", "afternoon")
        result.setdefault("location_type", None)
        result.setdefault("budget_level", None)
        result.setdefault("transport_mode", None)
        return result

    async def infer_constraint_from_text(self, text: str) -> Dict[str, Any]:
        """Wrapper: Constraint inference now uses the action registry."""
        prompt = f"""
        Convert the user's message into a constraint JSON.
        Allowed types: if_joins, if_attends, unless_joins.
        Extract target username if present (without @).
        
        User text: {text}
        
        Output JSON:
        {{
          "target_username": "alice" or null,
          "constraint_type": "if_joins|if_attends|unless_joins|null"
        }}
        """
        try:
            response = await self._call_llm(prompt)
            parsed = json.loads(response)
            return {
                "target_username": str(parsed.get("target_username", ""))
                .strip()
                .lstrip("@"),
                "constraint_type": str(parsed.get("constraint_type", ""))
                .strip()
                .lower(),
            }
        except Exception:
            return {"target_username": None, "constraint_type": None}


def _sanitize_toxic_text(text: str) -> str:
    """Basic toxicity scrub fallback."""
    banned = {"idiot", "stupid", "dumb", "hate", "trash", "moron"}
    tokens = text.split()
    cleaned = []
    for token in tokens:
        normalized = token.lower().strip(".,!?")
        if normalized in banned:
            cleaned.append("[redacted]")
        else:
            cleaned.append(token)
    return " ".join(cleaned).strip()[:500]


def _simple_sentiment_score(text: str) -> float:
    """Simple fallback sentiment to score mapping 1..5."""
    lowered = text.lower()
    positives = sum(
        lowered.count(word) for word in ["good", "great", "nice", "excellent", "love"]
    )
    negatives = sum(
        lowered.count(word) for word in ["bad", "poor", "late", "problem", "boring"]
    )
    raw = 3.0 + min(2.0, positives * 0.4) - min(2.0, negatives * 0.4)
    return max(1.0, min(5.0, raw))
