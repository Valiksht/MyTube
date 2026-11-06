import uuid
from pathlib import Path

ALLOWED_EXTENSIONS: dict[str, str] = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".ogg": "video/ogg",
}


class UnsupportedVideoType(Exception):
    def __init__(self) -> None:
        super().__init__("Unsupported video type")


def safe_filename(filename: str | None) -> str:
    raw_name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    cleaned = raw_name.replace("\x00", "") or "video"
    return cleaned[:255]


def resolve_media_type(filename: str, declared: str | None) -> str:
    expected = ALLOWED_EXTENSIONS.get(Path(filename).suffix.lower())
    if expected is None:
        raise UnsupportedVideoType

    if declared is None:
        return expected

    actual = declared.split(";", maxsplit=1)[0].strip().lower()
    if actual in {"", "application/octet-stream"}:
        return expected
    if actual != expected:
        raise UnsupportedVideoType
    return expected


def build_object_key(author_id: uuid.UUID, filename: str, object_id: uuid.UUID) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedVideoType
    return f"videos/{author_id}/{object_id}{extension}"
