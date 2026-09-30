from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SavedVideo(Base):
    """A video merged to MP4 in ``media_dir`` (``<video_id>.mp4``).

    The library is shared by every user; ``saved_by`` only decides who may
    remove it (that user or a superadmin). It becomes NULL when the user is
    deleted, which leaves the video admin-managed.
    """

    __tablename__ = "saved_videos"

    video_id: Mapped[str] = mapped_column(String(11), primary_key=True)
    saved_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    uploader: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_saved_videos_saved_at", text("saved_at DESC")),
    )
