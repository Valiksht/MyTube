import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import VideoVisibility


class VideoCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    visibility: VideoVisibility
    author_id: uuid.UUID
    channel_id: uuid.UUID
    view_count: int
    like_count: int
    is_hidden: bool
    created_at: datetime


class VideoPageResponse(BaseModel):
    items: list[VideoCardResponse]
    total: int
    limit: int
    offset: int


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)
    parent_id: uuid.UUID | None = None


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID
    author_id: uuid.UUID
    parent_id: uuid.UUID | None
    body: str
    created_at: datetime


class CommentPageResponse(BaseModel):
    items: list[CommentResponse]
    total: int
    limit: int
    offset: int


class LikeResponse(BaseModel):
    video_id: uuid.UUID
    liked: bool
    like_count: int


class ModerationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_hidden: bool


class ModerationResponse(BaseModel):
    id: uuid.UUID
    title: str
    is_hidden: bool


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    handle: str
    description: str
