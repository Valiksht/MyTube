import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.catalog import get_catalog_service, get_engagement_service
from app.core.config import Settings
from app.models import Channel, Video
from app.models.enums import UserRole, VideoVisibility
from app.services.catalog import CatalogService
from app.services.engagement import EngagementService
from tests.conftest import _application_with_role_zones
from tests.fakes import (
    FastPasswordHasher,
    InMemoryChannelRepository,
    InMemoryCommentRepository,
    InMemoryLikeRepository,
    InMemoryUserRepository,
    InMemoryVideoRepository,
    NullSession,
)


def _video(
    *,
    author_id: uuid.UUID,
    title: str,
    created_at: datetime,
    visibility: VideoVisibility = VideoVisibility.PUBLIC,
    is_hidden: bool = False,
) -> Video:
    return Video(
        id=uuid.uuid4(),
        author_id=author_id,
        channel_id=uuid.uuid4(),
        title=title,
        description="",
        visibility=visibility,
        is_hidden=is_hidden,
        bucket="mytube",
        object_key=f"videos/{uuid.uuid4()}.mp4",
        thumbnail_object_key=None,
        original_filename="clip.mp4",
        content_type="video/mp4",
        size_bytes=12,
        duration_seconds=None,
        view_count=0,
        created_at=created_at,
    )


@pytest.fixture
async def community(
    settings: Settings,
    user_store: InMemoryUserRepository,
    hasher: FastPasswordHasher,
) -> AsyncIterator[tuple[AsyncClient, InMemoryVideoRepository, InMemoryUserRepository]]:
    videos = InMemoryVideoRepository()
    likes = InMemoryLikeRepository()
    comments = InMemoryCommentRepository()
    channels = InMemoryChannelRepository()
    application = _application_with_role_zones(settings, user_store, hasher)
    application.dependency_overrides[get_catalog_service] = lambda: CatalogService(
        videos=videos,
        likes=likes,
        channels=channels,
        session=NullSession(),
    )
    application.dependency_overrides[get_engagement_service] = lambda: EngagementService(
        videos=videos,
        comments=comments,
        likes=likes,
        session=NullSession(),
    )
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, videos, user_store, channels


async def _register(client: AsyncClient, email: str, username: str) -> tuple[str, uuid.UUID]:
    response = await client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "password123"},
    )
    assert response.status_code == 201
    body = response.json()
    token: str = body["access_token"]
    return token, uuid.UUID(body["user"]["id"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_feed_paginates_public_videos_and_skips_hidden_ones(
    community: tuple[
        AsyncClient,
        InMemoryVideoRepository,
        InMemoryUserRepository,
        InMemoryChannelRepository,
    ],
) -> None:
    client, videos, _users, _channels = community
    _token, author_id = await _register(client, "author@example.com", "author")
    base = datetime(2026, 11, 6, tzinfo=timezone.utc)
    await videos.add(
        _video(author_id=author_id, title="First", created_at=base),
    )
    await videos.add(
        _video(author_id=author_id, title="Second", created_at=base + timedelta(minutes=1)),
    )
    await videos.add(
        _video(author_id=author_id, title="Third", created_at=base + timedelta(minutes=2)),
    )
    await videos.add(
        _video(
            author_id=author_id,
            title="Secret",
            created_at=base + timedelta(minutes=3),
            visibility=VideoVisibility.PRIVATE,
        ),
    )
    await videos.add(
        _video(
            author_id=author_id,
            title="Link only",
            created_at=base + timedelta(minutes=4),
            visibility=VideoVisibility.UNLISTED,
        ),
    )
    await videos.add(
        _video(
            author_id=author_id,
            title="Removed",
            created_at=base + timedelta(minutes=5),
            is_hidden=True,
        ),
    )

    first_page = await client.get("/videos", params={"limit": 2, "offset": 0})
    second_page = await client.get("/videos", params={"limit": 2, "offset": 2})

    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert [item["title"] for item in first_page.json()["items"]] == ["Third", "Second"]
    assert second_page.json()["items"][0]["title"] == "First"
    assert all(item["is_hidden"] is False for item in first_page.json()["items"])


@pytest.mark.asyncio
async def test_search_matches_title_and_ignores_hidden_videos(
    community: tuple[
        AsyncClient,
        InMemoryVideoRepository,
        InMemoryUserRepository,
        InMemoryChannelRepository,
    ],
) -> None:
    client, videos, _users, _channels = community
    _token, author_id = await _register(client, "author@example.com", "author")
    moment = datetime(2026, 11, 6, tzinfo=timezone.utc)
    await videos.add(_video(author_id=author_id, title="Night Market", created_at=moment))
    await videos.add(
        _video(
            author_id=author_id,
            title="Night Hidden",
            created_at=moment,
            is_hidden=True,
        ),
    )
    await videos.add(
        _video(
            author_id=author_id,
            title="Night Private",
            created_at=moment,
            visibility=VideoVisibility.PRIVATE,
        ),
    )

    found = await client.get("/videos/search", params={"q": "night"})
    blank = await client.get("/videos/search", params={"q": "   "})

    assert found.status_code == 200
    assert [item["title"] for item in found.json()["items"]] == ["Night Market"]
    assert blank.status_code == 422


@pytest.mark.asyncio
async def test_comments_and_likes_follow_visibility(
    community: tuple[
        AsyncClient,
        InMemoryVideoRepository,
        InMemoryUserRepository,
        InMemoryChannelRepository,
    ],
) -> None:
    client, videos, _users, _channels = community
    author, author_id = await _register(client, "author@example.com", "author")
    viewer, _viewer_id = await _register(client, "viewer@example.com", "viewer")
    moment = datetime(2026, 11, 6, tzinfo=timezone.utc)
    public = await videos.add(_video(author_id=author_id, title="Public", created_at=moment))
    private = await videos.add(
        _video(
            author_id=author_id,
            title="Private",
            created_at=moment,
            visibility=VideoVisibility.PRIVATE,
        ),
    )
    hidden = await videos.add(
        _video(author_id=author_id, title="Hidden", created_at=moment, is_hidden=True),
    )

    created = await client.post(
        f"/videos/{public.id}/comments",
        headers=_auth(viewer),
        json={"body": "  Hello there  "},
    )
    assert created.status_code == 201
    comment_id = created.json()["id"]
    assert created.json()["body"] == "Hello there"

    listed = await client.get(f"/videos/{public.id}/comments")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    edited = await client.patch(
        f"/comments/{comment_id}",
        headers=_auth(viewer),
        json={"body": "Updated"},
    )
    forbidden_edit = await client.patch(
        f"/comments/{comment_id}",
        headers=_auth(author),
        json={"body": "No"},
    )
    assert edited.status_code == 200
    assert edited.json()["body"] == "Updated"
    assert forbidden_edit.status_code == 403

    liked = await client.put(f"/videos/{public.id}/likes", headers=_auth(viewer))
    liked_again = await client.put(f"/videos/{public.id}/likes", headers=_auth(viewer))
    feed = await client.get("/videos")
    assert liked.status_code == 200
    assert liked.json() == {"video_id": str(public.id), "liked": True, "like_count": 1}
    assert liked_again.json()["like_count"] == 1
    assert feed.json()["items"][0]["like_count"] == 1

    removed = await client.delete(f"/videos/{public.id}/likes", headers=_auth(viewer))
    assert removed.json()["liked"] is False
    assert removed.json()["like_count"] == 0

    private_comment = await client.post(
        f"/videos/{private.id}/comments",
        headers=_auth(viewer),
        json={"body": "Nope"},
    )
    hidden_like = await client.put(f"/videos/{hidden.id}/likes", headers=_auth(viewer))
    assert private_comment.status_code == 403
    assert hidden_like.status_code == 404

    deleted = await client.delete(f"/comments/{comment_id}", headers=_auth(viewer))
    assert deleted.status_code == 204
    assert (await client.get(f"/videos/{public.id}/comments")).json()["total"] == 0


@pytest.mark.asyncio
async def test_moderator_hides_video_from_feed_and_search(
    community: tuple[
        AsyncClient,
        InMemoryVideoRepository,
        InMemoryUserRepository,
        InMemoryChannelRepository,
    ],
) -> None:
    client, videos, users, _channels = community
    member, _member_id = await _register(client, "member@example.com", "member")
    moderator, moderator_id = await _register(client, "mod@example.com", "moderator")
    users.users[moderator_id].role = UserRole.MODERATOR
    video = await videos.add(
        _video(
            author_id=moderator_id,
            title="Night Market",
            created_at=datetime(2026, 11, 6, tzinfo=timezone.utc),
        ),
    )

    denied = await client.patch(
        f"/videos/{video.id}/moderation",
        headers=_auth(member),
        json={"is_hidden": True},
    )
    hidden = await client.patch(
        f"/videos/{video.id}/moderation",
        headers=_auth(moderator),
        json={"is_hidden": True},
    )
    feed = await client.get("/videos")
    search = await client.get("/videos/search", params={"q": "Night"})

    assert denied.status_code == 403
    assert hidden.status_code == 200
    assert hidden.json()["is_hidden"] is True
    assert feed.json()["total"] == 0
    assert search.json()["total"] == 0

    restored = await client.patch(
        f"/videos/{video.id}/moderation",
        headers=_auth(moderator),
        json={"is_hidden": False},
    )
    assert restored.json()["is_hidden"] is False
    assert (await client.get("/videos")).json()["total"] == 1


@pytest.mark.asyncio
async def test_video_and_channel_pages_hide_private_clips_from_strangers(
    community: tuple[
        AsyncClient,
        InMemoryVideoRepository,
        InMemoryUserRepository,
        InMemoryChannelRepository,
    ],
) -> None:
    client, videos, _users, channels = community
    owner, owner_id = await _register(client, "owner@example.com", "owner")
    stranger, _stranger_id = await _register(client, "guest@example.com", "guest")
    channel = Channel(
        id=uuid.uuid4(),
        owner_id=owner_id,
        name="Owner",
        handle="owner",
        description="Канал",
    )
    await channels.add(channel)
    moment = datetime(2026, 11, 6, tzinfo=timezone.utc)
    public = await videos.add(
        _video(author_id=owner_id, title="Shown", created_at=moment),
    )
    public.channel_id = channel.id
    private = await videos.add(
        _video(
            author_id=owner_id,
            title="Mine",
            created_at=moment,
            visibility=VideoVisibility.PRIVATE,
        ),
    )
    private.channel_id = channel.id

    public_card = await client.get(f"/videos/{public.id}")
    private_card = await client.get(f"/videos/{private.id}", headers=_auth(stranger))
    owner_card = await client.get(f"/videos/{private.id}", headers=_auth(owner))
    channel_page = await client.get(f"/channels/{channel.id}")
    guest_list = await client.get(f"/channels/{channel.id}/videos")
    owner_list = await client.get(f"/channels/{channel.id}/videos", headers=_auth(owner))

    assert public_card.status_code == 200
    assert public_card.json()["title"] == "Shown"
    assert private_card.status_code == 403
    assert owner_card.status_code == 200
    assert channel_page.status_code == 200
    assert channel_page.json()["handle"] == "owner"
    assert [item["title"] for item in guest_list.json()["items"]] == ["Shown"]
    assert {item["title"] for item in owner_list.json()["items"]} == {"Shown", "Mine"}
