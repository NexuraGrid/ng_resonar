from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..services import importer, playlists

router = APIRouter(tags=["playlists"])


class CreateBody(BaseModel):
    name: str = Field("", max_length=200)
    fromUrl: str | None = Field(None, max_length=2048)


class RenameBody(BaseModel):
    name: str


class TracksBody(BaseModel):
    tracks: list[dict] | None = None
    track: dict | None = None


class ReorderBody(BaseModel):
    ids: list[str]


@router.get("/playlists")
async def list_all(
    db: Session = Depends(get_db), user: User = Depends(current_user)
):
    result = await run_in_threadpool(playlists.list_playlists, db, user.id)
    return {"results": result}


@router.post("/playlists")
async def create(
    body: CreateBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    tracks = None
    name = body.name
    if body.fromUrl:
        try:
            res = await importer.import_url(body.fromUrl)
        except importer.UnsupportedUrl as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        tracks = res.get("tracks") or []
        if not name.strip():
            name = res.get("title") or "Playlist importada"
        if not tracks:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No se pudieron extraer pistas de esa URL. Los 'Mix' y "
                    "radios de YouTube a veces no se pueden importar; probá "
                    "con una playlist normal (list=PL…) o un álbum."
                ),
            )
    return await run_in_threadpool(
        playlists.create, db, user.id, name, tracks
    )


@router.get("/playlists/{pid}")
async def get_one(
    pid: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    pl = await run_in_threadpool(playlists.get, db, user.id, pid)
    if not pl:
        raise HTTPException(status_code=404, detail="playlist not found")
    return pl


@router.patch("/playlists/{pid}")
async def rename(
    pid: str,
    body: RenameBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    pl = await run_in_threadpool(playlists.rename, db, user.id, pid, body.name)
    if not pl:
        raise HTTPException(status_code=404, detail="playlist not found")
    return pl


@router.delete("/playlists/{pid}")
async def remove(
    pid: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    removed = await run_in_threadpool(playlists.delete, db, user.id, pid)
    if not removed:
        raise HTTPException(status_code=404, detail="playlist not found")
    return {"removed": True}


@router.post("/playlists/{pid}/tracks")
async def add_tracks(
    pid: str,
    body: TracksBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    items = body.tracks or ([body.track] if body.track else [])
    pl = await run_in_threadpool(
        playlists.add_tracks, db, user.id, pid, items
    )
    if not pl:
        raise HTTPException(status_code=404, detail="playlist not found")
    return pl


@router.delete("/playlists/{pid}/tracks/{track_id}")
async def remove_track(
    pid: str,
    track_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    pl = await run_in_threadpool(
        playlists.remove_track, db, user.id, pid, track_id
    )
    if not pl:
        raise HTTPException(status_code=404, detail="playlist not found")
    return pl


@router.put("/playlists/{pid}/tracks")
async def reorder(
    pid: str,
    body: ReorderBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    pl = await run_in_threadpool(
        playlists.reorder, db, user.id, pid, body.ids
    )
    if not pl:
        raise HTTPException(status_code=404, detail="playlist not found")
    return pl
