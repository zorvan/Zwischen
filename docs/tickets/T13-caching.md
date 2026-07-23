# T13 — Caching layer

**Tier 3 · performance · area: state**
**Depends on:** T03 (backend must be in use)

## Why

There is no cache today. Several read-heavy, near-static datasets are fetched
from PostgreSQL on every interaction:

| Data | Table | Changes |
|---|---|---|
| Group settings (timezone, live-card toggle, hashtag limit) | `group_settings` | rarely |
| User preferences and language | `user_preferences` | rarely |
| Locale strings | `locales/*.json` | at deploy |
| Group membership | `group_members` | occasionally |

`bot/common/i18n.py:21` already caches translations in a module-level dict —
fine, since they change only at deploy.

## What to do

Add cache helpers to `core/state.py` (`get`/`set` with TTL already exist).

**Cache-aside, short TTLs, explicit invalidation on write.** Not write-through
— the complexity is not justified at this data volume.

```python
async def get_group_settings(group_id: int) -> GroupSettings:
    key = f"group_settings:{group_id}"
    if (cached := await state.get(key)) is not None:
        return GroupSettings(**cached)
    settings = await load_from_db(group_id)
    await state.set(key, settings.as_dict(), ttl_seconds=300)
    return settings
```

Invalidate on the write path — a stale timezone silently produces wrong event
times, which is worse than a cache miss.

## Watch for

- **Do not cache anything authorization depends on** without deliberate
  thought. A stale `is_member` grants access after removal. Either skip the
  cache for authorization or use a very short TTL plus explicit invalidation
  on membership change.
- **Cache invalidation must be cross-instance.** Redis handles this naturally;
  a per-process cache does not — which is an argument for putting these in
  Redis rather than in-process memory even when a single instance is running.
- Do not cache anything covered by T15's retention rules without checking the
  TTL is shorter than the retention window. A cache that outlives the data it
  mirrors is a quiet violation of the decay policy.

## Acceptance criteria

- [ ] Group settings and user preferences served from cache on repeat reads
- [ ] Writes invalidate immediately, verified across two instances
- [ ] Authorization reads are either uncached or explicitly invalidated
- [ ] Cache hit rate observable
- [ ] Everything still correct with the cache disabled

## Notes for the target architecture

Measure before adding. T12 will show whether these reads actually cost
anything — at current volumes they may not, and an unnecessary cache is a
correctness risk with no upside.
