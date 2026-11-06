from sqlalchemy import ColumnElement, and_

from app.models import Video
from app.models.enums import VideoVisibility


def is_publicly_listed(video: Video) -> bool:
    return video.visibility == VideoVisibility.PUBLIC and not video.is_hidden


def publicly_listed_clause() -> ColumnElement[bool]:
    return and_(
        Video.visibility == VideoVisibility.PUBLIC,
        Video.is_hidden.is_(False),
    )


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
