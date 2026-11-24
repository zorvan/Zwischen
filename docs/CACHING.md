# Read cache

`core/cache.py` is a cache-aside layer over the shared `StateBackend`. In any
multi-instance deployment that is Redis, so the cache and its invalidations
are shared by every instance. Nothing is cached per process.

## What is cached

| Namespace | Value | Read by | Invalidated by |
|---|---|---|---|
| `language` | a user's language preference (or none) | `get_language_preference`, `core.i18n.get_user_language` | `create_or_update_user_preferences`, `delete_user_preferences`, account erasure |
| `group_settings` | a group's live-card toggle, timezone, hashtag limit, lineage method | `LiveCardService`, via `get_group_settings` | `invalidate_group_settings` (call it from any code that writes `group_settings`; none does today) |

Full `UserPreference` rows are not cached. Callers mutate them in place to
write, so a cached copy would be a second source of truth.

## What is deliberately not cached

Membership, roles and every other input to authorization. A stale "is a
member" grants access after removal, and those reads are single
primary-key lookups anyway.

## Rules

- **TTL** `CACHE_TTL`, 300 s by default. Every retention window in
  `RETENTION_POLICY.md` is months long, and erasure invalidates immediately,
  so a cache entry cannot outlive the data it mirrors.
- **Invalidate twice.** A write deletes the entry at once and again after its
  transaction commits. Without the second delete, a reader on another
  instance could cache the pre-commit value between write and commit and pin
  it for a full TTL. `tests/test_cache.py` reproduces that race.
- **Fail open to the database.** If the backend errors, reads go to the
  database, and the failure is logged.
- **`CACHE_ENABLED=false`** turns the cache off. Every read then goes to the
  database, which is always correct.

## Observing it

`GET /health` includes `cache` with hits, misses and hit rate per namespace
for the process. A hit rate near zero means the cache is not paying for
itself and can be turned off.

Measure before relying on it. These are single-row
indexed reads, and `docs/QUERY_PROFILING.md` explains how to check whether
they register in production at all.
