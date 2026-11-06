import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user, require_moderator
from app.core.database import get_session
from app.models import User
from app.repositories.channel import ChannelRepository
from app.repositories.comment import CommentRepository
from app.repositories.like import LikeRepository
from app.repositories.video import VideoRepository
from app.schemas.catalog import (
    ChannelResponse,
    CommentCreate,
    CommentPageResponse,
    CommentResponse,
    CommentUpdate,
    LikeResponse,
    ModerationResponse,
    ModerationUpdate,
    VideoCardResponse,
    VideoPageResponse,
)
from app.services.access import VideoAccessRequired, VideoInteractionDenied
from app.services.catalog import CatalogService, ChannelNotFound, InvalidSearchQuery, VideoCard, VideoPage
from app.services.engagement import (
    CommentForbidden,
    CommentNotFound,
    CommentPage,
    EngagementService,
    InvalidComment,
    LikeState,
)
from app.services.videos import VideoNotFound

router = APIRouter(tags=["catalog"])


def get_catalog_service(session: Annotated[AsyncSession, Depends(get_session)]) -> CatalogService:
    return CatalogService(
        videos=VideoRepository(session),
        likes=LikeRepository(session),
        channels=ChannelRepository(session),
        session=session,
    )


def get_engagement_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EngagementService:
    return EngagementService(
        videos=VideoRepository(session),
        comments=CommentRepository(session),
        likes=LikeRepository(session),
        session=session,
    )


def _video_page(page: VideoPage) -> VideoPageResponse:
    return VideoPageResponse(
        items=[_video_card(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _video_card(item: VideoCard) -> VideoCardResponse:
    video = item.video
    return VideoCardResponse(
        id=video.id,
        title=video.title,
        description=video.description,
        visibility=video.visibility,
        author_id=video.author_id,
        channel_id=video.channel_id,
        view_count=video.view_count,
        like_count=item.like_count,
        is_hidden=video.is_hidden,
        created_at=video.created_at,
    )


def _comment_page(page: CommentPage) -> CommentPageResponse:
    return CommentPageResponse(
        items=[CommentResponse.model_validate(comment) for comment in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _like_response(state: LikeState) -> LikeResponse:
    return LikeResponse(video_id=state.video_id, liked=state.liked, like_count=state.like_count)


def _interaction_error(exc: Exception) -> HTTPException:
    if isinstance(exc, VideoNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, VideoAccessRequired):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if isinstance(exc, VideoInteractionDenied):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, InvalidComment):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.detail)
    if isinstance(exc, CommentNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, CommentForbidden):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    raise exc


@router.get("/videos")
async def feed(
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VideoPageResponse:
    return _video_page(await catalog.feed(limit=limit, offset=offset))


@router.get("/videos/search")
async def search_videos(
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VideoPageResponse:
    try:
        page = await catalog.search(q, limit=limit, offset=offset)
    except InvalidSearchQuery as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return _video_page(page)


@router.get("/videos/{video_id}")
async def video_detail(
    video_id: uuid.UUID,
    viewer: Annotated[User | None, Depends(get_optional_user)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
) -> VideoCardResponse:
    try:
        card = await catalog.get_video(video_id, viewer)
    except (VideoNotFound, VideoAccessRequired, VideoInteractionDenied) as exc:
        raise _interaction_error(exc) from exc
    return _video_card(card)


@router.get("/channels/{channel_id}")
async def channel_detail(
    channel_id: uuid.UUID,
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ChannelResponse:
    try:
        channel, _page = await catalog.channel(channel_id, None, limit=1, offset=0)
    except ChannelNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ChannelResponse.model_validate(channel)


@router.get("/channels/{channel_id}/videos")
async def channel_videos(
    channel_id: uuid.UUID,
    viewer: Annotated[User | None, Depends(get_optional_user)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VideoPageResponse:
    try:
        _channel, page = await catalog.channel(
            channel_id,
            viewer,
            limit=limit,
            offset=offset,
        )
    except ChannelNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _video_page(page)


@router.patch("/videos/{video_id}/moderation")
async def moderate_video(
    video_id: uuid.UUID,
    payload: ModerationUpdate,
    _moderator: Annotated[User, Depends(require_moderator)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ModerationResponse:
    try:
        video = await catalog.set_hidden(video_id, is_hidden=payload.is_hidden)
    except VideoNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ModerationResponse(id=video.id, title=video.title, is_hidden=video.is_hidden)


@router.get("/videos/{video_id}/comments")
async def list_comments(
    video_id: uuid.UUID,
    viewer: Annotated[User | None, Depends(get_optional_user)],
    engagement: Annotated[EngagementService, Depends(get_engagement_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CommentPageResponse:
    try:
        page = await engagement.list_comments(video_id, viewer, limit=limit, offset=offset)
    except (VideoNotFound, VideoAccessRequired, VideoInteractionDenied) as exc:
        raise _interaction_error(exc) from exc
    return _comment_page(page)


@router.post("/videos/{video_id}/comments", status_code=status.HTTP_201_CREATED)
async def create_comment(
    video_id: uuid.UUID,
    payload: CommentCreate,
    author: Annotated[User, Depends(get_current_user)],
    engagement: Annotated[EngagementService, Depends(get_engagement_service)],
) -> CommentResponse:
    try:
        comment = await engagement.add_comment(video_id, author, payload.body, payload.parent_id)
    except (VideoNotFound, VideoAccessRequired, VideoInteractionDenied, InvalidComment) as exc:
        raise _interaction_error(exc) from exc
    return CommentResponse.model_validate(comment)


@router.patch("/comments/{comment_id}")
async def update_comment(
    comment_id: uuid.UUID,
    payload: CommentUpdate,
    actor: Annotated[User, Depends(get_current_user)],
    engagement: Annotated[EngagementService, Depends(get_engagement_service)],
) -> CommentResponse:
    try:
        comment = await engagement.update_comment(comment_id, actor, payload.body)
    except (CommentNotFound, CommentForbidden, InvalidComment) as exc:
        raise _interaction_error(exc) from exc
    return CommentResponse.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: uuid.UUID,
    actor: Annotated[User, Depends(get_current_user)],
    engagement: Annotated[EngagementService, Depends(get_engagement_service)],
) -> None:
    try:
        await engagement.delete_comment(comment_id, actor)
    except (CommentNotFound, CommentForbidden) as exc:
        raise _interaction_error(exc) from exc


@router.put("/videos/{video_id}/likes")
async def like_video(
    video_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    engagement: Annotated[EngagementService, Depends(get_engagement_service)],
) -> LikeResponse:
    try:
        state = await engagement.like(video_id, user)
    except (VideoNotFound, VideoAccessRequired, VideoInteractionDenied) as exc:
        raise _interaction_error(exc) from exc
    return _like_response(state)


@router.delete("/videos/{video_id}/likes")
async def unlike_video(
    video_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    engagement: Annotated[EngagementService, Depends(get_engagement_service)],
) -> LikeResponse:
    try:
        state = await engagement.unlike(video_id, user)
    except (VideoNotFound, VideoAccessRequired, VideoInteractionDenied) as exc:
        raise _interaction_error(exc) from exc
    return _like_response(state)
