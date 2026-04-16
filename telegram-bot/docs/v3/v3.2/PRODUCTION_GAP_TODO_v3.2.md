# Production And Future-Proofing Gap Assessment
## Coordination Engine Bot: docs/v3 and docs/v3.2 vs current code

This document summarizes the most important gaps between the product described in `docs/v3/*` and `docs/v3.2/*` and the current implementation. It includes conceptual, philosophical, critical, and technical gaps, with a priority assessment aimed at production readiness and long-term maintainability.

## Priority Scale

- `P0` Release blocker. Must be fixed before production.
- `P1` Critical. Safe production use is weak without it.
- `P2` Important. Needed for resilience, correctness, or future-proofing.
- `P3` Valuable. Improves maintainability, observability, and polish.

## Executive Summary

The main risk is not just missing hardening. The bigger issue is that the codebase still contains overlapping product eras:

- v3/v3.2 philosophy says: no behavioral modeling, no reputational treatment, no synthetic meaning.
- parts of the code and schema still expose feedback, AI score, fragility framing, threshold legacy logic, and prototype-era operational patterns.

That means the code can regress philosophically even if individual features appear to work.

## P0

### 1. Remove or isolate legacy behavioral/reputation artifacts from the live domain model

Why:
- v3 and v3.2 explicitly reject reputation, behavioral inference, and scoring.
- The current schema and code still contain artifacts that contradict that stance.

Evidence:
- [db/schema.sql](/home/zorvan/Work/projects/Zwischen/telegram-bot/db/schema.sql) still defines `reputation`, `early_feedback`, user `reputation`, and AI recommendation types like `threshold_prediction`.
- [db/models.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/db/models.py) still contains `ai_score`, `Feedback`, `AILog`, and memory `tone_palette`.
- [bot/common/event_presenters.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/common/event_presenters.py#L340) still displays `AI Score`.
- [bot/commands/profile.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/commands/profile.py) still exposes feedback averages.
- [bot/handlers/feedback.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/handlers/feedback.py) keeps a rating flow that is conceptually out of sync with “memory not feedback” and “no behavioral interpretation”.

Risk:
- direct philosophical violation
- schema drift between docs and runtime
- future contributors will unknowingly build on deprecated concepts

TODO:
- remove deprecated behavioral tables/fields from the active schema path
- decide whether `Feedback` and `AILog` survive as strictly operational data or are removed entirely
- remove all user-facing “AI score”, average feedback, and similar computed judgment surfaces
- document one canonical allowed data model for v3.2

### 2. Introduce real schema migration management

Why:
- production systems cannot rely on `create_all()` plus ad hoc compatibility logic.

Evidence:
- [db/connection.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/db/connection.py) initializes schema via `Base.metadata.create_all`
- [db/schema.sql](/home/zorvan/Work/projects/Zwischen/telegram-bot/db/schema.sql) is explicitly out of sync with models and docs

Risk:
- silent drift across environments
- impossible rollback discipline
- unsafe production upgrades

TODO:
- adopt Alembic or equivalent
- generate baseline migration from current accepted v3.2 model
- add migrations for enum changes, waitlist changes, stats tables, and removal of deprecated artifacts
- block startup-time schema mutation in production

### 3. Fix broken or inconsistent waitlist implementation before relying on v3.2 resilience

Why:
- waitlist is one of the signature v3.2 features
- current implementation has correctness inconsistencies

Evidence:
- [db/models.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/db/models.py#L434) still requires `position`, but [bot/services/waitlist_service.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/services/waitlist_service.py) claims FIFO is purely `added_at` and does not set `position`
- [bot/handlers/waitlist.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/handlers/waitlist.py) calls `get_waitlist()` which does not exist in the service
- `handle_join_waitlist` expects a tuple from `add_to_waitlist()` though the service returns a single position integer

Risk:
- runtime failures in a core v3.2 path
- inability to trust event-level adaptation

TODO:
- align waitlist schema, service, and handlers to one contract
- remove `position` if FIFO is truly `added_at` only, or maintain it consistently
- add end-to-end tests for oversubscribe -> cancel -> offer -> accept/decline/expire

### 4. Reconcile materialization/privacy contract with actual emitted messages

Why:
- the docs treat message framing as a core product boundary

Evidence:
- [bot/common/event_presenters.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/common/event_presenters.py#L406) still contains “If one more person drops, this event collapses.”
- [bot/handlers/waitlist.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/handlers/waitlist.py) announces deadline extension to the group, which may be fine, but the surrounding logic is not clearly aligned to the v3.2 “private cancellation, public normal fill” contract
- multiple modules still use `threshold_attendance` language even though v3.2 distinguishes `min_participants` and `target_participants`

Risk:
- accidental guilt engineering
- philosophical drift in the most user-visible layer

TODO:
- define one authoritative materialization template source
- delete all legacy fragility/guilt wording
- audit every user-facing message against the v3 Materialization Test
- remove or quarantine old presenter/status formats that violate v3.2

## P1

### 5. Make production security/configuration explicit and complete

Why:
- production mode is partially implied, not fully modeled

Evidence:
- [config/settings.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/config/settings.py) does not actually define `webhook_url`, `webhook_port`, or `webhook_secret`, while [main.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/main.py) conditionally expects them
- secrets/config are thinly validated
- rate limiting is present but disabled in [main.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/main.py)

Risk:
- ambiguous deploy behavior
- accidental insecure or partial production startup

TODO:
- add explicit production config model with required env validation
- define webhook settings in `Settings`
- fail fast on incomplete production config
- enable and test rate limiting, webhook secret verification, and deploy-mode specific startup

### 6. Replace in-memory callback/idempotency assumptions with durable protection where required

Why:
- production bots receive retries, duplicate callbacks, restarts, and concurrent delivery

Evidence:
- [bot/common/callback_protection.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/common/callback_protection.py) tracks processed callbacks in per-process memory only
- callback protection helpers exist but are not clearly integrated across handlers
- idempotency is optional and only partially applied, for example [bot/commands/join.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/commands/join.py)

Risk:
- duplicate processing after restart
- replay vulnerabilities
- inconsistent behavior between polling and webhook modes

TODO:
- decide which paths require durable idempotency
- persist callback replay protection for sensitive actions
- apply idempotency uniformly to join/confirm/cancel/lock/waitlist acceptance
- add concurrency tests around duplicate Telegram delivery

### 7. Tighten event state and lifecycle ownership so there is truly one write path

Why:
- the code claims centralized write paths, but multiple handlers still do adjacent stateful work directly

Evidence:
- [bot/services/event_state_transition_service.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/services/event_state_transition_service.py) says it is the only allowed state mutation path
- handlers and commands still do nearby side effects and partial logic outside a single orchestration boundary

Risk:
- edge-case drift
- hard-to-reason state changes
- future regressions when new features are added

TODO:
- ensure every join/confirm/cancel/lock/waitlist transition flows through consistent service orchestration
- centralize materialization and stats updates
- formalize domain events or lifecycle hooks for side effects

### 8. Remove mixed legacy threshold model from active code paths

Why:
- future-proofing requires one clear domain vocabulary

Evidence:
- heavy use of `threshold_attendance` remains across commands, handlers, AI parsing, presenters, and services
- v3.2 conceptually uses `min_participants` plus `target_participants`

Risk:
- bugs from partially-updated semantics
- confusing future maintenance

TODO:
- define whether `threshold_attendance` is fully deprecated
- migrate all active paths to `min_participants` and `target_participants`
- leave a narrow compatibility layer only if old DB rows require it

## P2

### 9. Strengthen memory architecture to match the stated philosophy more rigorously

Why:
- memory is the most philosophically distinctive part of the product

Evidence:
- [db/models.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/db/models.py) and [bot/services/event_memory_service.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/services/event_memory_service.py) still use `tone_tag` and `tone_palette`, which risks moving from “receive fragments” toward system interpretation
- docs allow reflexive preference heuristics, but not analytical authorship

Risk:
- slow philosophical drift toward analysis/classification

TODO:
- decide whether tone metadata remains allowed under v3.2 philosophy
- if kept, restrict it to non-user-facing technical metadata and document why
- if not essential, remove it and simplify fragment structure
- add hard tests that no memory output includes invented interpretation

### 10. Improve webhook/worker queue architecture before scaling

Why:
- current async worker model is more proof-of-concept than production queueing

Evidence:
- [bot/common/webhook.py](/home/zorvan/Work/projects/Zwischen/telegram-bot/bot/common/webhook.py) uses token as URL path, keeps a global in-process queue, and exposes `submit_to_worker()` via `run_until_complete`

Risk:
- unsafe event loop behavior
- poor horizontal scaling story
- weak operational guarantees

TODO:
- remove sync wrapper patterns that call `run_until_complete` inside runtime paths
- decide whether background jobs remain in-process or move to dedicated worker infra
- add queue backpressure metrics and failure policy
- avoid token-derived routing identifiers in public paths

### 11. Add observability, SLOs, and production diagnostics

Why:
- future-proof systems need to be operable, not just correct

Evidence:
- docs mention Prometheus/SLO dashboards, but current implementation has only logging

TODO:
- add structured metrics for update latency, DB failures, callback failures, waitlist outcomes, memory DM send failures
- add health/readiness endpoints or equivalent deploy checks
- add correlation IDs for update handling and cross-service logging

### 12. Harden membership and permission model against edge cases

Why:
- current RBAC logic is thoughtful, but production safety needs clearer invariants

Evidence:
- membership can be inferred through same-chat presence and prior participation, which is useful, but should be explicitly validated against intended trust boundaries

TODO:
- write an explicit permission matrix for all operations
- verify organizer/admin exceptions remain narrow
- review whether implicit enrollment via chat presence is always desired in production

## P3

### 13. Clean up product language and module naming to reduce future confusion

Why:
- future-proofing is also conceptual clarity for maintainers

Evidence:
- modules, comments, and schema still mention v2/v3 mixed concepts
- docs and code use overlapping names for threshold, memory, feedback, and AI layers

TODO:
- rename deprecated concepts or mark them as legacy in code comments
- align docstrings with v3.2 language
- remove old TODO references that no longer match the current product

### 14. Formalize architecture boundaries

Why:
- the codebase is now large enough that implicit architecture will decay

TODO:
- define which modules own domain rules, orchestration, transport formatting, persistence, and AI integration
- add ADRs for memory, waitlist, and neutrality boundaries
- document “forbidden future changes” explicitly

### 15. Add release-grade non-functional test gates

Why:
- future-proofing depends on discipline, not only design

TODO:
- add contract tests for philosophy boundaries
- add integration tests for privacy boundaries
- add load/retry tests for duplicate delivery
- require test coverage on all message-template changes

## Recommended Execution Order

1. `P0`: remove/reconcile legacy behavioral domain artifacts
2. `P0`: introduce migrations and freeze the schema contract
3. `P0`: fix waitlist correctness and template/privacy mismatches
4. `P1`: make production config, webhook, replay protection, and idempotency real
5. `P1`: complete lifecycle centralization and threshold model cleanup
6. `P2`: harden memory, observability, and queue/runtime architecture
7. `P3`: cleanup naming, ADRs, and release gates

## Bottom Line

The product direction in v3 and v3.2 is coherent and distinctive.

The main gap is that the implementation is still a hybrid of:

- current philosophy
- older product assumptions
- prototype-grade operational patterns

To become production ready and future proof, the next phase should focus less on adding new features and more on:

- removing conceptual contradiction
- freezing the domain contract
- making stateful behavior operationally reliable
- making philosophy regressions impossible to reintroduce quietly
