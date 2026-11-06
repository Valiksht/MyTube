import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.models import Comment, User, Video
from app.repositories.comment import CommentStore
from app.repositories.like import LikeStore
from app.repositories.video import VideoStore
from app.services.access import VideoAccessRequired, VideoInteractionDenied, can_moderate, view_decision
from app.services.videos import VideoNotFound


class Transaction(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class CommentNotFound(Exception):
    def __init__(self) -> None:
        super().__init__("Comment not found")


class CommentForbidden(Exception):
    def __init__(self) -> None:
        super().__init__("Comment cannot be changed")


class InvalidComment(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class CommentPage:
    items: list[Comment]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class LikeState:
    video_id: uuid.UUID
    liked: bool
    like_count: int


class EngagementService:
    def __init__(
        self,
        videos: VideoStore,
        comments: CommentStore,
        likes: LikeStore,
        session: Transaction,
    ) -> None:
        self._videos = videos
        self._comments = comments
        self._likes = likes
        self._session = session

    async def list_comments(
        self,
        video_id: uuid.UUID,
        viewer: User | None,
        *,
        limit: int,
        offset: int,
    ) -> CommentPage:
        await self._visible_video(video_id, viewer)
        items, total = await self._comments.list_for_video(video_id, limit=limit, offset=offset)
        return CommentPage(items=items, total=total, limit=limit, offset=offset)

    async def add_comment(
        self,
        video_id: uuid.UUID,
        author: User,
        body: str,
        parent_id: uuid.UUID | None,
    ) -> Comment:
        await self._visible_video(video_id, author)
        cleaned = self._clean_body(body)
        if parent_id is not None:
            parent = await self._comments.get_by_id(parent_id)
            if parent is None or parent.video_id != video_id:
                raise InvalidComment("Parent comment does not belong to this video")
        comment = Comment(
            id=uuid.uuid4(),
            video_id=video_id,
            author_id=author.id,
            parent_id=parent_id,
            body=cleaned,
            created_at=datetime.now(timezone.utc),
        )
        await self._comments.add(comment)
        await self._session.commit()
        return comment

    async def update_comment(self, comment_id: uuid.UUID, actor: User, body: str) -> Comment:
        comment = await self._owned_comment(comment_id, actor)
        comment.body = self._clean_body(body)
        await self._session.commit()
        return comment

    async def delete_comment(self, comment_id: uuid.UUID, actor: User) -> None:
        comment = await self._comments.get_by_id(comment_id)
        if comment is None:
            raise CommentNotFound
        if comment.author_id != actor.id and not can_moderate(actor):
            raise CommentForbidden
        await self._comments.delete(comment)
        await self._session.commit()

    async def like(self, video_id: uuid.UUID, user: User) -> LikeState:
        await self._visible_video(video_id, user)
        await self._likes.add(user.id, video_id)
        await self._session.commit()
        return await self._state(video_id, liked=True)

    async def unlike(self, video_id: uuid.UUID, user: User) -> LikeState:
        await self._visible_video(video_id, user)
        await self._likes.remove(user.id, video_id)
        await self._session.commit()
        return await self._state(video_id, liked=False)

    async def _visible_video(self, video_id: uuid.UUID, viewer: User | None) -> Video:
        video = await self._videos.get_by_id(video_id)
        if video is None:
            raise VideoNotFound
        decision = view_decision(video, viewer)
        if decision == "hide":
            raise VideoNotFound
        if decision == "authenticate":
            raise VideoAccessRequired
        if decision == "deny":
            raise VideoInteractionDenied
        return video

    async def _owned_comment(self, comment_id: uuid.UUID, actor: User) -> Comment:
        comment = await self._comments.get_by_id(comment_id)
        if comment is None:
            raise CommentNotFound
        if comment.author_id != actor.id:
            raise CommentForbidden
        return comment

    async def _state(self, video_id: uuid.UUID, *, liked: bool) -> LikeState:
        return LikeState(
            video_id=video_id,
            liked=liked,
            like_count=await self._likes.count_for(video_id),
        )

    def _clean_body(self, body: str) -> str:
        cleaned = body.strip()
        if not cleaned:
            raise InvalidComment("Comment body is required")
        if len(cleaned) > 2000:
            raise InvalidComment("Comment body is too long")
        return cleaned
