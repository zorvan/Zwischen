"""Unit tests for bot.common.safe_edit.

Every callback interaction now routes through safe_edit_message, so its
failure handling is on the hot path for the whole bot.
"""

import os
import sys
from datetime import timedelta

import pytest
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.common import safe_edit  # noqa: E402
from bot.common.safe_edit import safe_edit_message  # noqa: E402


class FakeQuery:
    """Minimal CallbackQuery stand-in recording calls and raising on cue."""

    def __init__(self, edit_effects=None, answer_effect=None):
        # edit_effects: list of exceptions (or None for success) per call
        self.edit_effects = list(edit_effects or [None])
        self.answer_effect = answer_effect
        self.edit_calls = []
        self.answer_calls = []

    async def edit_message_text(self, text, **kwargs):
        self.edit_calls.append((text, kwargs))
        effect = self.edit_effects.pop(0) if self.edit_effects else None
        if effect is not None:
            raise effect
        return True

    async def answer(self, text="", **kwargs):
        self.answer_calls.append((text, kwargs))
        if self.answer_effect is not None:
            raise self.answer_effect
        return True


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Keep flood-control retries instant."""

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(safe_edit.asyncio, "sleep", fake_sleep)


async def test_successful_edit_returns_true():
    query = FakeQuery()
    assert await safe_edit_message(query, "hello", parse_mode="HTML") is True
    assert query.edit_calls == [("hello", {"parse_mode": "HTML"})]


async def test_not_modified_is_absorbed():
    """The most common Telegram error must not escape the handler."""
    query = FakeQuery([BadRequest("Message is not modified")])
    assert await safe_edit_message(query, "same") is False
    assert query.answer_calls, "user should get an 'already up to date' notice"


async def test_deleted_message_is_absorbed():
    query = FakeQuery([BadRequest("Message to edit not found")])
    assert await safe_edit_message(query, "gone") is False


async def test_unexpected_bad_request_still_raises():
    """Genuine bugs must not be silently swallowed."""
    query = FakeQuery([BadRequest("Button_data_invalid")])
    with pytest.raises(BadRequest):
        await safe_edit_message(query, "boom")


async def test_retry_after_retries_once_and_succeeds():
    query = FakeQuery([RetryAfter(3), None])
    assert await safe_edit_message(query, "text") is True
    assert len(query.edit_calls) == 2


async def test_retry_after_gives_up_on_second_failure():
    query = FakeQuery([RetryAfter(3), RetryAfter(3)])
    assert await safe_edit_message(query, "text") is False
    assert len(query.edit_calls) == 2


async def test_retry_after_accepts_timedelta():
    """PTB may type retry_after as timedelta; float() alone would raise."""
    query = FakeQuery([RetryAfter(timedelta(seconds=2)), None])
    assert await safe_edit_message(query, "text") is True


async def test_retry_delay_is_capped():
    captured = {}

    async def capture_sleep(seconds):
        captured["seconds"] = seconds

    safe_edit.asyncio.sleep = capture_sleep
    query = FakeQuery([RetryAfter(99999), None])
    await safe_edit_message(query, "text")
    assert captured["seconds"] == safe_edit.MAX_RETRY_AFTER


async def test_timed_out_and_forbidden_are_absorbed():
    assert await safe_edit_message(FakeQuery([TimedOut()]), "t") is False
    assert await safe_edit_message(FakeQuery([Forbidden("blocked")]), "t") is False


async def test_failing_answer_does_not_mask_result():
    """A failed courtesy notification must not raise out of the helper."""
    query = FakeQuery(
        [BadRequest("Message is not modified")],
        answer_effect=BadRequest("Query is too old"),
    )
    assert await safe_edit_message(query, "same") is False
