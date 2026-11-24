"""Authentication proofs and revocable sessions for non-Telegram transports."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl

from core.state import StateBackend


class AuthenticationError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 300,
    now: int | None = None,
) -> dict[str, Any]:
    """Validate Telegram Mini App initData exactly as Telegram specifies."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    supplied = pairs.pop("hash", None)
    if not supplied:
        raise AuthenticationError("Telegram payload has no hash")
    check = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise AuthenticationError("Invalid Telegram signature")
    try:
        auth_date = int(pairs["auth_date"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid Telegram auth_date") from exc
    current = int(time.time()) if now is None else now
    if auth_date > current + 30 or current - auth_date > max_age_seconds:
        raise AuthenticationError("Expired Telegram payload")
    try:
        user = json.loads(pairs["user"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError("Invalid Telegram user") from exc
    if not isinstance(user, dict) or "id" not in user:
        raise AuthenticationError("Telegram payload has no user id")
    return user


@dataclass(frozen=True)
class SessionPair:
    access_token: str
    refresh_token: str
    expires_in: int


class SessionManager:
    """Small HMAC access tokens plus opaque, server-side refresh tokens."""

    def __init__(
        self,
        state: StateBackend,
        secret: str,
        access_ttl: int = 900,
        refresh_ttl: int = 2592000,
    ):
        if len(secret) < 16:
            raise ValueError("AUTH_SECRET must contain at least 16 characters")
        self.state, self.secret = state, secret.encode()
        self.access_ttl, self.refresh_ttl = access_ttl, refresh_ttl

    def _access(self, user_id: int, session_id: str, now: int) -> str:
        payload = _b64encode(
            json.dumps(
                {
                    "sub": user_id,
                    "sid": session_id,
                    "iat": now,
                    "exp": now + self.access_ttl,
                },
                separators=(",", ":"),
            ).encode()
        )
        signature = _b64encode(
            hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
        )
        return f"{payload}.{signature}"

    async def issue(self, user_id: int, *, now: int | None = None) -> SessionPair:
        current = int(time.time()) if now is None else now
        sid, refresh = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        digest = hashlib.sha256(refresh.encode()).hexdigest()
        await self.state.set(
            f"session:{sid}", {"user_id": user_id, "refresh": digest}, self.refresh_ttl
        )
        return SessionPair(
            self._access(user_id, sid, current), f"{sid}.{refresh}", self.access_ttl
        )

    async def verify_access(self, token: str, *, now: int | None = None) -> int:
        try:
            payload, signature = token.split(".", 1)
            expected = _b64encode(
                hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(expected, signature):
                raise AuthenticationError("Invalid access token")
            claims = json.loads(_b64decode(payload))
            current = int(time.time()) if now is None else now
            if current >= int(claims["exp"]):
                raise AuthenticationError("Expired access token")
            session = await self.state.get(f"session:{claims['sid']}")
            if not session or int(session["user_id"]) != int(claims["sub"]):
                raise AuthenticationError("Revoked session")
            return int(claims["sub"])
        except AuthenticationError:
            raise
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AuthenticationError("Malformed access token") from exc

    async def refresh(self, token: str) -> SessionPair:
        try:
            sid, secret = token.split(".", 1)
        except ValueError as exc:
            raise AuthenticationError("Malformed refresh token") from exc
        session = await self.state.get(f"session:{sid}")
        if not session or not hmac.compare_digest(
            session["refresh"], hashlib.sha256(secret.encode()).hexdigest()
        ):
            raise AuthenticationError("Invalid refresh token")
        await self.state.delete(f"session:{sid}")  # rotate; refresh tokens are one-use
        return await self.issue(int(session["user_id"]))

    async def revoke(self, access_token: str) -> None:
        try:
            payload = json.loads(_b64decode(access_token.split(".", 1)[0]))
            await self.state.delete(f"session:{payload['sid']}")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            return


class WalletChallenges:
    """Single-use TON Connect challenges; signature verification is injectable."""

    def __init__(self, state: StateBackend, ttl: int = 300):
        self.state, self.ttl = state, ttl

    async def create(self, address: str) -> str:
        nonce = secrets.token_urlsafe(32)
        await self.state.set(f"wallet-challenge:{address}", nonce, self.ttl)
        return nonce

    async def consume(
        self,
        address: str,
        signature: str,
        verifier: Callable[[str, str, str], bool | Awaitable[bool]],
    ) -> None:
        nonce = await self.state.get(f"wallet-challenge:{address}")
        if not nonce:
            raise AuthenticationError("Missing or expired wallet challenge")
        result = verifier(address, nonce, signature)
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[misc]
        if not result:
            raise AuthenticationError("Invalid wallet signature")
        await self.state.delete(f"wallet-challenge:{address}")
