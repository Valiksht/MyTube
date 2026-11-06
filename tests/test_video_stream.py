import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.videos import get_video_service
from app.core.config import Settings
from app.models.enums import UserRole
from app.services.ranges import InvalidByteRange, parse_byte_range
from app.services.videos import VideoService
from tests.conftest import _application_with_role_zones
from tests.fakes import (
    FastPasswordHasher,
    InMemoryChannelRepository,
    InMemoryUserRepository,
    InMemoryVideoRepository,
    MemoryStorage,
    NullSession,
)

_PAYLOAD = b"PRIVATE-VIDEO-BYTES-0123456789"


def test_parse_byte_range_supports_player_seek_forms() -> None:
    assert parse_byte_range(None, 30) is None
    assert parse_byte_range("bytes=0-6", 30) == (0, 6)
    assert parse_byte_range("bytes=8-", 30) == (8, 29)
    assert parse_byte_range("bytes=-4", 30) == (26, 29)
    assert parse_byte_range("bytes=0-100", 30) == (0, 29)
    assert parse_byte_range("items=0-1", 30) is None

    with pytest.raises(InvalidByteRange) as error:
        parse_byte_range("bytes=40-50", 30)
    assert error.value.size == 30

    with pytest.raises(InvalidByteRange):
        parse_byte_range("bytes=5-1", 30)
    with pytest.raises(InvalidByteRange):
        parse_byte_range("bytes=0-1,2-3", 30)


@pytest.fixture
async def stream_client(
    settings: Settings,
    user_store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
) -> AsyncIterator[tuple[AsyncClient, MemoryStorage]]:
    storage = MemoryStorage()
    service = VideoService(
        videos=InMemoryVideoRepository(),
        channels=InMemoryChannelRepository(),
        session=NullSession(),
        storage=storage,
        settings=settings,
    )
    application = _application_with_role_zones(settings, user_store, hasher)
    application.dependency_overrides[get_video_service] = lambda: service
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client, storage


async def _register_token(client: AsyncClient, email: str, username: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "password123"},
    )
    assert response.status_code == 201
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _upload(
    client: AsyncClient,
    token: str,
    *,
    visibility: str,
    payload: bytes = _PAYLOAD,
) -> dict[str, object]:
    response = await client.post(
        "/videos",
        headers=_auth(token),
        data={"title": "Clip", "visibility": visibility},
        files={"file": ("clip.mp4", payload, "video/mp4")},
    )
    assert response.status_code == 201
    body: dict[str, object] = response.json()
    return body


@pytest.mark.asyncio
async def test_stranger_cannot_read_private_video_bytes(
    stream_client: tuple[AsyncClient, MemoryStorage],
    user_store: InMemoryUserRepository,
) -> None:
    client, storage = stream_client
    owner = await _register_token(client, "owner@example.com", "owner")
    stranger = await _register_token(client, "stranger@example.com", "stranger")
    video = await _upload(client, owner, visibility="private")

    anonymous = await client.get(f"/videos/{video['id']}/stream")
    stranger_response = await client.get(
        f"/videos/{video['id']}/stream",
        headers={**_auth(stranger), "Range": "bytes=0-6"},
    )
    stranger_user = next(user for user in user_store.users.values() if user.username == "stranger")
    stranger_user.role = UserRole.ADMIN
    admin_response = await client.get(
        f"/videos/{video['id']}/stream",
        headers=_auth(stranger),
    )

    assert anonymous.status_code == 401
    assert stranger_response.status_code == 403
    assert stranger_response.json()["detail"] == "Private video"
    assert admin_response.status_code == 403
    assert _PAYLOAD not in stranger_response.content
    assert _PAYLOAD not in admin_response.content
    assert storage.opened == []


@pytest.mark.asyncio
async def test_owner_can_seek_private_video_with_range(
    stream_client: tuple[AsyncClient, MemoryStorage],
) -> None:
    client, storage = stream_client
    owner = await _register_token(client, "owner@example.com", "owner")
    video = await _upload(client, owner, visibility="private")

    response = await client.get(
        f"/videos/{video['id']}/stream",
        headers={**_auth(owner), "Range": "bytes=0-6"},
    )

    assert response.status_code == 206
    assert response.content == _PAYLOAD[:7]
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes 0-6/{len(_PAYLOAD)}"
    assert response.headers["content-type"].startswith("video/mp4")
    assert storage.opened == [(video["object_key"], 0, 7)]

    by_query = await client.get(
        f"/videos/{video['id']}/stream",
        params={"access_token": owner},
        headers={"Range": "bytes=0-3"},
    )
    assert by_query.status_code == 206
    assert by_query.content == _PAYLOAD[:4]


@pytest.mark.asyncio
async def test_public_video_streams_without_a_token_and_rejects_bad_ranges(
    stream_client: tuple[AsyncClient, MemoryStorage],
) -> None:
    client, storage = stream_client
    owner = await _register_token(client, "owner@example.com", "owner")
    video = await _upload(client, owner, visibility="public")
    stranger = await _register_token(client, "viewer@example.com", "viewer")

    whole = await client.get(f"/videos/{video['id']}/stream")
    seek = await client.get(
        f"/videos/{video['id']}/stream",
        headers={**_auth(stranger), "Range": "bytes=8-"},
    )
    missing = await client.get(f"/videos/{uuid.uuid4()}/stream")
    invalid = await client.get(
        f"/videos/{video['id']}/stream",
        headers={"Range": "bytes=1000-1001"},
    )

    assert whole.status_code == 200
    assert whole.content == _PAYLOAD
    assert whole.headers["accept-ranges"] == "bytes"
    assert "content-range" not in whole.headers
    assert seek.status_code == 206
    assert seek.content == _PAYLOAD[8:]
    assert seek.headers["content-range"] == f"bytes 8-{len(_PAYLOAD) - 1}/{len(_PAYLOAD)}"
    assert missing.status_code == 404
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == f"bytes */{len(_PAYLOAD)}"
    assert _PAYLOAD not in invalid.content
