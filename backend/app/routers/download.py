import os
import re
import shutil

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ..deps import current_user
from ..models import User
from ..services import audiobatch, ytdlp
from ._shared import VideoId

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

router = APIRouter(tags=["download"])


@router.get("/download/{video_id}")
async def download(
    video_id: VideoId,
    format: str = Query("mp3"),
):
    fmt = format.lower()
    if fmt not in ytdlp.DOWNLOAD_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"format must be one of {sorted(ytdlp.DOWNLOAD_FORMATS)}",
        )
    try:
        path, tmpdir = await ytdlp.download(video_id, fmt)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"download failed: {exc}") from exc

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=os.path.basename(path),
        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True),
    )


class BatchBody(BaseModel):
    ids: list[str] = Field(max_length=500)
    format: str = "mp3"
    name: str | None = Field(None, max_length=200)


@router.post("/download/batch")
async def download_batch(
    body: BatchBody, user: User = Depends(current_user)
):
    ids = [i for i in body.ids if i][:100]
    if any(not _VIDEO_ID_RE.match(i) for i in ids):
        raise HTTPException(status_code=400, detail="invalid track id")
    if not ids:
        raise HTTPException(status_code=400, detail="no track ids")
    fmt = body.format.lower()
    if fmt not in ytdlp.DOWNLOAD_FORMATS:
        raise HTTPException(status_code=400, detail="bad format")
    try:
        job_id = await audiobatch.start(ids, fmt, body.name, owner=user.id)
    except audiobatch.TooManyJobs:
        raise HTTPException(
            status_code=429,
            detail="Ya tienes descargas en curso; espera a que terminen.",
        )
    return {"jobId": job_id}


@router.get("/download/batch/{job_id}")
async def download_batch_status(
    job_id: str, user: User = Depends(current_user)
):
    st = audiobatch.status(job_id, owner=user.id)
    if not st:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "status": st["status"],
        "progress": st.get("progress"),
        "error": st.get("error"),
        "ready": st["status"] == "ready" and audiobatch.zip_path(job_id) is not None,
    }


@router.get("/download/batch/{job_id}/file")
async def download_batch_file(
    job_id: str, user: User = Depends(current_user)
):
    st = audiobatch.status(job_id, owner=user.id)
    path = audiobatch.zip_path(job_id) if st else None
    if not st or not path:
        raise HTTPException(status_code=404, detail="not ready")
    return FileResponse(path, media_type="application/zip", filename=st.get("filename"))
