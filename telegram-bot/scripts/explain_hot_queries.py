#!/usr/bin/env python3
"""EXPLAIN every hot query and report the index the planner chose (T12).

    DB_URL=postgresql://... python scripts/explain_hot_queries.py [--analyze]
        [--event-id N] [--group-id N] [--user-id N]

Without --analyze it only plans, so it is safe against production. With
--analyze it executes each (read-only) query and reports timing too.
Exit status is 1 if any query misses its intended index.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import get_session  # noqa: E402
from db.hot_queries import HOT_QUERIES, explain_indexes  # noqa: E402
from db.url import normalize_db_url  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--event-id", type=int, default=1)
    parser.add_argument("--group-id", type=int, default=1)
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()

    url = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("Set DB_URL", file=sys.stderr)
        return 2
    params = {
        "event_id": args.event_id,
        "group_id": args.group_id,
        "user_id": args.user_id,
    }
    misses = 0
    normalized = normalize_db_url(url)
    if not normalized:
        print("DB_URL is not a PostgreSQL URL", file=sys.stderr)
        return 2
    async with get_session(normalized) as session:
        for query in HOT_QUERIES:
            used, plan = await explain_indexes(
                session, query, params, analyze=args.analyze
            )
            ok = bool(used & set(query.indexes))
            misses += not ok
            timing = ""
            if args.analyze:
                timing = f"  {plan[0].get('Execution Time', 0):.2f} ms"
            print(
                f"{'OK  ' if ok else 'MISS'} {query.name}: "
                f"{', '.join(sorted(used)) or 'sequential scan'}{timing}"
            )
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
