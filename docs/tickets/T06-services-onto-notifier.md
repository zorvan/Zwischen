# T06 — Move services onto the Notifier protocol

**Tier 1 · finish the transport split · area: domain**
**Depends on:** nothing hard; easier after T04
**Blocks:** T09 (web API), T10 (real-time), scheduler extraction in T01

## Why

`core/notifier.py` and `bot/common/telegram_notifier.py` exist and are tested.
**Nothing uses them yet.** 15 modules under `bot/services` and `bot/common`
still import `telegram` directly and call `bot.send_message` with Telegram
markup.

Until this lands, no domain service can be invoked from an HTTP handler — it
needs a `Bot` it will not have.

## Current state

Modules importing `telegram` (from the Phase-2 survey):

**Services:** `live_card_service`, `event_memory_service`,
`event_materialization_service`, `event_lifecycle_service`, `waitlist_service`

**Common:** `keyboards`, `menus`, `materialization`, `fallbacks`,
`event_notifications`, `webhook`, `safe_edit`, `weekly_digest`, `scheduler`,
`rate_limiter`

Split them: `webhook`, `safe_edit`, `keyboards`, `menus` are *legitimately*
Telegram — they are transport. The rest are domain and should not be.

## What to do

Replace `Bot` injection with `Notifier` injection:

```python
# before
class WaitlistService:
    def __init__(self, session: AsyncSession, bot: Bot): ...
    await self.bot.send_message(chat_id=telegram_user_id, text=..., reply_markup=markup)

# after
class WaitlistService:
    def __init__(self, session: AsyncSession, notifier: Notifier): ...
    await self.notifier.send(
        Recipient.user(user_id),
        Message(text, [[Action(label, "wl:accept:42")]]),
    )
```

Construct `TelegramNotifier(bot, session)` once at the composition root
(`main.py`) and pass it down. Tests use `NullNotifier`, which records sends —
no mock bot needed.

### Keyboard builders

`bot/common/keyboards.py` and `menus.py` return `InlineKeyboardMarkup`. Add
parallel builders returning `list[list[Action]]`, and let `TelegramNotifier`
render. The callback-data strings stay identical, so `main.py`'s routing table
and every existing handler pattern keep working — the wire format does not
change, only who constructs it.

### Live cards

`live_card_service.py` (578 lines) is the hardest: it stores `chat_id` /
`message_id` in `event_live_cards` and edits in place. `MessageRef` was
designed for this — `transport` + opaque `channel_id`/`message_id`. Migrating
that table to store a `MessageRef` shape is the bridge to T10. Consider doing
this module last, or as part of T10.

## Acceptance criteria

- [ ] `grep -rl "^from telegram" bot/services/` returns nothing
- [ ] Domain modules in `bot/common/` likewise
- [ ] A test constructs a service with `NullNotifier` and asserts on
      `notifier.sent` — no `Bot`, no mock
- [ ] Telegram behaviour unchanged: same text, same buttons, same callback data
- [ ] Lifecycle suite green

## Notes for the target architecture

The test in `tests/test_notifier.py` asserting `core/` never imports
`telegram` is the guardrail — keep it. A single stray import re-couples the
domain and forces a web process to install the bot library to send a
notification.

Once this is done, a second `Notifier` implementation (WebSocket, push, or the
"nothing" notifier for a headless worker) is additive.
