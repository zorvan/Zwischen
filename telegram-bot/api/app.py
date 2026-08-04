# mypy: disable-error-code="import-not-found,arg-type,union-attr"
"""FastAPI adapter over the same domain services used by Telegram."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.idempotency_service import IdempotencyService
from bot.services.membership_service import MembershipService
from bot.services.participant_service import ParticipantService
from core.auth import (
    AuthenticationError,
    SessionManager,
    WalletChallenges,
    validate_telegram_init_data,
)
from core.presentation import EventSummary
from core.realtime import EventUpdates, InMemoryEventBus
from core.state import InMemoryStateBackend, StateBackend
from db.connection import get_session
from db.identity import IdentityConflictError, link_identity, resolve_identity
from db.models import Event, EventParticipant, Group, User


class TelegramLogin(BaseModel):
    init_data: str


class RefreshRequest(BaseModel):
    refresh_token: str


class WalletRequest(BaseModel):
    address: str = Field(min_length=10, max_length=255)


class WalletVerify(WalletRequest):
    signature: str
    link: bool = False


class EventCreate(BaseModel):
    group_id: UUID
    event_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    scheduled_time: datetime | None = None
    min_participants: int = Field(default=2, ge=1)
    target_participants: int = Field(default=6, ge=1)


def create_app(
    *,
    db_url: str,
    bot_token: str,
    auth_secret: str,
    state_backend: StateBackend | None = None,
    event_bus: Any | None = None,
    wallet_verifier: Callable[[str, str, str], bool | Awaitable[bool]] | None = None,
) -> FastAPI:
    state = state_backend or InMemoryStateBackend()
    sessions = SessionManager(state, auth_secret)
    challenges = WalletChallenges(state)
    bus = event_bus or InMemoryEventBus()
    updates = EventUpdates(bus)
    app = FastAPI(title="Zwischen API", version="1.0.0")

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with get_session(db_url) as session:
            yield session

    async def current_user(
        authorization: str | None = Header(default=None),
        session: AsyncSession = Depends(session_dependency),
    ) -> User:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token required")
        try:
            user_id = await sessions.verify_access(authorization[7:])
        except AuthenticationError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Account no longer exists"
            )
        return user

    async def rate_limit(request: Request) -> None:
        count = await state.hit_window(
            f"auth:{request.client.host if request.client else 'unknown'}", 60
        )
        if count > 10:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many authentication attempts"
            )

    def tokens(pair: Any) -> dict[str, Any]:
        return {
            "access_token": pair.access_token,
            "refresh_token": pair.refresh_token,
            "token_type": "bearer",
            "expires_in": pair.expires_in,
        }

    @app.post("/auth/telegram", dependencies=[Depends(rate_limit)])
    async def telegram_login(
        body: TelegramLogin, session: AsyncSession = Depends(session_dependency)
    ) -> dict[str, Any]:
        try:
            claim = validate_telegram_init_data(body.init_data, bot_token)
        except AuthenticationError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        user = await resolve_identity(
            session,
            "telegram",
            claim["id"],
            display_name=" ".join(
                filter(None, [claim.get("first_name"), claim.get("last_name")])
            ),
            username=claim.get("username"),
        )
        await session.commit()
        return tokens(await sessions.issue(user.user_id))

    @app.post("/auth/refresh", dependencies=[Depends(rate_limit)])
    async def refresh(body: RefreshRequest) -> dict[str, Any]:
        try:
            return tokens(await sessions.refresh(body.refresh_token))
        except AuthenticationError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    @app.post("/auth/logout", status_code=204)
    async def logout(
        authorization: str = Header(), user: User = Depends(current_user)
    ) -> None:
        await sessions.revoke(authorization[7:])

    @app.post("/auth/wallet/challenge", dependencies=[Depends(rate_limit)])
    async def wallet_challenge(body: WalletRequest) -> dict[str, str]:
        return {"challenge": await challenges.create(body.address)}

    @app.post("/auth/wallet/verify", dependencies=[Depends(rate_limit)])
    async def wallet_verify(
        body: WalletVerify,
        session: AsyncSession = Depends(session_dependency),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if wallet_verifier is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "TON verification is not configured",
            )
        try:
            await challenges.consume(body.address, body.signature, wallet_verifier)
            if body.link:
                if not authorization or not authorization.startswith("Bearer "):
                    raise AuthenticationError(
                        "Authentication required to link a wallet"
                    )
                user_id = await sessions.verify_access(authorization[7:])
                await link_identity(session, user_id, "wallet:ton", body.address)
                user = await session.get(User, user_id)
            else:
                user = await resolve_identity(session, "wallet:ton", body.address)
            await session.commit()
            return tokens(await sessions.issue(user.user_id))
        except IdentityConflictError as exc:
            await session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except AuthenticationError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    async def event_for_member(
        public_id: UUID, user: User, session: AsyncSession
    ) -> Event:
        event = await session.scalar(select(Event).where(Event.public_id == public_id))
        if event is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
        if event.group_id is not None and not await MembershipService(
            session
        ).is_member(event.group_id, user.user_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this group")
        return event

    async def serialize(event: Event, session: AsyncSession) -> dict[str, Any]:
        counts = dict(
            (status.value, count)
            for status, count in (
                await session.execute(
                    select(EventParticipant.status, func.count())
                    .where(EventParticipant.event_id == event.event_id)
                    .group_by(EventParticipant.status)
                )
            ).all()
        )
        group = await session.get(Group, event.group_id) if event.group_id else None
        return EventSummary(
            event.public_id,
            group.public_id if group else None,
            event.title or event.event_type,
            event.event_type,
            event.state,
            event.scheduled_time,
            counts.get("confirmed", 0),
            counts.get("joined", 0),
            event.min_participants or 1,
        ).as_json()

    @app.get("/events")
    async def list_events(
        user: User = Depends(current_user),
        session: AsyncSession = Depends(session_dependency),
    ) -> list[dict[str, Any]]:
        rows = (
            (
                await session.execute(
                    select(Event)
                    .join(Group, Event.group_id == Group.group_id)
                    .where(Group.members.any(user_id=user.user_id, status="active"))
                    .order_by(Event.scheduled_time)
                )
            )
            .scalars()
            .all()
        )
        return [await serialize(event, session) for event in rows]

    @app.get("/events/{event_id}")
    async def view_event(
        event_id: UUID,
        user: User = Depends(current_user),
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        return await serialize(await event_for_member(event_id, user, session), session)

    async def mutate_participation(
        event_id: UUID, action: str, key: str | None, user: User, session: AsyncSession
    ) -> dict[str, Any]:
        event = await event_for_member(event_id, user, session)
        idem = IdempotencyService(session)
        if key:
            duplicate, state_name, _ = await idem.check(key)
            if not duplicate:
                await idem.register(key, action, user.user_id, event.event_id)
            elif state_name == "pending":
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "Request is already in progress"
                )
        service = ParticipantService(session)
        if not key or not duplicate:
            if action == "join":
                await service.join(event.event_id, user.user_id, "http")
            elif action == "leave":
                await service.cancel(event.event_id, user.user_id, "http")
            else:
                await service.confirm(event.event_id, user.user_id, "http")
            if key:
                await idem.complete(key)
            await session.commit()
            await updates.changed(event.event_id, str(event.public_id))
        return await serialize(event, session)

    @app.post("/events/{event_id}/join")
    async def join(
        event_id: UUID,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        user: User = Depends(current_user),
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        return await mutate_participation(
            event_id, "join", idempotency_key, user, session
        )

    @app.post("/events/{event_id}/leave")
    async def leave(
        event_id: UUID,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        user: User = Depends(current_user),
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        return await mutate_participation(
            event_id, "leave", idempotency_key, user, session
        )

    @app.post("/events/{event_id}/commit")
    async def commit(
        event_id: UUID,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        user: User = Depends(current_user),
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        return await mutate_participation(
            event_id, "commit", idempotency_key, user, session
        )

    @app.post("/events", status_code=201)
    async def create_event(
        body: EventCreate,
        user: User = Depends(current_user),
        session: AsyncSession = Depends(session_dependency),
    ) -> dict[str, Any]:
        group = await session.scalar(
            select(Group).where(Group.public_id == body.group_id)
        )
        if group is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
        if not await MembershipService(session).is_member(group.group_id, user.user_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a group member")
        event = Event(
            group_id=group.group_id,
            organizer_user_id=user.user_id,
            event_type=body.event_type,
            title=body.title,
            description=body.description,
            scheduled_time=body.scheduled_time,
            min_participants=body.min_participants,
            target_participants=body.target_participants,
        )
        session.add(event)
        await session.flush()
        await ParticipantService(session).join(event.event_id, user.user_id, "http")
        await session.commit()
        await updates.changed(event.event_id, str(event.public_id))
        return await serialize(event, session)

    @app.get("/events/{event_id}/stream")
    async def stream(
        event_id: UUID,
        user: User = Depends(current_user),
        session: AsyncSession = Depends(session_dependency),
    ) -> StreamingResponse:
        event = await event_for_member(event_id, user, session)
        initial = await serialize(event, session)

        async def events() -> AsyncIterator[str]:
            yield f"event: snapshot\ndata: {json.dumps(initial)}\n\n"
            async with bus.subscribe(f"event:{event_id}") as messages:
                async for message in messages:
                    yield f"event: changed\ndata: {json.dumps(message)}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    return app
