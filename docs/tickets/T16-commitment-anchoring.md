# T16 — Commitment anchoring (client-side validation, single-use seals)

**Tier 2/3 · exploratory · area: chain**
**Depends on:** T15 (retention policy must exist first), T08 (wallet identity)
**Related:** T17 (Diewan interop)

## Why

The goal is verifiable commitments — that a group agreed something, that
someone showed up — **without** turning Zwischen into a public ledger of who
gathered with whom. Naive on-chain state would be the exact opposite of this
project's stated character (T15).

Client-side validation with single-use seals fits the constraint precisely:

- the chain holds only a **commitment** (a hash), never content
- the data proving the commitment lives **client-side**, held by participants
- once that data decays or is deleted, the commitment is an opaque value that
  reveals nothing and cannot be reconstructed
- a seal can be spent **once**, which is what makes a commitment binding
  rather than merely recorded

This is the same model Diewan uses, which is not a coincidence and is a strong
argument for it here (T17).

## Open questions — resolve before building

1. **What is worth committing to?** Candidates: an event locking (the group
   agreed), attendance confirmation, a memory being sealed. Fewer is better;
   each anchored fact is permanent by construction.
2. **Who holds the client-side data?** Every participant? The organizer? If
   participants hold it and all of them lose it, the commitment becomes
   unverifiable — which may be *correct* for this product (the memory decayed)
   but must be an intended outcome, not an accident.
3. **Is the chain ever authoritative?** Recommendation: **no.** PostgreSQL
   stays the system of record; anchors are optional attestations. A design
   where the chain is authoritative forces reorg handling into the domain and
   makes the product unusable offline.
4. **What happens with no chain at all?** Anchoring must be strictly optional.
   The coordination product has to work fully for users who never touch a
   wallet, or the ethical stance becomes conditional on participation in a
   crypto-economy.

## TON specifically

TON is the natural candidate given the Telegram footprint:

- TON Connect works inside Telegram Mini Apps — the same surface T08 targets
- Telegram Wallet is already in front of the user base
- low fees make per-event anchoring plausible

Worth checking against alternatives before committing: TON's native
primitives differ from the Bitcoin/RGB lineage where single-use seals and CSV
originate, so the seal construction may need adapting rather than porting. If
Diewan already has a working implementation, matching it matters more than
picking the theoretically best chain.

## Implementation shape (when the above is settled)

**Transactional outbox.** Never submit a transaction inside a database
transaction — it cannot be rolled back:

```
event locked
  -> INSERT INTO anchor_outbox (payload_hash, status='pending')   [same tx]
  -> COMMIT
  -> worker picks up pending rows, submits, records tx id
  -> worker watches for confirmations
  -> reorg -> re-submit
```

Also needed: idempotency across DB and chain (an anchor must not be submitted
twice for one event), key management (the service's own key, if it signs), and
a clear failure mode when the chain is unreachable — degrade, never block a
coordination action.

## Acceptance criteria

- [x] Written decision on questions 1–4 **before** any code (`docs/ANCHORING_DECISION.md`)
- [x] Anchoring fully optional; all features work with it disabled
- [x] No content on-chain, only commitments — verified by inspecting payloads
- [x] Outbox survives crash between commit and submit
- [x] A decayed memory leaves an unverifiable-but-harmless commitment,
      and that is tested
- [x] Chain unavailability degrades gracefully

Still open (Tier 3): the chain adapter and seal construction; see the
implementation notes in `docs/ANCHORING_DECISION.md`.

## Notes

Treat this as a spike first, not a feature. The valuable output of the first
pass is a written decision on what deserves permanence in a product whose
premise is forgetting.
