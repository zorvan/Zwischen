"""Provider-neutral group membership read/write service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import GroupMember, GroupMemberRole, GroupMemberStatus


class MembershipService:
    """The single source of truth for group authorization."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_member(self, group_id: int, user_id: int) -> bool:
        return await self.get_role(group_id, user_id) is not None

    async def get_role(self, group_id: int, user_id: int) -> GroupMemberRole | None:
        row = await self._get(group_id, user_id)
        if row is None or row.status != GroupMemberStatus.active.value:
            return None
        return GroupMemberRole(row.role)

    async def add_member(
        self,
        group_id: int,
        user_id: int,
        role: GroupMemberRole = GroupMemberRole.member,
    ) -> GroupMember:
        row = await self._get(group_id, user_id)
        if row is None:
            row = GroupMember(group_id=group_id, user_id=user_id)
            self.session.add(row)
        setattr(row, "role", role.value)
        setattr(row, "status", GroupMemberStatus.active.value)
        setattr(row, "joined_at", datetime.now(timezone.utc))
        await self.session.flush()
        return row

    async def remove_member(
        self,
        group_id: int,
        user_id: int,
        *,
        status: GroupMemberStatus = GroupMemberStatus.removed,
    ) -> bool:
        row = await self._get(group_id, user_id)
        if row is None:
            return False
        setattr(row, "status", status.value)
        await self.session.flush()
        return True

    async def list_members(
        self,
        group_id: int,
        status: GroupMemberStatus = GroupMemberStatus.active,
    ) -> list[GroupMember]:
        result = await self.session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.status == status.value,
            )
        )
        return list(result.scalars().all())

    async def _get(self, group_id: int, user_id: int) -> GroupMember | None:
        return await self.session.get(GroupMember, (group_id, user_id))
