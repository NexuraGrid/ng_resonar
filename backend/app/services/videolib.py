"""Saved videos: download best video+audio, merge to MP4, keep on disk.

This is what gives real quality (up to 1080p+) and re-watchable / downloadable
files. The plain /api/videos/stream path stays as the instant low-res preview;
once a video is saved the watch page plays the saved file instead.

Where things live:
  - the file:     ``{media_dir}/<video_id>.mp4``
  - the metadata: a ``saved_videos`` row (the source of truth for "is it saved")
  - in-progress:  a Redis job (``jobs.JobStore("video")``) with status/progress

The library is shared; only whoever saved a video, or a superadmin, may remove
or re-download it (``can_manage``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import SavedVideo
from ..repos import saved_videos as repo
from . import ytdlp
from .jobs import UNFINISHED, JobStore

log = logging.getLogger("resonar.videolib")

MEDIA_DIR = settings.media_dir
store = JobStore("video")
_sem = asyncio.Semaphore(settings.video_download_concurrency)
_PARTIAL_RE = re.compile(r"(\.part(-Frag\d+)?|\.ytdl|\.temp|\.f\d+\.(mp4|m4a|webm))$")
_PROGRESS_MIN_INTERVAL = 1.0  # seconds between progress writes to Redis


def _mp4(video_id: str) -> str:
    return os.path.join(MEDIA_DIR, f"{video_id}.mp4")


def ensure_media_dir() -> None:
    os.makedirs(MEDIA_DIR, exist_ok=True)


def cleanup_partials() -> None:
    """Remove leftover yt-dlp temp files. Startup only — never while a download
    may be running, or it will yank files out from under yt-dlp."""
    ensure_media_dir()
    for name in os.listdir(MEDIA_DIR):
        if _PARTIAL_RE.search(name):
            try:
                os.remove(os.path.join(MEDIA_DIR, name))
            except OSError:
                pass


def import_legacy_sidecars() -> int:
    """One-off: turn pre-table ``<id>.json`` sidecars into rows.

    Each imported sidecar is renamed to ``.json.migrated``. Safe to run on
    every start: once renamed there is nothing left to import.
    """
    ensure_media_dir()
    imported = 0
    with SessionLocal() as db:
        for name in sorted(os.listdir(MEDIA_DIR)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(MEDIA_DIR, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue
            vid = meta.get("id") or name[:-5]
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) or not os.path.exists(_mp4(vid)):
                continue
            repo.upsert(
                db,
                video_id=vid,
                saved_by=meta.get("savedBy"),
                title=meta.get("title") or vid,
                uploader=meta.get("uploader"),
                duration_seconds=meta.get("durationSeconds"),
                height=meta.get("height"),
                quality=meta.get("quality") or 1080,
                size_bytes=os.path.getsize(_mp4(vid)),
                saved_at=datetime.fromtimestamp(
                    meta.get("savedAt") or time.time(), tz=timezone.utc
                ),
            )
            db.commit()
            os.replace(path, path + ".migrated")
            imported += 1
    if imported:
        log.info("imported %d legacy saved-video sidecars", imported)
    return imported


def _row_json(row: SavedVideo) -> dict:
    return {
        "id": row.video_id,
        "title": row.title,
        "uploader": row.uploader,
        "duration": ytdlp.fmt_duration(row.duration_seconds),
        "durationSeconds": row.duration_seconds,
        "height": row.height,
        "quality": row.quality,
        "thumbnail": ytdlp.thumbnail_url(row.video_id),
        "savedAt": int(row.saved_at.timestamp()),
        "size": row.size_bytes,
        "status": "ready",
    }


def _job_json(video_id: str, job: dict) -> dict:
    status = job.get("status")
    return {
        "id": video_id,
        "title": job.get("title") or video_id,
        "thumbnail": ytdlp.thumbnail_url(video_id),
        # The client only knows downloading / ready / error.
        "status": "downloading" if status == "queued" else status,
        "progress": job.get("progress"),
        "error": job.get("error"),
        "savedAt": int(job.get("createdAt") or 0),
    }


def _may_manage(saved_by: int | None, user_id: int, is_admin: bool) -> bool:
    return is_admin or (saved_by is not None and saved_by == user_id)


async def list_saved(db: Session, user_id: int, is_admin: bool) -> list[dict]:
    rows = await run_in_threadpool(repo.list_, db)
    items: dict[str, dict] = {}
    for row in rows:
        if os.path.exists(_mp4(row.video_id)):
            items[row.video_id] = {
                **_row_json(row),
                "canDelete": _may_manage(row.saved_by, user_id, is_admin),
            }
    for vid, job in (await store.all()).items():
        if job.get("status") == "ready" or vid in items:
            continue
        items[vid] = {
            **_job_json(vid, job),
            "canDelete": job.get("status") not in UNFINISHED
            or _may_manage(job.get("savedBy"), user_id, is_admin),
        }
    return sorted(items.values(), key=lambda m: m.get("savedAt", 0), reverse=True)


async def can_manage(db: Session, video_id: str, user_id: int, is_admin: bool) -> bool:
    """Whether a user may delete / force re-download ``video_id``.

    A saved video: only its saver or an admin. Nothing saved: anyone, unless
    someone else's download of it is still running.
    """
    if is_admin:
        return True
    row = await run_in_threadpool(repo.get, db, video_id)
    if row is not None:
        return row.saved_by == user_id
    job = await store.get(video_id)
    if job and job.get("status") in UNFINISHED:
        return job.get("savedBy") == user_id
    return True


async def file_path(db: Session, video_id: str) -> str | None:
    row = await run_in_threadpool(repo.get, db, video_id)
    path = _mp4(video_id)
    return path if row is not None and os.path.exists(path) else None


async def title_for(db: Session, video_id: str) -> str | None:
    row = await run_in_threadpool(repo.get, db, video_id)
    return row.title if row else None


def _purge_files(video_id: str) -> None:
    if not os.path.isdir(MEDIA_DIR):
        return
    for name in os.listdir(MEDIA_DIR):
        if name.startswith(video_id + "."):
            try:
                os.remove(os.path.join(MEDIA_DIR, name))
            except OSError:
                pass


def _progress_hook(video_id: str):
    """yt-dlp progress hook (runs on the download thread), throttled."""
    last = {"t": 0.0, "text": None}

    def hook(d: dict) -> None:
        fields: dict = {}
        if d.get("status") == "downloading":
            pct = (d.get("_percent_str") or "").strip()
            fields["progress"] = f"descargando {pct}" if pct else "descargando…"
            title = (d.get("info_dict") or {}).get("title")
            if title:
                fields["title"] = title
        elif d.get("status") == "finished":
            fields["progress"] = "uniendo audio y video…"
        else:
            return
        now = time.monotonic()
        if fields["progress"] == last["text"] or (
            now - last["t"] < _PROGRESS_MIN_INTERVAL and d.get("status") != "finished"
        ):
            return
        last["t"], last["text"] = now, fields["progress"]
        store.update_from_thread(video_id, **fields)

    return hook


def _record(video_id: str, quality: int, saved_by: int | None, meta: dict) -> None:
    with SessionLocal() as db:
        repo.upsert(
            db,
            video_id=video_id,
            saved_by=saved_by,
            title=meta.get("title") or video_id,
            uploader=meta.get("uploader"),
            duration_seconds=meta.get("duration_seconds"),
            height=meta.get("height"),
            quality=quality,
            size_bytes=os.path.getsize(_mp4(video_id)),
            saved_at=datetime.now(tz=timezone.utc),
        )
        db.commit()


async def _run(video_id: str, quality: int, saved_by: int | None) -> None:
    async with store.running(video_id):
        async with _sem:
            await store.update(video_id, status="downloading")
            try:
                ensure_media_dir()
                meta = await run_in_threadpool(
                    ytdlp.download_video_sync,
                    video_id,
                    quality,
                    MEDIA_DIR,
                    _progress_hook(video_id),
                )
                if await store.get(video_id) is None:
                    # Removed while it downloaded: don't resurrect it.
                    _purge_files(video_id)
                    return
                await run_in_threadpool(_record, video_id, quality, saved_by, meta)
            except Exception as exc:  # noqa: BLE001
                _purge_files(video_id)
                await store.update(
                    video_id, status="error", progress=None, error=str(exc)
                )
            else:
                await store.delete(video_id)


async def start_save(
    db: Session,
    video_id: str,
    quality: int,
    *,
    force: bool = False,
    saved_by: int | None = None,
) -> str:
    if force:
        await delete_saved(db, video_id)
    elif await file_path(db, video_id):
        return "ready"
    job = await store.get(video_id)
    if job and job.get("status") in UNFINISHED:
        return "downloading"
    await store.create(
        video_id,
        status="queued",
        progress="en cola…",
        title=None,
        error=None,
        savedBy=saved_by,
        createdAt=time.time(),
    )
    asyncio.create_task(_run(video_id, quality, saved_by))
    return "downloading"


async def delete_saved(db: Session, video_id: str) -> bool:
    removed = await run_in_threadpool(repo.delete_, db, video_id)
    had_file = os.path.exists(_mp4(video_id))
    _purge_files(video_id)
    await store.delete(video_id)
    return removed or had_file
