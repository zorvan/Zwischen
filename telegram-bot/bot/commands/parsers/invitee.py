#!/usr/bin/env python3
"""Parse invitee input for event creation."""

import re
from typing import Optional

TELEGRAM_HANDLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")


def parse_invitee_handles(raw_text: str) -> list[str]:
    """Parse comma-separated @handles and return normalized unique handles."""
    handles: list[str] = []
    seen: set[str] = set()
    tokens = [token.strip() for token in raw_text.split(",") if token.strip()]
    if not tokens:
        raise ValueError("No handles provided")

    for token in tokens:
        if not token.startswith("@"):
            raise ValueError("Handle must start with @")

        handle = token[1:]
        if not TELEGRAM_HANDLE_PATTERN.fullmatch(handle):
            raise ValueError("Invalid Telegram handle")

        normalized = f"@{handle.lower()}"
        if normalized not in seen:
            seen.add(normalized)
            handles.append(normalized)

    return handles


def parse_invitee_input(raw_text: str) -> tuple[list[str], bool]:
    """Parse invitee input and support @all shortcut."""
    normalized = raw_text.strip().lower()
    if normalized == "@all":
        return ["@all"], True
    return parse_invitee_handles(raw_text), False
