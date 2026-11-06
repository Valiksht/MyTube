from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import VideoVisibility, pg_enum


class Video(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "videos"

    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    visibility: Mapped[VideoVisibility] = mapped_column(
        pg_enum(VideoVisibility, "video_visibility"),
        nullable=False,
        default=VideoVisibility.PUBLIC,
        server_default=VideoVisibility.PUBLIC.value,
    )
    is_hidden: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=false(),
    )
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumbnail_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )

    author: Mapped[User] = relationship(back_populates="videos")
    channel: Mapped[Channel] = relationship(back_populates="videos")
    comments: Mapped[list[Comment]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    likes: Mapped[list[Like]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("char_length(title) >= 1", name="title_not_empty"),
        CheckConstraint("char_length(bucket) >= 1", name="bucket_not_empty"),
        CheckConstraint("char_length(object_key) >= 1", name="object_key_not_empty"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("view_count >= 0", name="view_count_non_negative"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="duration_non_negative",
        ),
        Index("ix_videos_author_id", author_id),
        Index("ix_videos_channel_id_created_at", channel_id, "created_at"),
        Index("ix_videos_feed_created_at", "is_hidden", "visibility", "created_at"),
    )
