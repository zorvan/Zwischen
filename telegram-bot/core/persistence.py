"""python-telegram-bot persistence backed by :mod:`core.state`.

PTB calls the ``refresh_*`` methods before dispatching an update.  Reloading
the relevant mapping there is what lets consecutive updates for one flow land
on different application instances without either instance retaining a stale
copy of ``user_data``.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from telegram.ext import BasePersistence, PersistenceInput

from core.state import StateBackend


class StateBackendPersistence(BasePersistence[dict, dict, dict]):
    """Persist PTB's JSON-compatible state in a shared ``StateBackend``."""

    def __init__(self, backend: StateBackend, ttl_seconds: int = 24 * 60 * 60) -> None:
        super().__init__(
            store_data=PersistenceInput(
                bot_data=False, chat_data=True, user_data=True, callback_data=False
            ),
            update_interval=0,
        )
        self.backend = backend
        self.ttl_seconds = ttl_seconds
        self._known_users: set[int] = set()
        self._known_chats: set[int] = set()
        self._conversation_names: set[str] = set()

    @staticmethod
    def _replace(target: dict, value: Any) -> None:
        target.clear()
        if isinstance(value, dict):
            target.update(deepcopy(value))

    async def get_user_data(self) -> dict[int, dict]:
        result: dict[int, dict] = {}
        for user_id in self._known_users:
            value = await self.backend.get(f"ptb:user:{user_id}")
            if isinstance(value, dict):
                result[user_id] = value
        return result

    async def get_chat_data(self) -> dict[int, dict]:
        result: dict[int, dict] = {}
        for chat_id in self._known_chats:
            value = await self.backend.get(f"ptb:chat:{chat_id}")
            if isinstance(value, dict):
                result[chat_id] = value
        return result

    async def get_bot_data(self) -> dict:
        value = await self.backend.get("ptb:bot")
        return value if isinstance(value, dict) else {}

    async def get_callback_data(self) -> None:
        return None

    async def get_conversations(self, name: str) -> dict:
        self._conversation_names.add(name)
        value = await self.backend.get(f"ptb:conversation:{name}")
        if not isinstance(value, dict):
            return {}
        return {tuple(json.loads(key)): state for key, state in value.items()}

    async def update_user_data(self, user_id: int, data: dict) -> None:
        self._known_users.add(user_id)
        await self.backend.set(f"ptb:user:{user_id}", deepcopy(data), self.ttl_seconds)

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        self._known_chats.add(chat_id)
        await self.backend.set(f"ptb:chat:{chat_id}", deepcopy(data), self.ttl_seconds)

    async def update_bot_data(self, data: dict) -> None:
        await self.backend.set("ptb:bot", deepcopy(data))

    async def update_callback_data(self, data: Any) -> None:
        return None

    async def update_conversation(
        self, name: str, key: tuple[int | str, ...], new_state: object | None
    ) -> None:
        self._conversation_names.add(name)
        storage_key = f"ptb:conversation:{name}"
        values = await self.backend.get(storage_key) or {}
        encoded_key = json.dumps(list(key), separators=(",", ":"))
        if new_state is None:
            values.pop(encoded_key, None)
        else:
            values[encoded_key] = new_state
        await self.backend.set(storage_key, values, self.ttl_seconds)

    async def refresh_user_data(self, user_id: int, user_data: dict) -> None:
        self._known_users.add(user_id)
        self._replace(user_data, await self.backend.get(f"ptb:user:{user_id}"))

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> None:
        self._known_chats.add(chat_id)
        self._replace(chat_data, await self.backend.get(f"ptb:chat:{chat_id}"))

    async def refresh_bot_data(self, bot_data: dict) -> None:
        return None

    async def drop_user_data(self, user_id: int) -> None:
        self._known_users.discard(user_id)
        await self.backend.delete(f"ptb:user:{user_id}")

    async def drop_chat_data(self, chat_id: int) -> None:
        self._known_chats.discard(chat_id)
        await self.backend.delete(f"ptb:chat:{chat_id}")

    async def flush(self) -> None:
        # Writes are immediate. The backend is closed by the application
        # shutdown hook, after PTB has flushed persistence.
        return None
