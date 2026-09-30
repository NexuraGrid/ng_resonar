from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..deps import current_user
from ..models import User
from ..models.user import ROLE_SUPERADMIN
from ..services import videolib
from ._shared import VideoId

router = APIRouter(tags=["videolib"])


def _require_manage(video_id: str, user: User) -> None:
    if not videolib.can_manage(
        video_id, user.id, user.role == ROLE_SUPERADMIN
    ):
        raise HTTPException(
            status_code=403,
            detail="Solo quien guardó este video (o un admin) puede quitarlo.",
        )


@router.get("/library/videos")
async def list_videos():
    return {"results": videolib.list_saved()}


@router.post("/library/videos/{video_id}")
async def save_video(
    video_id: VideoId,
    quality: int = Query(1080, ge=144, le=2160),
    force: bool = Query(False),
    user: User = Depends(current_user),
):
    if force:
        _require_manage(video_id, user)
    status = await videolib.start_save(
        video_id, quality, force=force, saved_by=user.id
    )
    return {"id": video_id, "status": status}


@router.delete("/library/videos/{video_id}")
async def remove_video(video_id: VideoId, user: User = Depends(current_user)):
    _require_manage(video_id, user)
    return {"removed": videolib.delete_saved(video_id)}


@router.get("/library/videos/{video_id}/file")
async def video_file(video_id: VideoId):
    path = videolib.file_path(video_id)
    if not path:
        raise HTTPException(status_code=404, detail="video not saved")
    return FileResponse(path, media_type="video/mp4")


@router.get("/library/videos/{video_id}/download")
async def video_download(video_id: VideoId):
    path = videolib.file_path(video_id)
    if not path:
        raise HTTPException(status_code=404, detail="video not saved")
    meta = videolib.meta_for(video_id) or {}
    filename = f"{meta.get('title') or video_id}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)
