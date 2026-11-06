import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel


class ChannelStore(Protocol):
    async def get_by_owner(self, owner_id: uuid.UUID) -> Channel | None: ...

    async def get_by_id(self, channel_id: uuid.UUID) -> Channel | None: ...

    async def add(self, channel: Channel) -> Channel: ...


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_owner(self, owner_id: uuid.UUID) -> Channel | None:
        statement = (
            select(Channel)
            .where(Channel.owner_id == owner_id)
            .order_by(Channel.created_at.asc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_id(self, channel_id: uuid.UUID) -> Channel | None:
        return await self._session.get(Channel, channel_id)

    async def add(self, channel: Channel) -> Channel:
        self._session.add(channel)
        await self._session.flush()
        return channel
