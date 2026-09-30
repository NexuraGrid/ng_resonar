"""saved_videos: the saved-video library moves from JSON sidecars to Postgres

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

Existing ``<media_dir>/<id>.json`` sidecars are imported by the app on start
(``videolib.import_legacy_sidecars``), not here: the media volume is the
app's concern and this migration must also run where it isn't mounted.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_videos",
        sa.Column("video_id", sa.String(length=11), primary_key=True),
        sa.Column(
            "saved_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("uploader", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("quality", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_saved_videos_saved_at",
        "saved_videos",
        [sa.text("saved_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_videos_saved_at", table_name="saved_videos")
    op.drop_table("saved_videos")
