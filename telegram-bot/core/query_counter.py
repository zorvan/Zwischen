"""Count SQL statements per unit of work.

One-off profiling finds today's N+1; a counter is what catches the next one.
Wrap a request, an update or a test in ``count_queries()`` and read the total
afterwards. Counting is scoped with a ContextVar, so concurrent tasks on the
same loop (two Telegram updates, two API requests) never share a count.

``install()`` registers one listener on every SQLAlchemy Engine in the
process, async engines included (they execute through a sync Engine
underneath). It is idempotent and costs one ContextVar lookup per statement
when nothing is counting.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger("coord_bot.queries")


@dataclass
class QueryCount:
    """Statements executed inside one ``count_queries()`` block."""

    label: str
    total: int = 0
    statements: list[str] = field(default_factory=list)
    keep_statements: bool = False

    def record(self, statement: str) -> None:
        self.total += 1
        if self.keep_statements:
            self.statements.append(statement)


_current: ContextVar[Optional[QueryCount]] = ContextVar("query_count", default=None)
_installed = False


def _before_cursor_execute(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    counter = _current.get()
    if counter is not None:
        counter.record(statement)


def install() -> None:
    """Start counting statements on every engine. Safe to call repeatedly."""
    global _installed
    if _installed:
        return
    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    _installed = True


@contextmanager
def count_queries(
    label: str = "",
    *,
    warn_above: Optional[int] = None,
    keep_statements: bool = False,
) -> Iterator[QueryCount]:
    """Count statements executed in this block (and tasks it awaits).

    With ``warn_above``, a block that exceeds the budget logs a warning
    naming the label, which is how a regression shows up in production logs.
    The label may be refined inside the block (``counter.label = ...``) when
    it is only known later, such as an HTTP route after routing.
    """
    install()
    counter = QueryCount(label=label, keep_statements=keep_statements)
    token = _current.set(counter)
    try:
        yield counter
    finally:
        _current.reset(token)
        if warn_above is not None and counter.total > warn_above:
            logger.warning(
                "Query budget exceeded",
                extra={
                    "label": counter.label,
                    "queries": counter.total,
                    "budget": warn_above,
                },
            )
