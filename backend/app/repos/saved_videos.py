"""Saved-video library rows. Shared by all users (see ``models.SavedVideo``)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..models import SavedVideo


def get(db: Session, video_id: str) -> SavedVideo | None:
    return db.get(SavedVideo, video_id)


def list_(db: Session) -> list[SavedVideo]:
    stmt = select(SavedVideo).order_by(SavedVideo.saved_at.desc())
    return list(db.execute(stmt).scalars())


def upsert(db: Session, **values) -> None:
    """Insert or replace the row for ``values["video_id"]``."""
    stmt = insert(SavedVideo).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[SavedVideo.video_id],
        set_={k: v for k, v in values.items() if k != "video_id"},
    )
    db.execute(stmt)
    db.flush()


def delete_(db: Session, video_id: str) -> bool:
    result = db.execute(delete(SavedVideo).where(SavedVideo.video_id == video_id))
    db.flush()
    return result.rowcount > 0
