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

        prompt = self._build_conflict_prompt(
            event, availability, notes or []
        )

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

    async def infer_constraint_from_text(self, text: str) -> Dict[str, Any]:
        """Infer structured constraint from free-form user text."""
        from ai.schemas import ConstraintInference, validate_llm_output

        prompt = f"""
        Convert the user's message into a scheduling constraint JSON.
        Allowed types: if_joins, if_attends, unless_joins.
        Extract target username if present (without @).
        Be concise and deterministic.

        User text:
        {text}

        Output JSON only:
        {{
          "constraint_type": "if_joins|if_attends|unless_joins",
          "target_username": "string or null",
          "confidence": 0.0,
          "sanitized_summary": "clean short summary"
        }}
        """

        # v3.5: Regex fallbacks removed per spec Section 2.4
        # LLM either succeeds or returns empty dict - no pattern matching fallbacks
        try:
            response = await self._call_llm(prompt)
            return validate_llm_output(
                ConstraintInference, response, fallback_factory=lambda: {}, logger=logger
            )
        except Exception:
            logger.warning("Constraint inference failed, no fallback available")
            return {}

    # v3.5: infer_feedback_from_text REMOVED per spec Section 3
    # Behavioral scoring violates project philosophy

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

            min_match = re.search(r"\b(?:minimum|min|threshold|at least)(?:\s+(?:to|of))?\s+(\d{1,3})\b", lowered)
            if min_match:
                patch["min_participants"] = int(min_match.group(1))

            target_match = re.search(r"\b(?:capacity|target|up to|fit)\s+(\d{1,3})\b", lowered)
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

            if "clear time" in lowered or "no time" in lowered or "time tbd" in lowered or "flexible" in lowered:
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
            elif any(token in lowered for token in ["park", "outdoor", "outside", "garden", "field"]):
                patch["location_type"] = "outdoor"
            elif any(token in lowered for token in ["cafe", "restaurant", "coffee shop", "diner"]):
                patch["location_type"] = "cafe"
            elif any(token in lowered for token in ["office", "workspace", "workplace", "meeting room"]):
                patch["location_type"] = "office"
            elif any(token in lowered for token in ["gym", "fitness", "workout place"]):
                patch["location_type"] = "gym"

            # Budget level detection
            if any(token in lowered for token in ["free", "no cost", "cheap", "budget"]):
                patch["budget_level"] = "free"
            elif any(token in lowered for token in ["low cost", "inexpensive", "affordable"]):
                patch["budget_level"] = "low"
            elif any(token in lowered for token in ["moderate", "mid-range", "medium cost"]):
                patch["budget_level"] = "medium"
            elif any(token in lowered for token in ["expensive", "premium", "high-end", "luxury"]):
                patch["budget_level"] = "high"

            # Transport mode detection
            if "walking" in lowered or "walk" in lowered:
                patch["transport_mode"] = "walk"
            elif any(token in lowered for token in ["public transit", "bus", "train", "metro", "subway"]):
                patch["transport_mode"] = "public_transit"
            elif any(token in lowered for token in ["driving", "drive", "car", "by car"]):
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
            target_participants = int(parsed.get("target_participants", max(min_participants, 5)))
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
                    inferred_constraints.append({
                        "constraint_type": ctype,
                        "target_username": target,
                        "note": note,
                    })

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
                valid_windows = {"early-morning", "morning", "afternoon", "evening", "night"}
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

    async def infer_group_mention_action(
        self,
        text: str,
        history: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> Dict[str, Any]:
        """Infer mention intent into a concrete action payload."""
        compact_history = (history or [])[-20:]
        prompt = f"""
        You are a Telegram group coordination assistant.
        Infer the best action from a message that mentioned the bot.

        Allowed action_type values:
        - opinion
        - organize_event
        - organize_event_flexible
        - status
        - event_details
        - suggest_time
        - constraint_add
        - join
        - confirm
        - cancel
        - lock
        - request_confirmations

        If action is unclear, use opinion.
        If event_id is unknown, set event_id to null.

        CONSTRAINT INFERENCE:
        When action_type is constraint_add, you MUST infer:
        - target_username: the person the constraint is about (without @)
        - constraint_type: "if_joins" (I'll come if X comes), "if_attends" (I'll come if X attends), or "unless_joins" (I won't go if X goes)
        Look for conditional language: "if", "unless", "only if", "as long as"
        Examples:
          "I'll come if @alice comes" → constraint_add, target_username="alice", constraint_type="if_joins"
          "I won't go unless @bob is there" → constraint_add, target_username="bob", constraint_type="unless_joins"
          "Count me in if @carol joins" → constraint_add, target_username="carol", constraint_type="if_joins"

        Mention text:
        {text}

        Recent chat history (newest last):
        {compact_history}

        Output JSON only:
        {{
          "action_type": "<see allowed list above>",
          "event_id": 123 or null,
          "target_username": "alice" or null,
          "constraint_type": "if_joins|if_attends|unless_joins|null",
          "assistant_response": "short response"
        }}
        """
        try:
            response = await self._call_llm(
                prompt,
                max_tokens=600,
                system=system if system is not None else MEDIATOR_SYSTEM,
            )
            parsed = json.loads(response)
            action_type = str(parsed.get("action_type", "opinion")).strip().lower()
            logger.debug(
                "LLM raw response: action_type=%s, event_id=%s, text=%s",
                action_type,
                parsed.get("event_id"),
                text[:100],
            )
            if action_type not in {
                "opinion",
                "organize_event",
                "organize_event_flexible",
                "status",
                "event_details",
                "suggest_time",
                "constraint_add",
                "join",
                "confirm",
                "cancel",
                "lock",
                "request_confirmations",
            }:
                action_type = "opinion"
            event_id = parsed.get("event_id")
            try:
                event_id = int(event_id) if event_id is not None else None
            except (TypeError, ValueError):
                event_id = None
            constraint_type = parsed.get("constraint_type")
            if constraint_type is not None:
                constraint_type = str(constraint_type).strip().lower()
                if constraint_type not in {"if_joins", "if_attends", "unless_joins"}:
                    constraint_type = None
            target_username = parsed.get("target_username")
            if target_username is not None:
                target_username = str(target_username).strip().lstrip("@")
                if not target_username:
                    target_username = None
            return {
                "action_type": action_type,
                "event_id": event_id,
                "target_username": target_username,
                "constraint_type": constraint_type,
                "assistant_response": str(parsed.get("assistant_response", "")).strip(),
            }
        except Exception:
            lowered = text.lower()
            fallback_action = "opinion"
            if (
                "organize" in lowered
                or "organise" in lowered
                or "create event" in lowered
                or "new event" in lowered
                or "plan event" in lowered
            ):
                if "flexible" in lowered:
                    fallback_action = "organize_event_flexible"
                else:
                    fallback_action = "organize_event"
            elif "status" in lowered:
                fallback_action = "status"
            elif "detail" in lowered:
                fallback_action = "event_details"
            elif "suggest" in lowered or "time" in lowered:
                fallback_action = "suggest_time"
            elif (
                "constraint" in lowered
                or " if " in lowered
                or "unless" in lowered
                or "only if" in lowered
                or "as long as" in lowered
            ):
                fallback_action = "constraint_add"
            elif (
                "request confirmation" in lowered
                or "confirm button" in lowered
                or "ask confirmations" in lowered
            ):
                fallback_action = "request_confirmations"
            elif "join" in lowered:
                fallback_action = "join"
            elif (
                "confirm" in lowered or "interested" in lowered or "interest" in lowered
            ):
                fallback_action = "confirm"
            elif "cancel" in lowered:
                fallback_action = "cancel"
            elif "lock" in lowered:
                fallback_action = "lock"

            # Basic event id extraction fallback
            event_id = None
            for token in text.split():
                if token.isdigit():
                    event_id = int(token)
                    break

            # Constraint type and target extraction for constraint_add
            fallback_constraint_type = None
            fallback_target_username = None
            if fallback_action == "constraint_add":
                # Detect constraint type
                if "unless" in lowered or "won't" in lowered or "won t" in lowered:
                    fallback_constraint_type = "unless_joins"
                elif " if " in lowered or "only if" in lowered or "as long as" in lowered:
                    fallback_constraint_type = "if_joins"
                elif "attend" in lowered:
                    fallback_constraint_type = "if_attends"
                else:
                    fallback_constraint_type = "if_joins"

                # Extract @username
                mention_match = re.search(r"@([A-Za-z][A-Za-z0-9_]{4,31})", text)
                if mention_match:
                    fallback_target_username = mention_match.group(1)

            logger.debug(
                f"LLM fallback inference: action={fallback_action}, event_id={event_id}, constraint_type={fallback_constraint_type}, target={fallback_target_username}, text={text[:100]}"
            )

            return {
                "action_type": fallback_action,
                "event_id": event_id,
                "target_username": fallback_target_username,
                "constraint_type": fallback_constraint_type,
                "assistant_response": "I inferred a best-effort action from your mention.",
            }

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


# v3.5: _sanitize_toxic_text and _simple_sentiment_score REMOVED
# These were only used by infer_feedback_from_text which violated project philosophy
