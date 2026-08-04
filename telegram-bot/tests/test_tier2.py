import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from core.auth import (
    AuthenticationError,
    SessionManager,
    WalletChallenges,
    validate_telegram_init_data,
)
from core.realtime import InMemoryEventBus
from core.state import InMemoryStateBackend


def telegram_payload(token: str, user: dict, auth_date: int = 1000) -> str:
    fields = {
        "auth_date": str(auth_date),
        "query_id": "q",
        "user": json.dumps(user, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_telegram_init_data_rejects_forgery_and_expiry():
    token = "bot-token"
    valid = telegram_payload(token, {"id": 42}, 1000)
    assert validate_telegram_init_data(valid, token, now=1001)["id"] == 42
    with pytest.raises(AuthenticationError):
        validate_telegram_init_data(valid.replace("q", "forged", 1), token, now=1001)
    with pytest.raises(AuthenticationError, match="Expired"):
        validate_telegram_init_data(valid, token, now=2000)


@pytest.mark.asyncio
async def test_sessions_expire_rotate_and_revoke():
    state = InMemoryStateBackend()
    manager = SessionManager(state, "a sufficiently long secret", access_ttl=10)
    pair = await manager.issue(7, now=100)
    assert await manager.verify_access(pair.access_token, now=109) == 7
    with pytest.raises(AuthenticationError, match="Expired"):
        await manager.verify_access(pair.access_token, now=110)
    replacement = await manager.refresh(pair.refresh_token)
    with pytest.raises(AuthenticationError):
        await manager.refresh(pair.refresh_token)
    await manager.revoke(replacement.access_token)
    with pytest.raises(AuthenticationError, match="Revoked"):
        await manager.verify_access(replacement.access_token)


@pytest.mark.asyncio
async def test_wallet_challenge_is_single_use():
    challenges = WalletChallenges(InMemoryStateBackend())
    nonce = await challenges.create("EQ-address")
    await challenges.consume(
        "EQ-address",
        "signature",
        lambda address, challenge, signature: challenge == nonce,
    )
    with pytest.raises(AuthenticationError):
        await challenges.consume("EQ-address", "signature", lambda *_: True)


@pytest.mark.asyncio
async def test_event_bus_fans_out_to_all_subscribers():
    bus = InMemoryEventBus()
    async with bus.subscribe("event:x") as first, bus.subscribe("event:x") as second:
        await bus.publish("event:x", {"type": "changed"})
        assert await anext(first) == {"type": "changed"}
        assert await anext(second) == {"type": "changed"}
