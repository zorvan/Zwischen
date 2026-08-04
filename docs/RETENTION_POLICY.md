# Zwischen retention policy

Zwischen remembers enough to coordinate a gathering, then deliberately forgets
the social graph behind it. Retention is measured from event completion. Running
the decay job repeatedly has the same result as running it once.

| Data | Policy | Product reason |
|---|---|---|
| Users, identities, preferences, group membership | Keep while the account exists; erase on account deletion | Required for an account and its explicit memberships |
| Events and groups | Keep a minimal record | A title, time, state, and anonymous aggregate let a group remember that something happened |
| Event participants and waitlists | Delete after 180 days | Attendance must not become a durable social graph |
| Enrichments and constraints | Delete after 180 days | Member-authored detail has served its coordination purpose |
| State transitions | After 180 days remove actor and free-text reason; keep state/timestamp | Retains operational history without attribution |
| Event memories | At 180 days retain only the weave/tags; delete at 365 days | Memories decay from detail to summary to nothing |
| Logs | Delete after 90 days | Short operational diagnostic window only |
| Group event-type statistics | Keep aggregate counters while the group exists | Contains no individual attribution |
| Idempotency keys | Delete on their existing 24-hour expiry | Retry safety only |
| Live-card references | Delete with the event or when the referenced message/subscription disappears | Delivery metadata, not a memory |

Deleting an account removes identities, preferences, memberships,
participation, constraints, enrichments, and waitlist entries through database
cascades. Shared events remain; organizer and audit actor references become
anonymous. Backups age out on the infrastructure backup schedule and are not
restored to answer ordinary product queries.

No event content or identity is eligible for a permanent public ledger. If
optional anchoring is enabled later, only a content-free hash may leave the
system; after its source memory decays that hash is intentionally unverifiable.
