import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO, Protocol

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.models import Channel, User, Video
from app.models.enums import VideoVisibility
from app.repositories.channel import ChannelStore
from app.repositories.video import VideoStore
from app.services.media import (
    UnsupportedVideoType,
    build_object_key,
    resolve_media_type,
    safe_filename,
)
from app.services.ranges import InvalidByteRange, parse_byte_range
from app.storage.base import BinaryReader, ObjectStorage, StorageError


class Transaction(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class EmptyVideoFile(Exception):
    def __init__(self) -> None:
        super().__init__("Video file is empty")


class VideoTooLarge(Exception):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Video exceeds the upload limit of {limit} bytes")


class InvalidVideoMetadata(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class VideoNotFound(Exception):
    def __init__(self) -> None:
        super().__init__("Video not found")


class AuthenticationRequired(Exception):
    def __init__(self) -> None:
        super().__init__("Could not validate credentials")


class VideoAccessDenied(Exception):
    def __init__(self) -> None:
        super().__init__("Private video")


@dataclass(frozen=True)
class Playback:
    content_type: str
    total_size: int
    start: int
    end: int
    body: BinaryReader
    partial: bool

    @property
    def length(self) -> int:
        if self.total_size == 0:
            return 0
        return self.end - self.start + 1


class VideoService:
    def __init__(
        self,
        videos: VideoStore,
        channels: ChannelStore,
        session: Transaction,
        storage: ObjectStorage,
        settings: Settings,
    ) -> None:
        self._videos = videos
        self._channels = channels
        self._session = session
        self._storage = storage
        self._settings = settings

    async def upload(
        self,
        *,
        author: User,
        title: str,
        description: str,
        visibility: VideoVisibility,
        filename: str | None,
        declared_type: str | None,
        data: BinaryIO,
        size: int,
    ) -> Video:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise InvalidVideoMetadata("Title is required")
        if len(cleaned_title) > 200:
            raise InvalidVideoMetadata("Title is too long")

        cleaned_description = description.strip()
        if len(cleaned_description) > 5000:
            raise InvalidVideoMetadata("Description is too long")

        if size < 0:
            raise InvalidVideoMetadata("Invalid file size")

        original_filename = safe_filename(filename)
        content_type = resolve_media_type(original_filename, declared_type)
        if size == 0:
            raise EmptyVideoFile
        if size > self._settings.max_upload_bytes:
            raise VideoTooLarge(self._settings.max_upload_bytes)

        author_id = author.id
        channel = await self._ensure_channel(author_id, author.username)
        object_id = uuid.uuid4()
        object_key = build_object_key(author_id, original_filename, object_id)

        await self._storage.upload(
            object_key=object_key,
            data=data,
            size=size,
            content_type=content_type,
        )
        video = Video(
            id=object_id,
            author_id=author_id,
            channel_id=channel.id,
            title=cleaned_title,
            description=cleaned_description,
            visibility=visibility,
            is_hidden=False,
            bucket=self._settings.minio_bucket,
            object_key=object_key,
            thumbnail_object_key=None,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size,
            duration_seconds=None,
            view_count=0,
            created_at=datetime.now(timezone.utc),
        )
        try:
            await self._videos.add(video)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            await self._discard_object(object_key)
            raise
        return video

    async def open_playback(
        self,
        video_id: uuid.UUID,
        viewer: User | None,
        range_header: str | None,
    ) -> Playback:
        video = await self._videos.get_by_id(video_id)
        if video is None:
            raise VideoNotFound
        self._ensure_can_stream(video, viewer)

        if video.size_bytes == 0:
            selected = parse_byte_range(range_header, 0)
            if selected is not None or (range_header is not None and range_header.strip() != ""):
                raise InvalidByteRange(0)
            return Playback(
                content_type=video.content_type,
                total_size=0,
                start=0,
                end=0,
                body=_EmptyReader(),
                partial=False,
            )

        selected = parse_byte_range(range_header, video.size_bytes)
        if selected is None:
            start, end = 0, video.size_bytes - 1
            partial = False
        else:
            start, end = selected
            partial = True

        body = await self._storage.open(
            object_key=video.object_key,
            offset=start,
            length=end - start + 1,
        )
        return Playback(
            content_type=video.content_type,
            total_size=video.size_bytes,
            start=start,
            end=end,
            body=body,
            partial=partial,
        )

    def _ensure_can_stream(self, video: Video, viewer: User | None) -> None:
        if video.visibility != VideoVisibility.PRIVATE:
            return
        if viewer is None:
            raise AuthenticationRequired
        if viewer.id != video.author_id:
            raise VideoAccessDenied

    async def _ensure_channel(self, author_id: uuid.UUID, username: str) -> Channel:
        existing = await self._channels.get_by_owner(author_id)
        if existing is not None:
            return existing

        channel = Channel(
            id=uuid.uuid4(),
            owner_id=author_id,
            name=username[:100],
            handle=username[:50],
            description="",
        )
        try:
            await self._channels.add(channel)
        except IntegrityError:
            await self._session.rollback()
            raced = await self._channels.get_by_owner(author_id)
            if raced is None:
                raise
            return raced
        return channel

    async def _discard_object(self, object_key: str) -> None:
        try:
            await self._storage.delete(object_key)
        except StorageError:
            return


class _EmptyReader:
    def read(self, size: int = -1) -> bytes:
        return b""

    def close(self) -> None:
        return None
