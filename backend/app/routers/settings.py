import html
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..services import appsettings, scrobble

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings(
    db: Session = Depends(get_db), user: User = Depends(current_user)
):
    return await run_in_threadpool(appsettings.redacted, db, user.id)


@router.put("/settings")
async def put_settings(
    patch: dict,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    await run_in_threadpool(appsettings.update, db, user.id, patch)
    return await run_in_threadpool(appsettings.redacted, db, user.id)


class TrackBody(BaseModel):
    track: dict
    listenedAt: int | None = None


@router.post("/scrobble/now-playing", status_code=202)
async def now_playing(
    body: TrackBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    cfg = await run_in_threadpool(appsettings.load, db, user.id)
    await scrobble.now_playing(cfg, body.track)
    return {"ok": True}


@router.post("/scrobble/submit", status_code=202)
async def submit(
    body: TrackBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    cfg = await run_in_threadpool(appsettings.load, db, user.id)
    await scrobble.submit(cfg, body.track, body.listenedAt or int(time.time()))
    return {"ok": True}


@router.get("/scrobble/lastfm/auth-url")
async def lastfm_auth_url(
    callback: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    cfg = await run_in_threadpool(appsettings.load, db, user.id)
    if not cfg["lastfm"]["apiKey"]:
        raise HTTPException(
            status_code=400, detail="guarda primero la API key de Last.fm"
        )
    url = (
        "https://www.last.fm/api/auth/"
        f"?api_key={quote(cfg['lastfm']['apiKey'], safe='')}"
        f"&cb={quote(callback, safe='')}"
    )
    return {"url": url}


@router.get("/scrobble/lastfm/callback", response_class=HTMLResponse)
async def lastfm_callback(
    token: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    try:
        cfg = await run_in_threadpool(appsettings.load, db, user.id)
        data = await scrobble.lastfm_call(cfg, "auth.getSession", {"token": token})
        session = data["session"]
        await run_in_threadpool(
            appsettings.set_lastfm_session,
            db,
            user.id,
            session["key"],
            session.get("name", ""),
        )
        msg = (
            f"Conectado como {session.get('name', '')}. "
            "Ya puedes cerrar esta pestaña."
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"No se pudo conectar con Last.fm: {exc}"
    msg = html.escape(msg)
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8>"
        f"<body style='font-family:system-ui;background:#0E1414;color:#E6EDEB;"
        f"display:grid;place-items:center;height:100vh;margin:0'>"
        f"<p>{msg}</p>"
    )
