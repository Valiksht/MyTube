import uuid
from dataclasses import dataclass
from typing import Protocol

from app.models import Channel, User, Video
from app.repositories.channel import ChannelStore
from app.repositories.like import LikeStore
from app.repositories.video import VideoCatalog
from app.services.access import VideoAccessRequired, VideoInteractionDenied, view_decision
from app.services.videos import VideoNotFound


class Transaction(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class InvalidSearchQuery(Exception):
    def __init__(self) -> None:
        super().__init__("Search query is required")


class ChannelNotFound(Exception):
    def __init__(self) -> None:
        super().__init__("Channel not found")


@dataclass(frozen=True)
class VideoCard:
    video: Video
    like_count: int


@dataclass(frozen=True)
class VideoPage:
    items: list[VideoCard]
    total: int
    limit: int
    offset: int


class CatalogService:
    def __init__(
        self,
        videos: VideoCatalog,
        likes: LikeStore,
        channels: ChannelStore,
        session: Transaction,
    ) -> None:
        self._videos = videos
        self._likes = likes
        self._channels = channels
        self._session = session

    async def feed(self, *, limit: int, offset: int) -> VideoPage:
        rows, total = await self._videos.list_public(limit=limit, offset=offset)
        return await self._page(rows, total, limit, offset)

    async def search(self, query: str, *, limit: int, offset: int) -> VideoPage:
        cleaned = query.strip()
        if not cleaned:
            raise InvalidSearchQuery
        rows, total = await self._videos.search_public(cleaned, limit=limit, offset=offset)
        return await self._page(rows, total, limit, offset)

    async def get_video(self, video_id: uuid.UUID, viewer: User | None) -> VideoCard:
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
        counts = await self._likes.counts_for([video.id])
        return VideoCard(video=video, like_count=counts.get(video.id, 0))

    async def channel(
        self,
        channel_id: uuid.UUID,
        viewer: User | None,
        *,
        limit: int,
        offset: int,
    ) -> tuple[Channel, VideoPage]:
        channel = await self._channels.get_by_id(channel_id)
        if channel is None:
            raise ChannelNotFound
        include_private = viewer is not None and viewer.id == channel.owner_id
        rows, total = await self._videos.list_by_channel(
            channel_id,
            include_private=include_private,
            limit=limit,
            offset=offset,
        )
        return channel, await self._page(rows, total, limit, offset)

    async def set_hidden(self, video_id: uuid.UUID, *, is_hidden: bool) -> Video:
        video = await self._videos.get_by_id(video_id)
        if video is None:
            raise VideoNotFound
        video.is_hidden = is_hidden
        await self._session.commit()
        return video

    async def _page(
        self,
        rows: list[Video],
        total: int,
        limit: int,
        offset: int,
    ) -> VideoPage:
        counts = await self._likes.counts_for([video.id for video in rows])
        return VideoPage(
            items=[VideoCard(video=video, like_count=counts.get(video.id, 0)) for video in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
