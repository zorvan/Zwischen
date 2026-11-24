# Optional commitment anchoring — decision record

This is a spike decision, not authorization to deploy chain writes.

1. Only an event lock may be committed, and only after every affected group
   explicitly opts in. Attendance and memories are never committed.
2. The consenting clients hold the proof bundle. Losing every copy makes the
   commitment unverifiable, which is the intended consequence of decay.
3. PostgreSQL remains authoritative. An anchor is an optional attestation and
   never gates locking, joining, or any other coordination operation.
4. With anchoring disabled or a chain unavailable, every feature behaves
   identically except that no attestation is produced.

Any implementation must use a transactional outbox, contain only a salted
commitment hash (no IDs, addresses, titles, timestamps, or participant data),
and degrade without blocking. Chain and seal selection is still to be decided.

## Implementation (spike)

Built to the rules above, with no chain adapter yet:

- `core/anchoring.py`: the commitment is
  `SHA-256("zwischen/anchor/v1" ‖ 0x00 ‖ salt ‖ canonical facts)`, using a
  32-byte random salt. The facts are fixed to the event's public id, its
  scheduled time, the lock time and the confirmed count. Any other key is
  rejected. A proof bundle holds the salt and facts and opens the commitment.
  The seal an anchor spends is derived from its idempotency key. A retry
  therefore reuses the seal, and a sink that already accepted it refuses
  a second spend.
- `AnchorSink` is the chain boundary. It receives 32 bytes and a seal id,
  nothing else. `InMemoryAnchorSink` is the reference implementation of the
  contract. A TON (or other) adapter plugs in through
  `core.anchoring.configure_sink`. Until one is registered, enabled anchoring
  only fills the outbox, and retention empties it.
- Outbox: `anchor_outbox` rows are written in the lock's transaction, inside
  a savepoint, so an anchoring failure can never abort the lock. The scheduler
  worker submits due rows, records the transaction reference, polls for
  confirmation, backs off exponentially (up to an hour, then gives up after
  12 attempts) and resubmits after a reorg. Rows are claimed with
  `SKIP LOCKED`.
- Opt-in: `ANCHORING_ENABLED=true` for the deployment, **and**
  `group_settings.anchoring_enabled` for each group. Both default to off.
- Clients fetch the bundle from `GET /events/{id}/anchor` (members only). The
  server keeps its copy for 7 days after confirmation and deletes the anchor
  row after 30 (`RETENTION_POLICY.md`). After that only clients that kept the
  bundle can open the commitment.

Each acceptance criterion has a test in `tests/test_anchoring.py`.
Still open: choosing the chain and seal construction (TON's primitives differ
from the Bitcoin/RGB lineage that single-use seals come from), and how a Mini
App client stores bundles.
