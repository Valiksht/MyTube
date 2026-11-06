import uuid
from collections.abc import AsyncIterator
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.videos import get_video_service
from app.core.config import Settings
from app.models import User, Video
from app.models.enums import UserRole, VideoVisibility
from app.services.media import (
    UnsupportedVideoType,
    build_object_key,
    resolve_media_type,
    safe_filename,
)
from app.services.videos import EmptyVideoFile, VideoService, VideoTooLarge
from tests.conftest import _application_with_role_zones
from tests.fakes import (
    FastPasswordHasher,
    InMemoryChannelRepository,
    InMemoryUserRepository,
    InMemoryVideoRepository,
    MemoryStorage,
    NullSession,
)


def test_object_key_uses_generated_name_not_the_original_path() -> None:
    author_id = uuid.uuid4()
    object_id = uuid.uuid4()

    key = build_object_key(author_id, safe_filename("../../secret.mp4"), object_id)

    assert key == f"videos/{author_id}/{object_id}.mp4"
    assert ".." not in key
    assert safe_filename("../../secret.mp4") == "secret.mp4"


def test_media_type_follows_extension_and_rejects_a_mismatch() -> None:
    assert resolve_media_type("clip.MP4", None) == "video/mp4"
    assert resolve_media_type("clip.mp4", "application/octet-stream") == "video/mp4"

    with pytest.raises(UnsupportedVideoType):
        resolve_media_type("notes.txt", "text/plain")
    with pytest.raises(UnsupportedVideoType):
        resolve_media_type("clip.mp4", "video/webm")


def _author() -> User:
    return User(
        id=uuid.uuid4(),
        email="author@example.com",
        username="author",
        hashed_password="fast:password123",
        role=UserRole.USER,
        is_active=True,
    )


def _service(
    settings: Settings,
    storage: MemoryStorage | None = None,
    videos: InMemoryVideoRepository | None = None,
) -> tuple[VideoService, MemoryStorage, InMemoryVideoRepository, InMemoryChannelRepository]:
    object_storage = storage or MemoryStorage()
    video_store = videos or InMemoryVideoRepository()
    channels = InMemoryChannelRepository()
    service = VideoService(
        videos=video_store,
        channels=channels,
        session=NullSession(),
        storage=object_storage,
        settings=settings,
    )
    return service, object_storage, video_store, channels


@pytest.mark.asyncio
async def test_upload_persists_visibility_and_unique_object_keys(settings: Settings) -> None:
    service, storage, videos, channels = _service(settings)
    author = _author()

    private_video = await service.upload(
        author=author,
        title="  Private cut  ",
        description=" home ",
        visibility=VideoVisibility.PRIVATE,
        filename="../../holiday.mp4",
        declared_type="video/mp4",
        data=BytesIO(b"private-bytes"),
        size=13,
    )
    public_video = await service.upload(
        author=author,
        title="Public cut",
        description="",
        visibility=VideoVisibility.PUBLIC,
        filename="holiday.mp4",
        declared_type="video/mp4",
        data=BytesIO(b"public-bytes"),
        size=12,
    )

    assert private_video.visibility == VideoVisibility.PRIVATE
    assert private_video.title == "Private cut"
    assert private_video.description == "home"
    assert private_video.original_filename == "holiday.mp4"
    assert private_video.bucket == "mytube"
    assert private_video.size_bytes == 13
    assert public_video.visibility == VideoVisibility.PUBLIC
    assert private_video.object_key != public_video.object_key
    assert private_video.object_key.startswith(f"videos/{author.id}/")
    assert private_video.channel_id == public_video.channel_id
    assert len(channels.channels) == 1
    assert storage.objects[private_video.object_key] == (b"private-bytes", "video/mp4")
    assert set(videos.videos) == {private_video.id, public_video.id}


@pytest.mark.asyncio
async def test_upload_rejects_empty_unknown_and_oversized_files(settings: Settings) -> None:
    limited = settings.model_copy(update={"max_upload_bytes": 4})
    service, storage, _videos, _channels = _service(limited)
    author = _author()

    with pytest.raises(EmptyVideoFile):
        await service.upload(
            author=author,
            title="Empty",
            description="",
            visibility=VideoVisibility.PUBLIC,
            filename="empty.mp4",
            declared_type="video/mp4",
            data=BytesIO(b""),
            size=0,
        )
    with pytest.raises(UnsupportedVideoType):
        await service.upload(
            author=author,
            title="Notes",
            description="",
            visibility=VideoVisibility.PUBLIC,
            filename="notes.txt",
            declared_type="text/plain",
            data=BytesIO(b"hello"),
            size=5,
        )
    with pytest.raises(VideoTooLarge):
        await service.upload(
            author=author,
            title="Big",
            description="",
            visibility=VideoVisibility.PRIVATE,
            filename="big.mp4",
            declared_type="video/mp4",
            data=BytesIO(b"12345"),
            size=5,
        )

    assert storage.objects == {}


@pytest.mark.asyncio
async def test_upload_deletes_object_when_database_commit_fails(settings: Settings) -> None:
    class BrokenVideoRepository(InMemoryVideoRepository):
        async def add(self, video: Video) -> Video:
            raise RuntimeError("database unavailable")

    service, storage, _videos, _channels = _service(settings, videos=BrokenVideoRepository())

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.upload(
            author=_author(),
            title="Keep storage clean",
            description="",
            visibility=VideoVisibility.PRIVATE,
            filename="clip.mp4",
            declared_type="video/mp4",
            data=BytesIO(b"bytes"),
            size=5,
        )

    assert storage.objects == {}
    assert len(storage.deleted) == 1


@pytest.fixture
async def upload_client(
    settings: Settings,
    user_store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
) -> AsyncIterator[tuple[AsyncClient, InMemoryVideoRepository, MemoryStorage]]:
    videos = InMemoryVideoRepository()
    storage = MemoryStorage()
    service = VideoService(
        videos=videos,
        channels=InMemoryChannelRepository(),
        session=NullSession(),
        storage=storage,
        settings=settings,
    )
    application = _application_with_role_zones(settings, user_store, hasher)
    application.dependency_overrides[get_video_service] = lambda: service
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client, videos, storage


async def _token(client: AsyncClient) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": "author@example.com", "username": "author", "password": "password123"},
    )
    assert response.status_code == 201
    access_token: str = response.json()["access_token"]
    return access_token


@pytest.mark.asyncio
async def test_video_endpoint_saves_private_and_public_metadata(
    upload_client: tuple[AsyncClient, InMemoryVideoRepository, MemoryStorage],
) -> None:
    client, videos, storage = upload_client
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    private = await client.post(
        "/videos",
        headers=headers,
        data={"title": "Hidden", "visibility": "private", "description": "draft"},
        files={"file": ("clip.mp4", b"private-video", "video/mp4")},
    )
    public = await client.post(
        "/videos",
        headers=headers,
        data={"title": "Shown", "visibility": "public"},
        files={"file": ("clip.mp4", b"public-video", "video/mp4")},
    )

    assert private.status_code == 201
    assert public.status_code == 201
    private_body = private.json()
    public_body = public.json()
    assert private_body["visibility"] == "private"
    assert public_body["visibility"] == "public"
    assert private_body["object_key"] != public_body["object_key"]
    assert private_body["original_filename"] == "clip.mp4"
    assert private_body["size_bytes"] == len(b"private-video")
    assert "hashed_password" not in private_body
    assert set(videos.videos) == {uuid.UUID(private_body["id"]), uuid.UUID(public_body["id"])}
    assert storage.objects[private_body["object_key"]][0] == b"private-video"


@pytest.mark.asyncio
async def test_video_endpoint_requires_auth_and_rejects_bad_files(
    upload_client: tuple[AsyncClient, InMemoryVideoRepository, MemoryStorage],
) -> None:
    client, _videos, storage = upload_client
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}

    anonymous = await client.post(
        "/videos",
        data={"title": "Hidden", "visibility": "private"},
        files={"file": ("clip.mp4", b"private-video", "video/mp4")},
    )
    notes = await client.post(
        "/videos",
        headers=headers,
        data={"title": "Notes", "visibility": "public"},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    empty = await client.post(
        "/videos",
        headers=headers,
        data={"title": "Empty", "visibility": "public"},
        files={"file": ("empty.mp4", b"", "video/mp4")},
    )
    unlisted = await client.post(
        "/videos",
        headers=headers,
        data={"title": "Nope", "visibility": "unlisted"},
        files={"file": ("clip.mp4", b"bytes", "video/mp4")},
    )

    assert anonymous.status_code == 401
    assert notes.status_code == 415
    assert empty.status_code == 400
    assert unlisted.status_code == 422
    assert storage.objects == {}


@pytest.mark.asyncio
async def test_upload_page_has_progress_bar(
    upload_client: tuple[AsyncClient, InMemoryVideoRepository, MemoryStorage],
) -> None:
    client, _videos, _storage = upload_client
    response = await client.get("/upload")

    assert response.status_code == 200
    page = response.text
    assert 'id="upload-progress"' in page
    assert "request.upload.addEventListener(\"progress\"" in page
    assert 'value="private"' in page
    assert 'value="public"' in page
