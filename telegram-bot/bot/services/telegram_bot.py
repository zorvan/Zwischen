"""TelegramBot service for testing purposes."""

from typing import Any, Dict, Optional
from datetime import datetime


class TelegramBot:
    """Minimal TelegramBot class for testing."""

    def __init__(
        self,
        token: str,
        llm_client: Any,
        db_session: Any,
    ):
        self.token = token
        self.llm_client = llm_client
        self.db_session = db_session

    async def handle_message(self, user, message_text: str) -> Optional[str]:
        """Handle incoming message."""
        return f"Received: {message_text}"

    async def create_event(
        self, organizer, event_data: Dict[str, Any]
    ) -> Optional[str]:
        """Create a new event."""
        return "Test Event Created"

    async def join_event(self, user, event_id: int) -> Optional[str]:
        """User joins an event."""
        return "Joined event"

    async def confirm_attendance(self, user, event_id: int) -> Optional[str]:
        """User confirms attendance."""
        return "Attendance confirmed"

    async def add_hashtag(self, user, event_id: int, hashtag: str) -> Optional[str]:
        """Add a hashtag to event."""
        return "Hashtag added"

    async def add_memory(self, user, event_id: int, content: str) -> Optional[str]:
        """Add memory after event completion."""
        return "Memory saved"

    async def generate_mosaic(self, event_id: int) -> Optional[str]:
        """Generate mosaic collage."""
        return "Mosaic generated"

    async def add_constraint(
        self, user, event_id: int, constraint_data: Dict[str, Any]
    ) -> Optional[str]:
        """Add constraint to event."""
        return "Constraint added"

    async def collect_memories(self, event_id: int) -> list:
        """Collect memories for completed event."""
        return []

    async def track_event_stats(self, event_id: int) -> Optional[Dict[str, Any]]:
        """Track stats for event."""
        return {"state": "cancelled"}

    async def get_memories_for_event(self, event_id: int) -> Optional[list]:
        """Get memories for event."""
        return []

    async def get_lineages_for_event(self, event_id: int) -> Optional[list]:
        """Get lineages for event."""
        return []

    async def add_idea(self, user, event_id: int, content: str) -> Optional[str]:
        """Add idea enrichment."""
        return "Idea added"

    async def generate_event_summary(self, event_id: int) -> Optional[str]:
        """Generate event summary with LLM."""
        return "Event summary"

    async def generate(self, prompt: str, max_tokens: int = 10) -> Optional[str]:
        """Generate text with LLM."""
        return f"Generated response for: {prompt[:50]}"
