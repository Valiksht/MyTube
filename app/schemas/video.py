import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import VideoVisibility


class VideoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    visibility: VideoVisibility
    bucket: str
    object_key: str
    original_filename: str
    content_type: str
    size_bytes: int
    author_id: uuid.UUID
    channel_id: uuid.UUID
