from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..models.user import ROLE_SUPERADMIN
from ..services import videolib
from ._shared import VideoId

router = APIRouter(tags=["videolib"])


def _is_admin(user: User) -> bool:
    return user.role == ROLE_SUPERADMIN


async def _require_manage(db: Session, video_id: str, user: User) -> None:
    if not await videolib.can_manage(db, video_id, user.id, _is_admin(user)):
        raise HTTPException(
            status_code=403,
            detail="Solo quien guardó este video (o un admin) puede quitarlo.",
        )


@router.get("/library/videos")
async def list_videos(
    db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return {"results": await videolib.list_saved(db, user.id, _is_admin(user))}


@router.post("/library/videos/{video_id}")
async def save_video(
    video_id: VideoId,
    quality: int = Query(1080, ge=144, le=2160),
    force: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if force:
        await _require_manage(db, video_id, user)
    status = await videolib.start_save(
        db, video_id, quality, force=force, saved_by=user.id
    )
    return {"id": video_id, "status": status}


@router.delete("/library/videos/{video_id}")
async def remove_video(
    video_id: VideoId,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    await _require_manage(db, video_id, user)
    return {"removed": await videolib.delete_saved(db, video_id)}


@router.get("/library/videos/{video_id}/file")
async def video_file(video_id: VideoId, db: Session = Depends(get_db)):
    path = await videolib.file_path(db, video_id)
    if not path:
        raise HTTPException(status_code=404, detail="video not saved")
    return FileResponse(path, media_type="video/mp4")


@router.get("/library/videos/{video_id}/download")
async def video_download(video_id: VideoId, db: Session = Depends(get_db)):
    path = await videolib.file_path(db, video_id)
    if not path:
        raise HTTPException(status_code=404, detail="video not saved")
    title = await videolib.title_for(db, video_id)
    return FileResponse(path, media_type="video/mp4", filename=f"{title or video_id}.mp4")
