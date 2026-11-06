"""Index the public feed filter.

Revision ID: 20261106_0002
Revises: 20261106_0001
Create Date: 2026-11-06

"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261106_0002"
down_revision: str | None = "20261106_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_videos_feed_created_at",
        "videos",
        ["is_hidden", "visibility", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_videos_feed_created_at", table_name="videos")
