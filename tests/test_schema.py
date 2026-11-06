from app.models import Base
from app.models.enums import UserRole, VideoVisibility


def _ondelete(table_name: str, column_name: str) -> str | None:
    foreign_key = next(
        fk
        for fk in Base.metadata.tables[table_name].foreign_keys
        if fk.parent.name == column_name
    )
    return foreign_key.ondelete


def test_expected_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "channels",
        "videos",
        "comments",
        "likes",
        "subscriptions",
    }


def test_user_role_values() -> None:
    column = Base.metadata.tables["users"].c.role
    assert [item.value for item in UserRole] == ["user", "moderator", "admin"]
    assert column.nullable is False


def test_video_visibility_and_storage_columns() -> None:
    columns = Base.metadata.tables["videos"].c
    assert [item.value for item in VideoVisibility] == ["public", "unlisted", "private"]
    assert columns.visibility.nullable is False
    assert columns.is_hidden.nullable is False
    assert columns.bucket.nullable is False
    assert columns.object_key.nullable is False
    assert columns.thumbnail_object_key.nullable is True
    assert columns.author_id.nullable is False
    assert columns.channel_id.nullable is False


def test_cascade_rules() -> None:
    assert _ondelete("channels", "owner_id") == "CASCADE"
    assert _ondelete("videos", "author_id") == "CASCADE"
    assert _ondelete("videos", "channel_id") == "CASCADE"
    assert _ondelete("comments", "video_id") == "CASCADE"
    assert _ondelete("comments", "author_id") == "CASCADE"
    assert _ondelete("comments", "parent_id") == "SET NULL"
    assert _ondelete("likes", "user_id") == "CASCADE"
    assert _ondelete("likes", "video_id") == "CASCADE"
    assert _ondelete("subscriptions", "subscriber_id") == "CASCADE"
    assert _ondelete("subscriptions", "channel_id") == "CASCADE"


def test_like_and_subscription_primary_keys() -> None:
    assert [column.name for column in Base.metadata.tables["likes"].primary_key] == [
        "user_id",
        "video_id",
    ]
    assert [
        column.name for column in Base.metadata.tables["subscriptions"].primary_key
    ] == ["subscriber_id", "channel_id"]


def test_check_constraint_names() -> None:
    names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name is not None and constraint.name.startswith("ck_")
    }
    assert "ck_users_email_length" in names
    assert "ck_videos_size_bytes_non_negative" in names
    assert "ck_comments_body_not_empty" in names
    assert all("_ck_" not in name for name in names)


def test_case_insensitive_uniqueness() -> None:
    index_names = {index.name for index in Base.metadata.tables["users"].indexes}
    channel_indexes = {index.name for index in Base.metadata.tables["channels"].indexes}
    assert "uq_users_email_lower" in index_names
    assert "uq_users_username_lower" in index_names
    assert "uq_channels_handle_lower" in channel_indexes
