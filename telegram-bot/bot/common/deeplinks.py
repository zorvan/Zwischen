"""Helpers for Telegram DM deep links."""


def build_start_link(bot_username: str | None, payload: str) -> str | None:
    """Build `t.me/<bot>?start=<payload>` link."""
    username = (bot_username or "").strip().lstrip("@")
    if not username:
        return None
    return f"https://t.me/{username}?start={payload}"
