#!/usr/bin/env python3
"""Startup smoke tests.

Verifies that every top-level package actually imports and that the configured
database is reachable. The import checks matter: a broken import in a rarely
exercised handler otherwise only surfaces when a user triggers it in
production, because main.py imports everything at boot.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Every module main.py pulls in at boot. Previously this file printed a
# checkmark for these without importing them, so import errors went unnoticed.
BOT_MODULES = [
    "config.settings",
    "config.logging",
    "db.connection",
    "db.models",
    "db.url",
    "ai.llm",
    "ai.schemas",
    "ai.validator",
    "bot.commands.start",
    "bot.commands.event_creation",
    "bot.commands.events",
    "bot.commands.memory",
    "bot.commands.modify_event",
    "bot.commands.preferences",
    "bot.commands.language",
    "bot.handlers.event_panel",
    "bot.handlers.mentions",
    "bot.handlers.menus",
    "bot.handlers.membership",
    "bot.handlers.waitlist",
    "bot.common.i18n",
    "bot.common.scheduler",
    "bot.common.webhook",
    "bot.services.event_lifecycle_service",
    "bot.services.participant_service",
    "bot.services.waitlist_service",
]


@pytest.mark.parametrize("module_name", BOT_MODULES)
def test_module_imports(module_name: str) -> None:
    """Each bot module imports cleanly."""
    __import__(module_name)


def test_main_module_imports() -> None:
    """main.py imports without executing its entrypoint."""
    import main

    assert callable(main.main)


def test_logging_configures() -> None:
    """Logging setup runs against real settings without raising."""
    from config.logging import setup_logging
    from config.settings import settings

    assert setup_logging(settings) is not None


def _load_locales() -> tuple[dict, dict[str, dict]]:
    """Return (en, {name: translations}) for every locale file."""
    import json
    from pathlib import Path

    locales = Path(__file__).parent / "locales"
    en = json.loads((locales / "en.json").read_text(encoding="utf-8"))
    others = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(locales.glob("*.json"))
        if p.stem != "en"
    }
    return en, others


def test_locales_are_valid_json() -> None:
    """Translation files parse and English is the complete key set."""
    en, others = _load_locales()
    assert en, "en.json is empty"

    for name, data in others.items():
        extra = set(data) - set(en)
        assert not extra, f"{name}.json has keys missing from en.json: {sorted(extra)}"


def test_locales_are_complete() -> None:
    """Every locale covers every English key.

    Missing keys fall back to English rather than crashing, so drift is
    invisible at runtime -- it just silently ships English to non-English
    users. This is the only thing that catches it.
    """
    en, others = _load_locales()

    for name, data in others.items():
        missing = sorted(set(en) - set(data))
        assert not missing, (
            f"{name}.json is missing {len(missing)} keys: {missing[:10]}"
            f"{' ...' if len(missing) > 10 else ''}"
        )


def test_locale_placeholders_match() -> None:
    """Translations use exactly the placeholders the English string declares.

    A translation naming a placeholder the call site never passes renders the
    literal "{event_type}" to the user; one that drops a placeholder silently
    omits data, or reuses the wrong one and shows a wrong number.
    """
    import re

    en, others = _load_locales()
    placeholders = lambda s: set(re.findall(r"{(\w+)}", s))  # noqa: E731

    problems = []
    for name, data in others.items():
        for key, text in data.items():
            if key not in en:
                continue
            expected = placeholders(en[key])
            actual = placeholders(text)
            if expected != actual:
                problems.append(
                    f"{name}.json[{key}]: expected {sorted(expected)}, "
                    f"got {sorted(actual)}"
                )

    assert not problems, "Placeholder mismatches:\n" + "\n".join(problems)


@pytest.mark.integration
def test_database_connection() -> None:
    """The configured database accepts connections and answers a query.

    Skipped rather than failed when no database is reachable, so the suite
    stays runnable without infrastructure.
    """
    from db.connection import check_db_connection
    from db.url import normalize_db_url

    db_url = normalize_db_url(
        os.getenv(
            "DB_URL", "postgresql://coord_user:coord_pass@localhost:5432/coord_db"
        )
    )
    assert db_url

    ok, message = asyncio.run(check_db_connection(db_url))
    if not ok:
        pytest.skip(f"No database available: {message}")
    assert ok, message
