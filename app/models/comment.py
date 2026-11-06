from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Comment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "comments"

    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comments.id", ondelete="SET NULL"),
        nullable=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    video: Mapped[Video] = relationship(back_populates="comments")
    author: Mapped[User] = relationship(back_populates="comments")
    parent: Mapped[Comment | None] = relationship(
        back_populates="replies",
        remote_side=lambda: Comment.id,
    )
    replies: Mapped[list[Comment]] = relationship(
        back_populates="parent",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("char_length(body) >= 1", name="body_not_empty"),
        Index("ix_comments_video_id_created_at", video_id, "created_at"),
        Index("ix_comments_author_id", author_id),
        Index("ix_comments_parent_id", parent_id),
    )
