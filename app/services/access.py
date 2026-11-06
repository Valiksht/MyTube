from app.models import User, Video
from app.models.enums import UserRole, VideoVisibility


class VideoAccessRequired(Exception):
    def __init__(self) -> None:
        super().__init__("Could not validate credentials")


class VideoInteractionDenied(Exception):
    def __init__(self) -> None:
        super().__init__("Video is not available")


def can_moderate(user: User) -> bool:
    return user.role in {UserRole.MODERATOR, UserRole.ADMIN}


def view_decision(video: Video, viewer: User | None) -> str:
    """Return allow, authenticate, deny, or hide."""
    if viewer is not None and viewer.id == video.author_id:
        return "allow"
    if video.visibility == VideoVisibility.PRIVATE:
        return "authenticate" if viewer is None else "deny"
    if video.is_hidden:
        if viewer is not None and can_moderate(viewer):
            return "allow"
        return "hide"
    return "allow"
