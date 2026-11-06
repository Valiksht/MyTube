import uuid
from io import BytesIO
from typing import BinaryIO

from sqlalchemy.exc import IntegrityError

from app.models import Channel, Comment, User, Video
from app.repositories.listing import is_publicly_listed


class NullSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FastPasswordHasher:
    dummy_hash = "fast:dummy"

    def hash(self, password: str) -> str:
        return f"fast:{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"fast:{password}"


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        return next(
            (user for user in self.users.values() if user.email.lower() == normalized),
            None,
        )

    async def get_by_username(self, username: str) -> User | None:
        normalized = username.strip().lower()
        return next(
            (user for user in self.users.values() if user.username.lower() == normalized),
            None,
        )

    async def add(self, user: User) -> User:
        if user.id in self.users or await self.get_by_email(user.email) is not None:
            raise IntegrityError(
                "INSERT",
                {},
                Exception("duplicate key value violates unique constraint uq_users_email_lower"),
            )
        if await self.get_by_username(user.username) is not None:
            raise IntegrityError(
                "INSERT",
                {},
                Exception(
                    "duplicate key value violates unique constraint uq_users_username_lower"
                ),
            )
        self.users[user.id] = user
        return user


class InMemoryChannelRepository:
    def __init__(self) -> None:
        self.channels: dict[uuid.UUID, Channel] = {}

    async def get_by_owner(self, owner_id: uuid.UUID) -> Channel | None:
        return next(
            (channel for channel in self.channels.values() if channel.owner_id == owner_id),
            None,
        )

    async def get_by_id(self, channel_id: uuid.UUID) -> Channel | None:
        return self.channels.get(channel_id)

    async def add(self, channel: Channel) -> Channel:
        self.channels[channel.id] = channel
        return channel


class InMemoryVideoRepository:
    def __init__(self) -> None:
        self.videos: dict[uuid.UUID, Video] = {}

    async def add(self, video: Video) -> Video:
        self.videos[video.id] = video
        return video

    async def get_by_id(self, video_id: uuid.UUID) -> Video | None:
        return self.videos.get(video_id)

    async def list_public(self, *, limit: int, offset: int) -> tuple[list[Video], int]:
        return _page_videos(
            [video for video in self.videos.values() if is_publicly_listed(video)],
            limit=limit,
            offset=offset,
        )

    async def search_public(
        self,
        query: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Video], int]:
        needle = query.casefold()
        matched = [
            video
            for video in self.videos.values()
            if is_publicly_listed(video) and needle in video.title.casefold()
        ]
        return _page_videos(matched, limit=limit, offset=offset)

    async def list_by_channel(
        self,
        channel_id: uuid.UUID,
        *,
        include_private: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Video], int]:
        rows = []
        for video in self.videos.values():
            if video.channel_id != channel_id:
                continue
            if include_private or is_publicly_listed(video):
                rows.append(video)
        return _page_videos(rows, limit=limit, offset=offset)


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []
        self.opened: list[tuple[str, int, int]] = []

    async def upload(
        self,
        *,
        object_key: str,
        data: BinaryIO,
        size: int,
        content_type: str,
    ) -> None:
        payload = data.read(size)
        self.objects[object_key] = (payload, content_type)

    async def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)
        self.objects.pop(object_key, None)

    async def open(self, *, object_key: str, offset: int, length: int) -> BytesIO:
        self.opened.append((object_key, offset, length))
        payload, _content_type = self.objects[object_key]
        return BytesIO(payload[offset : offset + length])


def _page_videos(rows: list[Video], *, limit: int, offset: int) -> tuple[list[Video], int]:
    ordered = sorted(rows, key=lambda video: (video.created_at, video.id), reverse=True)
    return ordered[offset : offset + limit], len(ordered)


class InMemoryCommentRepository:
    def __init__(self) -> None:
        self.comments: dict[uuid.UUID, Comment] = {}

    async def add(self, comment: Comment) -> Comment:
        self.comments[comment.id] = comment
        return comment

    async def get_by_id(self, comment_id: uuid.UUID) -> Comment | None:
        return self.comments.get(comment_id)

    async def list_for_video(
        self,
        video_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Comment], int]:
        rows = [comment for comment in self.comments.values() if comment.video_id == video_id]
        rows.sort(key=lambda comment: (comment.created_at, comment.id))
        return rows[offset : offset + limit], len(rows)

    async def delete(self, comment: Comment) -> None:
        self.comments.pop(comment.id, None)
        for child in self.comments.values():
            if child.parent_id == comment.id:
                child.parent_id = None


class InMemoryLikeRepository:
    def __init__(self) -> None:
        self.likes: set[tuple[uuid.UUID, uuid.UUID]] = set()

    async def add(self, user_id: uuid.UUID, video_id: uuid.UUID) -> None:
        self.likes.add((user_id, video_id))

    async def remove(self, user_id: uuid.UUID, video_id: uuid.UUID) -> bool:
        key = (user_id, video_id)
        if key not in self.likes:
            return False
        self.likes.remove(key)
        return True

    async def counts_for(self, video_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        wanted = set(video_ids)
        counts: dict[uuid.UUID, int] = {}
        for _user_id, video_id in self.likes:
            if video_id in wanted:
                counts[video_id] = counts.get(video_id, 0) + 1
        return counts

    async def count_for(self, video_id: uuid.UUID) -> int:
        return sum(1 for _user_id, liked_video in self.likes if liked_video == video_id)
