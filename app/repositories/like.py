import uuid
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Like


class LikeStore(Protocol):
    async def add(self, user_id: uuid.UUID, video_id: uuid.UUID) -> None: ...

    async def remove(self, user_id: uuid.UUID, video_id: uuid.UUID) -> bool: ...

    async def counts_for(self, video_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]: ...

    async def count_for(self, video_id: uuid.UUID) -> int: ...


class LikeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_id: uuid.UUID, video_id: uuid.UUID) -> None:
        existing = await self._session.get(Like, (user_id, video_id))
        if existing is not None:
            return
        self._session.add(Like(user_id=user_id, video_id=video_id))
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()

    async def remove(self, user_id: uuid.UUID, video_id: uuid.UUID) -> bool:
        existing = await self._session.get(Like, (user_id, video_id))
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    async def counts_for(self, video_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not video_ids:
            return {}
        statement = (
            select(Like.video_id, func.count())
            .where(Like.video_id.in_(video_ids))
            .group_by(Like.video_id)
        )
        rows = await self._session.execute(statement)
        return {video_id: int(count) for video_id, count in rows.all()}

    async def count_for(self, video_id: uuid.UUID) -> int:
        counts = await self.counts_for([video_id])
        return counts.get(video_id, 0)
