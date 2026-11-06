import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_media_viewer
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models import User
from app.models.enums import VideoVisibility
from app.repositories.channel import ChannelRepository
from app.repositories.video import VideoRepository
from app.schemas.video import VideoResponse
from app.services.media import UnsupportedVideoType
from app.services.ranges import InvalidByteRange
from app.services.videos import (
    AuthenticationRequired,
    EmptyVideoFile,
    InvalidVideoMetadata,
    VideoAccessDenied,
    VideoNotFound,
    VideoService,
    VideoTooLarge,
)
from app.storage.base import BinaryReader, ObjectStorage, StorageError
from app.storage.minio import MinioStorage

router = APIRouter(tags=["videos"])


def get_object_storage(settings: Annotated[Settings, Depends(get_settings)]) -> MinioStorage:
    return MinioStorage(settings)


def get_video_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VideoService:
    return VideoService(
        videos=VideoRepository(session),
        channels=ChannelRepository(session),
        session=session,
        storage=storage,
        settings=settings,
    )


async def _upload_size(file: UploadFile) -> int:
    def measure() -> int:
        file.file.seek(0, 2)
        measured = file.file.tell()
        file.file.seek(0)
        return int(measured)

    return await asyncio.to_thread(measure)


@router.post("/videos", status_code=status.HTTP_201_CREATED)
async def upload_video(
    user: Annotated[User, Depends(get_current_user)],
    videos: Annotated[VideoService, Depends(get_video_service)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    visibility: Annotated[Literal["public", "private"], Form()],
    description: Annotated[str, Form(max_length=5000)] = "",
) -> VideoResponse:
    size = await _upload_size(file)
    try:
        video = await videos.upload(
            author=user,
            title=title,
            description=description,
            visibility=VideoVisibility(visibility),
            filename=file.filename,
            declared_type=file.content_type,
            data=file.file,
            size=size,
        )
    except UnsupportedVideoType as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    except EmptyVideoFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except VideoTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except InvalidVideoMetadata as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.detail,
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    finally:
        await file.close()
    return VideoResponse.model_validate(video)


@router.get("/videos/{video_id}/stream")
async def stream_video(
    video_id: uuid.UUID,
    request: Request,
    viewer: Annotated[User | None, Depends(get_media_viewer)],
    videos: Annotated[VideoService, Depends(get_video_service)],
) -> StreamingResponse:
    try:
        playback = await videos.open_playback(video_id, viewer, request.headers.get("range"))
    except VideoNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AuthenticationRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except VideoAccessDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InvalidByteRange as exc:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail=str(exc),
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{exc.size}",
            },
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(playback.length),
    }
    status_code = status.HTTP_200_OK
    if playback.partial:
        headers["Content-Range"] = (
            f"bytes {playback.start}-{playback.end}/{playback.total_size}"
        )
        status_code = status.HTTP_206_PARTIAL_CONTENT
    return StreamingResponse(
        _iter_body(playback.body),
        status_code=status_code,
        media_type=playback.content_type,
        headers=headers,
    )


async def _iter_body(body: BinaryReader) -> AsyncIterator[bytes]:
    try:
        while True:
            chunk = await asyncio.to_thread(body.read, 64 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        await asyncio.to_thread(body.close)
