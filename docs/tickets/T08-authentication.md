# T08 — Authentication and sessions

**Tier 2 · platform surface · area: auth**
**Depends on:** T04, T07
**Blocks:** T09 (every endpoint), T16 (wallet-bound commitments)

## Why

There is no authentication in this codebase. Telegram supplied identity
implicitly on every update — `update.effective_user.id` was trusted because
Telegram had already authenticated the user. No web or mobile client gets that
for free.

`db/identity.py` already resolves any provider to a `User` and links multiple
credentials to one account. What is missing is the layer that *proves* a
caller is who they claim.

## Providers, in the order they matter here

### 1. Telegram Login Widget / Mini App `initData`

**Do this first.** It keeps existing users working and requires no new account
concept — the user is already known, the web client just has to prove it.

Both mechanisms are an HMAC over the payload keyed by the bot token. Validate
server-side; never trust `initData` unparsed. This gives every current user a
working web login on day one, with `provider='telegram'` resolving to the
account they already have.

### 2. Wallet (TON Connect)

TON is a natural fit given the Telegram footprint: TON Connect works inside
Telegram Mini Apps, and Telegram Wallet is already in front of the user base.
The mechanism is a signed challenge — server issues a nonce, wallet signs,
server verifies against the address.

This drops into `user_identities` with **no schema change**:

| provider | provider_user_id |
|---|---|
| `telegram` | `123456789` |
| `email` | `ada@example.com` |
| `wallet:ton` | `EQCD39VS5j…` |

Namespace the provider (`wallet:ton`, `wallet:eth`) so a second chain is
additive. Add the value to `AuthProvider` in `db/models.py` — it is a plain
`String(32)`, deliberately not a PG enum, so no migration is needed.

**Caveat worth deciding early:** a wallet address is a pseudonymous public
identifier. Linking one to a Zwischen account is a durable, externally
observable association — which sits in tension with this project's
data-minimization stance (see T15). Consider whether wallet linkage should be
opt-in per group, or held only as a commitment rather than an address.

### 3. Email / OAuth

Standard, lowest priority. Needed only for users with neither Telegram nor a
wallet.

## Session mechanics

- Short-lived access token + refresh token; mobile needs refresh, web can use
  an httpOnly cookie
- Store refresh tokens server-side so they can be revoked — Redis is available
- Rate-limit auth endpoints (`core/state.py` `hit_window`)
- Account linking flow: an authenticated user adds a provider via
  `identity.link_identity()`, which already raises `IdentityConflictError`
  rather than silently merging two populated accounts

## Acceptance criteria

- [ ] Telegram Mini App `initData` validated server-side; forged payloads rejected
- [ ] An existing Telegram user logs into the web app and sees their history
- [ ] TON Connect challenge/verify issues a session for a wallet-only user
- [ ] Linking a wallet to an existing Telegram account preserves all history
- [ ] Tokens revocable; expiry enforced
- [ ] Auth endpoints rate-limited

## Notes for the target architecture

Because identity resolution is already provider-agnostic and tested, this
ticket is mostly *verification* code — proving a claim — rather than account
management. That was the point of doing identity first.
