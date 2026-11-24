"""Per-update SQL query budget for the Telegram bot.

Wraps every update in ``core.query_counter.count_queries`` so an update that
issues more statements than ``QUERY_BUDGET`` logs a warning naming the update
kind. That warning is the regression signal for N+1 patterns in production.
"""

from __future__ import annotations

from typing import Any, Awaitable

from telegram import Update
from telegram.ext import SimpleUpdateProcessor

from core.query_counter import count_queries


def describe_update(update: object) -> str:
    """A low-cardinality label: the command or callback prefix, never content."""
    if not isinstance(update, Update):
        return type(update).__name__
    if update.callback_query and update.callback_query.data:
        data = update.callback_query.data
        for separator in (":", "_"):
            if separator in data:
                return f"callback:{data.split(separator, 1)[0]}"
        return f"callback:{data}"
    message = update.effective_message
    if message and message.text and message.text.startswith("/"):
        return f"command:{message.text.split()[0].split('@')[0]}"
    return "message"


class QueryBudgetUpdateProcessor(SimpleUpdateProcessor):
    """Same scheduling as the default processor, with a query count per update."""

    def __init__(self, max_concurrent_updates: int, budget: int) -> None:
        super().__init__(max_concurrent_updates)
        self.budget = budget

    async def do_process_update(
        self, update: object, coroutine: "Awaitable[Any]"
    ) -> None:
        with count_queries(describe_update(update), warn_above=self.budget):
            await coroutine
