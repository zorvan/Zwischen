# T10 — Real-time updates to replace live-card editing

**Tier 2 · platform surface · area: realtime**
**Depends on:** T06, T09

## Why

Live cards are the product's most distinctive mechanic: an event card posted
to a group chat that updates in place as people join, showing "gravity
signals" (participant counts, hashtags, reactions). Implemented as Telegram
message editing — `event_live_cards` stores `chat_id` / `message_id` and
`live_card_service.py` calls `edit_message_text`.

There is no equivalent primitive on the web. The *intent* — a shared surface
that changes under everyone simultaneously — needs a different mechanism.

## What to do

### 1. Generalize the stored reference

`event_live_cards` currently holds Telegram coordinates. `MessageRef`
(`core/notifier.py`) was designed for the general case: `transport` +
opaque `channel_id` / `message_id`. Migrate the table so one event can have a
live card per transport — a Telegram message *and* a web subscription — since
during the Telegram-plus-web period it will have both.

### 2. Fan-out via Redis pub/sub

Redis is already in the stack (`core/state.py`, compose). On a state change
the service publishes one domain event; each transport subscribes:

```
participant joined
    -> publish  event:42:changed
        -> TelegramNotifier.edit(ref)      (existing behaviour)
        -> WebSocket broadcast to room 42  (new)
        -> mobile push for subscribed users
```

Publishing rather than calling each transport directly is what makes this
work across instances — the instance handling the join is not necessarily the
one holding the WebSocket connection.

### 3. WebSocket / SSE endpoint

SSE is enough if updates are server→client only, and is markedly simpler
(works over plain HTTP, reconnects natively). Choose WebSocket only if the
client needs to push.

### 4. Reconcile on reconnect

A client that was offline must resync, not replay. Send current state on
connect; the stream is an optimization over polling, never the source of
truth.

## Watch for

- **Edit storms.** A popular event mutating rapidly triggers an edit per
  change. Telegram rate-limits edits per chat. Debounce — coalesce changes
  within a short window into one render. This is worth doing for the Telegram
  path regardless of the web work; it is likely a current source of
  `RetryAfter`.
- `safe_edit.py` already handles "message is not modified"; `TelegramNotifier`
  treats it as success. Keep that — live cards frequently re-render identical
  text.

## Acceptance criteria

- [ ] A join updates the Telegram card and any connected web client
- [ ] Works when the joining request and the WebSocket land on different instances
- [ ] Client reconnect resyncs to current state
- [ ] Rapid changes are coalesced; no rate-limit errors under a burst
- [ ] An event with no Telegram card still fans out to web clients

## Notes for the target architecture

This is where the product's character either survives the platform move or
does not. The live card is not a notification — it is a shared object people
watch together. Whatever replaces it should feel like the same object seen
from a different window, not a feed item.
