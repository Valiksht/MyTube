"""SQLAlchemy models. Importing this package registers every table on Base.metadata."""

from sqlalchemy.orm import configure_mappers

from app.models.base import Base
from app.models.channel import Channel
from app.models.comment import Comment
from app.models.like import Like
from app.models.subscription import Subscription
from app.models.user import User
from app.models.video import Video

configure_mappers()

__all__ = [
    "Base",
    "Channel",
    "Comment",
    "Like",
    "Subscription",
    "User",
    "Video",
]
