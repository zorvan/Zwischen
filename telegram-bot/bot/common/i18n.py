#!/usr/bin/env python3
"""Internationalization (i18n) module for the Telegram bot.

Loads JSON translation files from the locales/ directory.
Supports variable substitution: {key} in strings.
Auto-detects language from user profile or defaults to 'en'.
"""
import json
from pathlib import Path
from typing import Any

LOCALES_DIR = Path(__file__).parent.parent.parent / "locales"

# Supported languages
SUPPORTED_LANGS = {"en", "fa"}

# Default language
DEFAULT_LANG = "en"

# Cache for loaded translations
_translations: dict[str, dict[str, str]] = {}


def _load_locale(lang: str) -> dict[str, str]:
    """Load a locale file and return key-value pairs."""
    if lang in _translations:
        return _translations[lang]

    locale_file = LOCALES_DIR / f"{lang}.json"
    if locale_file.exists():
        with open(locale_file, "r", encoding="utf-8") as f:
            _translations[lang] = json.load(f)
    else:
        _translations[lang] = {}

    return _translations[lang]


def set_language(lang: str) -> None:
    """Set the default language for translations."""
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    _load_locale(lang)


async def get_user_language(
    user: Any,
    session: Any = None,
    telegram_user_id: int = None,
    user_data: dict | None = None,
) -> str:
    """Detect language from user_data cache, DB preference, then Telegram profile.

    Priority:
    1. user_data['language'] cache (set when user changes language)
    2. DB language_preference (if session and telegram_user_id provided)
    3. Telegram user.language_code
    4. Default 'en'
    """
    # Check user_data cache first (set by /language command)
    if user_data and isinstance(user_data, dict):
        cached_lang = user_data.get("language")
        if cached_lang and cached_lang in SUPPORTED_LANGS:
            return cached_lang

    # Check DB preference first
    if session is not None and telegram_user_id is not None:
        from bot.common.user_preferences import get_language_preference

        db_lang = await get_language_preference(session, telegram_user_id)
        if db_lang and db_lang in SUPPORTED_LANGS:
            return db_lang

    # Fall back to Telegram profile language
    if hasattr(user, "language_code") and user.language_code:
        lang = user.language_code.lower()
        if lang.startswith("fa"):
            return "fa"
        if lang.startswith("en"):
            return "en"
    return DEFAULT_LANG


def t(key: str, lang: str | None = None, **variables: Any) -> str:
    """Translate a string key.

    Args:
        key: Translation key (e.g., "welcome_message")
        lang: Language code (auto-detected if None)
        **variables: Variables to substitute in the string (e.g., name="John")

    Returns:
        Translated string with variables substituted.

    Example:
        >>> t("greeting", name="Alice")
        "Hello, Alice!"
    """
    if lang is None:
        lang = DEFAULT_LANG

    translations = _load_locale(lang)
    text = translations.get(key)
    if text is None:
        text = _load_locale("en").get(key)
    if text is None:
        text = "{" + key + "}"

    # Escape Markdown special chars in the fallback key itself to prevent parse errors
    if text == "{" + key + "}":
        text = (
            text.replace("[", "\\[")
            .replace("]", "\\]")
            .replace("_", "\\_")
            .replace("*", "\\*")
            .replace("`", "\\`")
        )

    # Substitute variables: {name} -> Alice
    for var_key, var_value in variables.items():
        text = text.replace("{" + var_key + "}", str(var_value))

    return text


def init() -> None:
    """Load all available locales at startup."""
    for lang in SUPPORTED_LANGS:
        _load_locale(lang)
