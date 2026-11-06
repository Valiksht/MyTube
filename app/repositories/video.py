import uuid
from typing import Protocol

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Video
from app.repositories.listing import escape_like, publicly_listed_clause


class VideoStore(Protocol):
    async def add(self, video: Video) -> Video: ...

    async def get_by_id(self, video_id: uuid.UUID) -> Video | None: ...


class VideoCatalog(Protocol):
    async def get_by_id(self, video_id: uuid.UUID) -> Video | None: ...

    async def list_public(self, *, limit: int, offset: int) -> tuple[list[Video], int]: ...

    async def search_public(
        self,
        query: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Video], int]: ...

    async def list_by_channel(
        self,
        channel_id: uuid.UUID,
        *,
        include_private: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Video], int]: ...


class VideoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, video: Video) -> Video:
        self._session.add(video)
        await self._session.flush()
        return video

    async def get_by_id(self, video_id: uuid.UUID) -> Video | None:
        return await self._session.get(Video, video_id)

    async def list_public(self, *, limit: int, offset: int) -> tuple[list[Video], int]:
        return await self._page(publicly_listed_clause(), limit=limit, offset=offset)

    async def search_public(
        self,
        query: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Video], int]:
        pattern = f"%{escape_like(query)}%"
        clause = publicly_listed_clause() & Video.title.ilike(pattern, escape="\\")
        return await self._page(clause, limit=limit, offset=offset)

    async def list_by_channel(
        self,
        channel_id: uuid.UUID,
        *,
        include_private: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Video], int]:
        clause = Video.channel_id == channel_id
        if not include_private:
            clause = publicly_listed_clause() & clause
        return await self._page(clause, limit=limit, offset=offset)

    async def _page(
        self,
        clause: ColumnElement[bool],
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Video], int]:
        total = await self._session.scalar(select(func.count()).select_from(Video).where(clause))
        statement = (
            select(Video)
            .where(clause)
            .order_by(Video.created_at.desc(), Video.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = await self._session.scalars(statement)
        return list(rows.all()), int(total or 0)
