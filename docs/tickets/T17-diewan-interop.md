# T17 — Interop boundary with Diewan

**Tier 3 · exploratory · area: integration**
**Depends on:** T09 (API), T15 (retention policy), T16 (shared commitment model)

## Why

Diewan is a complementary project: an **Accountability Economy** that traces
mandates to the work done to fulfil them, by AI agents or any other actor.
Everything is registered and traced; it can operate offline, minimally
on-chain, using single-use seals and client-side validation.

Zwischen and Diewan are near-opposites by design, and that is the point:

| | Zwischen | Diewan |
|---|---|---|
| Premise | shared experience | accountability |
| Memory | decays deliberately | registered and traced |
| Default | store as little as possible | record the mandate chain |

The connection is plausible — a gathering *is* work done against some mandate,
and an accountability system needs evidence that something happened — but the
boundary has to be drawn carefully, because naive integration would import
Diewan's permanence into a product whose premise is forgetting.

## The core constraint

**Zwischen must not become a data source that defeats its own retention
policy.** If Diewan traces and retains what Zwischen deliberately lets decay,
then connecting them makes Zwischen's decay cosmetic — the data still exists,
just elsewhere.

Ways to hold the line:

- Zwischen exports **attestations**, never records. "A gathering occurred and
  these commitments were satisfied", not "these people met on this date".
- The user, not the system, initiates any export. Consent per event, not a
  standing feed.
- Zwischen's export carries the same decay semantics — an attestation about a
  decayed memory is unverifiable, and Diewan should be able to represent that
  honestly rather than treating it as missing data.

## What to explore

1. **Shared commitment format.** Both projects converge on single-use seals +
   CSV. If the seal construction is shared, an attestation produced by
   Zwischen is verifiable by Diewan with no bridge — this is the strongest
   version of the integration and the reason to align T16 with Diewan's
   existing implementation rather than inventing a parallel one.
2. **Shared identity?** Both need to know who an actor is. `user_identities`
   is provider-agnostic, and a wallet identity (T08) is portable between the
   two systems without either holding the other's user table. Prefer that over
   any account federation.
3. **Direction of flow.** Almost certainly Zwischen → Diewan only. A mandate
   in Diewan triggering coordination in Zwischen is imaginable but introduces
   a control dependency into a product that should stand alone.
4. **What is a "mandate" here?** An event has an organizer, participants and
   commitments (`commit_by`, `min_participants`, lock deadlines). That maps to
   a mandate structure fairly naturally — but only if the mapping is written
   down before code assumes it.

## Acceptance criteria (for the spike)

- [ ] Written statement of what may cross the boundary, and what may not
- [ ] Confirmation that Zwischen's retention policy still holds after export
- [ ] Decision on shared seal/commitment format, aligned with Diewan's
      existing implementation
- [ ] Zwischen works completely with no Diewan present — always
- [ ] Consent model defined: who authorizes an export, at what granularity

## Notes

This is the ticket most likely to be shaped by decisions made in Diewan rather
than here. The useful work now is **not** building a bridge — it is making
sure T15 and T16 do not foreclose one. Specifically: keep commitments
content-free, keep identity provider-agnostic, and keep anchoring optional.
Those three properties are what make a later connection possible without
compromising either project.
