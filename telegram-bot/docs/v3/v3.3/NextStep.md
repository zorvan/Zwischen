
## The core problem in one sentence
the infrastructure was built for v3, but the experience still runs on v2 interaction patterns.

## What works correctly
The state machine, constraints, fragment mosaic, personal attendance mirror, and idempotency layer are all solid and v3-aligned. These are not the problem.

## The three critical gaps

### Gap 1 — the event is socially invisible between announcement and deadline.
Your vision: the event lives in the group, people talk about it, put stickers on it, hashtags form around it, gravity builds publicly. What exists: one announcement message in the group, then everything moves to private DM. The group chat goes quiet. Nobody can see what is forming. There is no hashtag on a forming event — hashtags only exists in event_memories (post-event). There is no reaction, no thread, no way for the group to orbit the event before it locks.
This is the most fundamental gap. The entire "living organism" metaphor requires group-visible social presence during the formation window. The code has none.

### Gap 2 — /plan and memory-as-input are orphaned.
start_meaning_formation() and get_prior_event_memories() exist and are architecturally correct. But /plan is a separate command that most users will never type. /organize_event — the default path — bypasses memory entirely and goes straight to the creation form. The v3 design principle ("memory is a coordination input, not an output") is violated at the most important moment: when someone decides to create an event.

### Gap 3 — the post-event mosaic arrives and stops.
The fragment mosaic gets posted to the group as a single bot message. That is correct for v3 — but the group has no way to continue building on it, react to it collectively, or have it referenced when the next event of that type is created through the normal path. It lands and disappears into chat history. The organism perishes silently rather than leaving something the group can feel.

## What needs to change
Three things, in priority order:

### 1. Give the forming event a group-chat presence.
When an event is proposed, post a live status card to the group that updates as people join — participant count, time remaining, who is interested. Let people react to that card with Telegram reactions. Store those reactions as social energy signals (not behavioral scores — just counts). Let the organizer optionally attach hashtags to the forming event. The event should feel like it is growing in the room, not in a database.

### 2. Collapse /plan and /organize_event into one flow.
The default creation path should surface prior memories first, always. Remove /plan as a separate command. Make start_meaning_formation() the entry point for all event creation. Users should never be able to skip past "here is what your group remembered last time" — not because it is forced, but because it is the first thing they see.

### 3. Make the mosaic a living artifact.
After the mosaic is posted, keep a reference to it in the group. When the next event of the same type is created, surface a fragment from that mosaic inline — not just in a DM. Let the group see the lineage. The fragment does not need to be long. One sentence from a prior event, quoted in the next event's announcement, is enough for the group to feel it has a history.

## What not to change
The infrastructure is good. The constraint system, state machine, memory service internals, and RBAC are all well-built. The problem is not in the services — it is in the surface layer: where interactions happen (DM vs group), what is visible when (nothing vs live card), and which flow users enter through (direct creation vs memory-first creation).
