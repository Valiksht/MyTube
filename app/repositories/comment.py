import uuid
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment


class CommentStore(Protocol):
    async def add(self, comment: Comment) -> Comment: ...

    async def get_by_id(self, comment_id: uuid.UUID) -> Comment | None: ...

    async def list_for_video(
        self,
        video_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Comment], int]: ...

    async def delete(self, comment: Comment) -> None: ...


class CommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, comment: Comment) -> Comment:
        self._session.add(comment)
        await self._session.flush()
        return comment

    async def get_by_id(self, comment_id: uuid.UUID) -> Comment | None:
        return await self._session.get(Comment, comment_id)

    async def list_for_video(
        self,
        video_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Comment], int]:
        clause = Comment.video_id == video_id
        total = await self._session.scalar(select(func.count()).select_from(Comment).where(clause))
        statement = (
            select(Comment)
            .where(clause)
            .order_by(Comment.created_at.asc(), Comment.id.asc())
            .limit(limit)
            .offset(offset)
        )
        rows = await self._session.scalars(statement)
        return list(rows.all()), int(total or 0)

    async def delete(self, comment: Comment) -> None:
        await self._session.delete(comment)
        await self._session.flush()
