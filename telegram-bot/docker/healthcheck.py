#!/usr/bin/env python3
"""Container healthcheck: verify the database is reachable.

A polling-mode bot exposes no HTTP port, so there is nothing to curl. The
database is the dependency whose loss silently degrades every handler, so that
is what we probe.

Exit 0 = healthy, exit 1 = unhealthy. Absent DB_URL is treated as healthy
because the bot is designed to start without one.
"""

import asyncio
import os
import sys

sys.path.insert(0, "/app")


def main() -> int:
    db_url = os.environ.get("DB_URL")
    if not db_url:
        return 0

    try:
        from db.connection import check_db_connection
        from db.url import normalize_db_url

        normalized = normalize_db_url(db_url)
        assert normalized is not None  # db_url is non-empty, checked above
        ok, message = asyncio.run(check_db_connection(normalized))
    except Exception as exc:  # import or driver failure is itself unhealthy
        print(f"healthcheck error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if not ok:
        print(f"unhealthy: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
