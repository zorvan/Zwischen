# Optional commitment anchoring — Tier-2 decision record

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
and degrade without blocking. Chain and seal selection remains Tier 3.
