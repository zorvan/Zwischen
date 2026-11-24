"""Optional commitment anchoring (T16), per docs/ANCHORING_DECISION.md.

What leaves the system is a single 32-byte value::

    commitment = SHA-256("zwischen/anchor/v1" || 0x00 || salt || canonical(bundle facts))

The salt is 32 random bytes that exist only in the *proof bundle*. The
consenting clients hold the bundle; the server keeps a copy only briefly,
long enough for clients to fetch it, and the retention job then removes it.
With the bundle, anyone can recompute the commitment and check it against
the anchor. Without it, the commitment is an opaque value. It reveals
nothing, and the salt makes it impossible to confirm a guess about the facts.
That is the intended end state once a memory decays.

Rules enforced here and in AnchorService:

* Only an event lock is ever committed, and only when anchoring is enabled
  for the deployment *and* the event's group opted in.
* The facts in the bundle are minimal: the event's public id, the scheduled
  time, the lock time and the confirmed count. No names, internal ids,
  titles, descriptions or participant identities.
* PostgreSQL is authoritative. Enqueueing is a row in the same transaction
  as the lock (a transactional outbox). Submission happens later, from the
  worker. A failure anywhere in anchoring never blocks or fails a lock.
* Chains are behind ``AnchorSink``. No chain adapter ships yet: chain and seal
  selection is a later decision. ``InMemoryAnchorSink`` is the reference for
  the contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

DOMAIN_TAG = b"zwischen/anchor/v1"
BUNDLE_VERSION = 1
KIND_EVENT_LOCK = "event_lock"

#: Keys a proof bundle's facts may contain. Anything else is a bug.
ALLOWED_FACTS = frozenset({"event", "scheduled_time", "locked_at", "confirmed"})


def canonical(facts: dict[str, Any]) -> bytes:
    """Deterministic encoding: sorted keys, no whitespace, UTF-8."""
    unknown = set(facts) - ALLOWED_FACTS
    if unknown:
        raise ValueError(f"facts not allowed in a proof bundle: {sorted(unknown)}")
    return json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()


def commit(salt: bytes, facts: dict[str, Any]) -> str:
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    digest = hashlib.sha256(DOMAIN_TAG + b"\x00" + salt + canonical(facts))
    return digest.hexdigest()


@dataclass(frozen=True)
class ProofBundle:
    """What a consenting client keeps. Verifiable against the anchor."""

    kind: str
    salt_hex: str
    facts: dict[str, Any]
    commitment: str

    @classmethod
    def create(cls, facts: dict[str, Any]) -> "ProofBundle":
        salt = secrets.token_bytes(32)
        return cls(KIND_EVENT_LOCK, salt.hex(), dict(facts), commit(salt, facts))

    def as_json(self) -> dict[str, Any]:
        return {
            "v": BUNDLE_VERSION,
            "kind": self.kind,
            "salt": self.salt_hex,
            "facts": self.facts,
            "commitment": self.commitment,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ProofBundle":
        if data.get("v") != BUNDLE_VERSION:
            raise ValueError("unsupported bundle version")
        return cls(
            str(data["kind"]),
            str(data["salt"]),
            dict(data["facts"]),
            str(data["commitment"]),
        )


def verify(bundle: ProofBundle, anchored_commitment: str) -> bool:
    """True when the bundle opens the anchored commitment."""
    try:
        recomputed = commit(bytes.fromhex(bundle.salt_hex), bundle.facts)
    except ValueError:
        return False
    return hmac.compare_digest(recomputed, anchored_commitment) and hmac.compare_digest(
        recomputed, bundle.commitment
    )


def seal_id(idempotency_key: str) -> str:
    """The single-use seal an anchor spends.

    Derived from the idempotency key, so retrying the same anchor reuses the
    same seal and a sink that has already accepted it refuses a second
    spend. One logical anchor can therefore never land twice.
    """
    return hashlib.sha256(
        b"zwischen/seal/v1\x00" + idempotency_key.encode()
    ).hexdigest()


# -- the chain boundary -------------------------------------------------------


class AnchorUnavailable(RuntimeError):
    """The chain could not be reached. Retry later; never fail the caller."""


class SealAlreadySpent(RuntimeError):
    """The seal was spent before, so this anchor has already landed."""

    def __init__(self, tx_ref: str) -> None:
        super().__init__(tx_ref)
        self.tx_ref = tx_ref


@runtime_checkable
class AnchorSink(Protocol):
    """Where commitments go. Receives 32 bytes and a seal id, nothing else."""

    async def submit(self, commitment: bytes, seal: str) -> str:
        """Publish; return a transaction reference. Raise AnchorUnavailable
        when unreachable, SealAlreadySpent when the seal was used before."""
        ...

    async def status(self, tx_ref: str) -> str:
        """'pending', 'confirmed', or 'dropped' (reorged out / expired)."""
        ...


class InMemoryAnchorSink:
    """Reference sink for tests and local runs.

    Records exactly the bytes a real chain would receive, so tests can
    assert nothing but a commitment ever leaves.
    """

    def __init__(self) -> None:
        self.published: list[bytes] = []
        self._by_seal: dict[str, str] = {}
        self._status: dict[str, str] = {}
        self.available = True

    async def submit(self, commitment: bytes, seal: str) -> str:
        if not self.available:
            raise AnchorUnavailable("in-memory chain is down")
        if seal in self._by_seal:
            raise SealAlreadySpent(self._by_seal[seal])
        tx_ref = f"mem:{len(self.published)}"
        self.published.append(bytes(commitment))
        self._by_seal[seal] = tx_ref
        self._status[tx_ref] = "pending"
        return tx_ref

    async def status(self, tx_ref: str) -> str:
        if not self.available:
            raise AnchorUnavailable("in-memory chain is down")
        return self._status.get(tx_ref, "dropped")

    # test controls
    def confirm_all(self) -> None:
        for tx_ref in self._status:
            self._status[tx_ref] = "confirmed"

    def reorg(self, tx_ref: str) -> None:
        """Drop a transaction, freeing its seal, as a reorg would."""
        self._status[tx_ref] = "dropped"
        for seal, ref in list(self._by_seal.items()):
            if ref == tx_ref:
                del self._by_seal[seal]


_sink: Optional[AnchorSink] = None


def configure_sink(sink: Optional[AnchorSink]) -> None:
    global _sink
    _sink = sink


def get_sink() -> Optional[AnchorSink]:
    return _sink
