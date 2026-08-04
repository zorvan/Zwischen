"""Transport-neutral localization from markup-free locale resources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOCALES_DIR = Path(__file__).parent.parent / "locales"
SUPPORTED_LANGS = {"en", "fa"}
_translations: dict[str, dict[str, str]] = {}


def load_locales() -> dict[str, dict[str, str]]:
    for lang in SUPPORTED_LANGS:
        if lang not in _translations:
            with (LOCALES_DIR / f"{lang}.json").open(encoding="utf-8") as source:
                _translations[lang] = json.load(source)
    return _translations


def t(key: str, lang: str = "en", **variables: Any) -> str:
    catalogs = load_locales()
    value = catalogs.get(lang, {}).get(key, catalogs["en"].get(key, "{" + key + "}"))
    for name, replacement in variables.items():
        value = value.replace("{" + name + "}", str(replacement))
    return value


async def get_user_language(
    user: Any, session: Any = None, user_id: int | None = None
) -> str:
    """Resolve the persisted preference first, then the client's hint."""
    if session is not None and user_id is not None:
        from db.models import UserPreference

        preference = await session.scalar(
            __import__("sqlalchemy")
            .select(UserPreference.language_preference)
            .where(UserPreference.user_id == user_id)
        )
        if preference in SUPPORTED_LANGS:
            return preference
    code = getattr(user, "language_code", "") or ""
    return "fa" if code.lower().startswith("fa") else "en"


__all__ = ["get_user_language", "load_locales", "t"]
