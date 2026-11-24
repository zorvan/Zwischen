"""T16: optional, content-free commitment anchoring.

One test per acceptance criterion, plus the commitment primitives.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select

from bot.services.anchor_service import AnchorService
from core.anchoring import (
    InMemoryAnchorSink,
    ProofBundle,
    canonical,
    commit,
    seal_id,
    verify,
)
from db.connection import get_session
from db.identity import resolve_telegram_user
from db.models import (
    AnchorOutbox,
    Event,
    EventParticipant,
    Group,
    GroupSettings,
    ParticipantStatus,
)

FACTS = {
    "event": "5b0c3a52-0000-4000-8000-000000000001",
    "scheduled_time": "2026-12-01T19:00:00+00:00",
    "locked_at": "2026-11-30T10:00:00+00:00",
    "confirmed": 4,
}


# -- primitives -----------------------------------------------------------------


def test_bundle_opens_its_commitment_and_nothing_else() -> None:
    bundle = ProofBundle.create(FACTS)
    assert verify(bundle, bundle.commitment)
    assert verify(ProofBundle.from_json(bundle.as_json()), bundle.commitment)

    tampered = ProofBundle(
        bundle.kind, bundle.salt_hex, {**FACTS, "confirmed": 5}, bundle.commitment
    )
    assert not verify(tampered, bundle.commitment)
    assert not verify(bundle, ProofBundle.create(FACTS).commitment)


def test_commitment_reveals_nothing_without_the_salt() -> None:
    # Same facts, different salts: unlinkable commitments. And knowing the
    # facts does not let anyone confirm a guess without the salt.
    first, second = ProofBundle.create(FACTS), ProofBundle.create(FACTS)
    assert first.commitment != second.commitment
    guess = commit(secrets.token_bytes(32), FACTS)
    assert guess not in {first.commitment, second.commitment}


def test_bundle_rejects_identifying_facts() -> None:
    for key in ("title", "participants", "user_id", "group_name"):
        with pytest.raises(ValueError):
            canonical({**FACTS, key: "x"})


def test_seal_is_stable_per_anchor_and_distinct_across() -> None:
    assert seal_id("event_lock:a:1") == seal_id("event_lock:a:1")
    assert seal_id("event_lock:a:1") != seal_id("event_lock:a:2")


# -- integration ---------------------------------------------------------------


async def _locked_event(url: str, *, opted_in: bool, offset: int) -> int:
    async with get_session(url) as session:
        group = Group(
            telegram_group_id=-1_005_000_000_000 - offset, group_name="Secret"
        )
        session.add(group)
        await session.flush()
        session.add(GroupSettings(group_id=group.group_id, anchoring_enabled=opted_in))
        organizer = await resolve_telegram_user(
            session, 5_000_000_000 + offset, display_name="Organizer Name"
        )
        event = Event(
            group_id=group.group_id,
            event_type="dinner",
            title="Mina's birthday dinner",
            description="Secret surprise",
            state="confirmed",
            version=0,
            organizer_user_id=organizer.user_id,
            scheduled_time=datetime(2026, 12, 1, 19, tzinfo=timezone.utc),
            min_participants=1,
        )
        session.add(event)
        await session.flush()
        session.add(
            EventParticipant(
                event_id=event.event_id,
                user_id=organizer.user_id,
                status=ParticipantStatus.confirmed,
            )
        )
        await session.commit()
        return int(event.event_id)


async def _lock(url: str, event_id: int) -> None:
    from bot.services.event_state_transition_service import (
        EventStateTransitionService,
    )

    async with get_session(url) as session:
        event = await session.get(Event, event_id)
        organizer = event.organizer_user_id
        _, moved = await EventStateTransitionService(session).transition(
            event_id=event_id,
            target_state="locked",
            actor_user_id=organizer,
            source="test",
        )
        assert moved
        await session.commit()


async def _outbox(url: str) -> list[AnchorOutbox]:
    async with get_session(url) as session:
        return list((await session.execute(select(AnchorOutbox))).scalars())


@pytest.fixture
def anchoring_on(monkeypatch: pytest.MonkeyPatch) -> None:
    import config.settings as settings_module

    monkeypatch.setattr(settings_module.settings, "anchoring_enabled", True)


@pytest.mark.integration
async def test_disabled_anchoring_changes_nothing(test_db_url: str) -> None:
    """Deployment switch off: locking works and writes no outbox row."""
    event_id = await _locked_event(test_db_url, opted_in=True, offset=1)
    await _lock(test_db_url, event_id)
    assert await _outbox(test_db_url) == []
    async with get_session(test_db_url) as session:
        assert (await session.get(Event, event_id)).state == "locked"


@pytest.mark.integration
async def test_group_must_opt_in(test_db_url: str, anchoring_on: None) -> None:
    event_id = await _locked_event(test_db_url, opted_in=False, offset=2)
    await _lock(test_db_url, event_id)
    assert await _outbox(test_db_url) == []


@pytest.mark.integration
async def test_only_a_commitment_leaves_the_system(
    test_db_url: str, anchoring_on: None
) -> None:
    event_id = await _locked_event(test_db_url, opted_in=True, offset=3)
    await _lock(test_db_url, event_id)
    sink = InMemoryAnchorSink()
    async with get_session(test_db_url) as session:
        counts = await AnchorService(session).run_worker_once(sink)
        await session.commit()
    assert counts["submitted"] == 1

    [payload] = sink.published
    assert len(payload) == 32, "the chain receives a 32-byte hash and nothing else"
    for secret in (b"Mina", b"birthday", b"Secret", b"Organizer", b"dinner"):
        assert secret not in payload
    [row] = await _outbox(test_db_url)
    assert payload.hex() == row.commitment
    # The bundle held for clients opens it, and holds no identities either.
    bundle = ProofBundle.from_json(row.bundle)
    assert verify(bundle, payload.hex())
    assert set(bundle.facts) == {"event", "scheduled_time", "locked_at", "confirmed"}


@pytest.mark.integration
async def test_outbox_survives_crash_between_commit_and_submit(
    test_db_url: str, anchoring_on: None
) -> None:
    event_id = await _locked_event(test_db_url, opted_in=True, offset=4)
    await _lock(test_db_url, event_id)
    # "Crash": the process that locked is gone; nothing in memory survives.
    # A fresh worker, with a fresh sink, finds the committed row.
    sink = InMemoryAnchorSink()
    async with get_session(test_db_url) as session:
        assert (await AnchorService(session).run_worker_once(sink))["submitted"] == 1
        await session.commit()

    # Crash *after* submit but before the tx ref was recorded: the retry
    # spends the same seal, the sink refuses, and the worker adopts the
    # existing transaction instead of anchoring twice.
    async with get_session(test_db_url) as session:
        row = await session.scalar(select(AnchorOutbox))
        row.status, row.tx_ref = "pending", None
        await session.commit()
    async with get_session(test_db_url) as session:
        await AnchorService(session).run_worker_once(sink)
        await session.commit()
    assert len(sink.published) == 1
    [row] = await _outbox(test_db_url)
    assert row.status == "submitted" and row.tx_ref == "mem:0"

    sink.confirm_all()
    async with get_session(test_db_url) as session:
        assert (await AnchorService(session).run_worker_once(sink))["confirmed"] == 1
        await session.commit()


@pytest.mark.integration
async def test_chain_unavailable_degrades_and_recovers(
    test_db_url: str, anchoring_on: None
) -> None:
    sink = InMemoryAnchorSink()
    sink.available = False
    event_id = await _locked_event(test_db_url, opted_in=True, offset=5)
    await _lock(test_db_url, event_id)  # the lock itself is unaffected
    async with get_session(test_db_url) as session:
        counts = await AnchorService(session).run_worker_once(sink)
        await session.commit()
    assert counts["deferred"] == 1
    [row] = await _outbox(test_db_url)
    assert row.status == "pending" and row.attempts == 1 and row.last_error
    assert row.next_attempt_at > datetime.now(timezone.utc)

    sink.available = True
    later = datetime.now(timezone.utc) + timedelta(hours=2)
    async with get_session(test_db_url) as session:
        assert (await AnchorService(session).run_worker_once(sink, now=later))[
            "submitted"
        ] == 1
        await session.commit()


@pytest.mark.integration
async def test_reorg_resubmits_with_the_same_seal(
    test_db_url: str, anchoring_on: None
) -> None:
    event_id = await _locked_event(test_db_url, opted_in=True, offset=6)
    await _lock(test_db_url, event_id)
    sink = InMemoryAnchorSink()
    async with get_session(test_db_url) as session:
        await AnchorService(session).run_worker_once(sink)
        await session.commit()
    sink.reorg("mem:0")
    async with get_session(test_db_url) as session:
        counts = await AnchorService(session).run_worker_once(sink)
        await session.commit()
    assert counts["requeued"] == 1 and counts["submitted"] == 1
    assert sink.published[0] == sink.published[1]


@pytest.mark.integration
async def test_enqueue_failure_never_blocks_the_lock(
    test_db_url: str, anchoring_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.anchoring as anchoring

    def broken(facts: dict[str, Any]) -> ProofBundle:
        raise RuntimeError("bundle construction failed")

    monkeypatch.setattr(anchoring.ProofBundle, "create", staticmethod(broken))
    event_id = await _locked_event(test_db_url, opted_in=True, offset=7)
    await _lock(test_db_url, event_id)
    async with get_session(test_db_url) as session:
        assert (await session.get(Event, event_id)).state == "locked"
    assert await _outbox(test_db_url) == []


@pytest.mark.integration
async def test_decayed_memory_leaves_harmless_unverifiable_commitment(
    test_db_url: str, anchoring_on: None
) -> None:
    from bot.services.retention_service import RetentionService

    event_id = await _locked_event(test_db_url, opted_in=True, offset=8)
    await _lock(test_db_url, event_id)
    sink = InMemoryAnchorSink()
    async with get_session(test_db_url) as session:
        await AnchorService(session).run_worker_once(sink)
        await session.commit()
    sink.confirm_all()
    async with get_session(test_db_url) as session:
        await AnchorService(session).run_worker_once(sink)
        await session.commit()
    [row] = await _outbox(test_db_url)
    client_copy = ProofBundle.from_json(row.bundle)
    anchored = sink.published[0].hex()

    # Past the bundle window the server forgets the salt...
    async with get_session(test_db_url) as session:
        await RetentionService(session).decay(now=row.confirmed_at + timedelta(days=8))
        await session.commit()
    [row] = await _outbox(test_db_url)
    assert row.bundle is None
    # ...past the row window it forgets the anchor existed at all.
    async with get_session(test_db_url) as session:
        later = row.confirmed_at + timedelta(days=31)
        await RetentionService(session).decay(now=later)
        assert (await RetentionService(session).overdue(now=later))["anchor_rows"] == 0
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(AnchorOutbox)) == 0

    # The chain still holds the commitment. Only a client that kept the
    # bundle can open it; anyone else, the server included, cannot, even
    # with every remaining fact about the event.
    assert verify(client_copy, anchored)
    async with get_session(test_db_url) as session:
        event = await session.get(Event, event_id)
        reconstructed = {
            "event": str(event.public_id),
            "scheduled_time": client_copy.facts["scheduled_time"],
            "locked_at": client_copy.facts["locked_at"],
            "confirmed": client_copy.facts["confirmed"],
        }
    for _ in range(100):
        assert commit(secrets.token_bytes(32), reconstructed) != anchored


@pytest.mark.integration
async def test_members_fetch_the_bundle_over_the_api(
    test_db_url: str, anchoring_on: None
) -> None:
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("fastapi")
    from api.app import create_app
    from bot.services.membership_service import MembershipService
    from core.auth import SessionManager
    from core.state import InMemoryStateBackend

    event_id = await _locked_event(test_db_url, opted_in=True, offset=9)
    await _lock(test_db_url, event_id)
    async with get_session(test_db_url) as session:
        event = await session.get(Event, event_id)
        member = await resolve_telegram_user(session, 5_100_000_001)
        await MembershipService(session).add_member(event.group_id, member.user_id)
        outsider = await resolve_telegram_user(session, 5_100_000_002)
        public_id, member_id, outsider_id = (
            event.public_id,
            int(member.user_id),
            int(outsider.user_id),
        )
        await session.commit()

    state = InMemoryStateBackend()
    secret = "anchor-test-secret-32-bytes-long!!!"
    app = create_app(
        db_url=test_db_url, bot_token="1:x", auth_secret=secret, state_backend=state
    )
    sessions = SessionManager(state, secret)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        member_token = (await sessions.issue(member_id)).access_token
        response = await client.get(
            f"/events/{public_id}/anchor",
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert verify(ProofBundle.from_json(body["bundle"]), body["commitment"])

        outsider_token = (await sessions.issue(outsider_id)).access_token
        denied = await client.get(
            f"/events/{public_id}/anchor",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert denied.status_code == 403
