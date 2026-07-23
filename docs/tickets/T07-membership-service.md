# T07 — Membership service over `group_members`

**Tier 1 · finish the identity migration · area: domain**
**Depends on:** T04 (partially — can start in parallel)
**Blocks:** T09 (authorization for the API)

## Why

`group_members` was created and backfilled by the expand migration. **Nothing
reads it.** Membership is still answered by two mechanisms that cannot survive
outside Telegram:

1. `groups.member_list` — a JSON array of Telegram ids. Cannot carry a role,
   cannot be joined against, cannot be indexed usefully.
2. `bot/common/rbac.py:39-53` — `check_group_membership()` falls back to
   **asking the Telegram API who is in the chat**:

```
4. Final fallback: query Telegram API for actual group membership
```

A web or mobile client has no such oracle. This is the last place where
Telegram is load-bearing for authorization.

## What to do

### 1. `bot/services/membership_service.py`

The single read/write path for membership:

- `is_member(group_id, user_id) -> bool`
- `get_role(group_id, user_id) -> GroupMemberRole | None`
- `add_member(group_id, user_id, role=member)`
- `remove_member(...)` — set `status='removed'`, do not delete; history matters
- `list_members(group_id, status=active)`

`GroupMemberRole` and `GroupMemberStatus` already exist in `db/models.py`.

### 2. Rewrite `rbac.check_group_membership()` on top of it

Delete the Telegram API fallback. Keep the "proven member by participation"
inference **only** as a backfill on join, not as a live lookup — it should
write a `group_members` row rather than re-deriving the answer every call.
That also removes a network round-trip from a hot path.

### 3. Keep `group_members` current from Telegram events

`bot/handlers/membership.py` (`track_group_members`) already observes group
activity. Point it at the service so new members are recorded as they appear.
Handle leave/kick events too — currently nothing removes anyone.

### 4. Decide the role model

The backfill assigned everyone `member` deliberately: group-level roles were
not derivable from the old data, and event organizers are an *event* role, not
a group one. Before the web app has an admin UI, decide:

- who can create events in a group
- who can add or remove members
- whether a Telegram chat admin maps to `admin` here (it can be synced, but
  that reintroduces a Telegram dependency — better as a one-time import)

### 5. Drop `member_list` (in T05)

## Acceptance criteria

- [ ] No Telegram API call in any authorization path
- [ ] `is_member` answers correctly for a user with no Telegram identity
- [ ] Joining a group via the bot writes a `group_members` row
- [ ] Leaving/being removed updates `status`
- [ ] `rbac.py` has no `bot` parameter for membership checks
- [ ] Tests cover: member, non-member, removed member, web-only user

## Notes for the target architecture

This is the authorization foundation for T09 — every API endpoint will ask
"is this user in this group, and in what role". Getting the role model right
now is cheaper than retrofitting it once endpoints depend on it.
