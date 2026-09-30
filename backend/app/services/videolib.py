"""Saved videos: download best video+audio, merge to MP4, keep on disk.

This is what gives real quality (up to 1080p+) and re-watchable / downloadable
files. The plain /api/videos/stream path stays as the instant low-res preview;
once a video is saved the watch page plays the saved file instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time

import yt_dlp
from fastapi.concurrency import run_in_threadpool

from ..config import settings
from .ytdlp import _base_opts, _fmt_duration, _watch_url

MEDIA_DIR = settings.media_dir

_sem = asyncio.Semaphore(settings.video_download_concurrency)

# video_id -> {"status": "downloading"|"ready"|"error", "progress": str|None,
#              "title": str|None, "error": str|None}
_jobs: dict[str, dict] = {}


def _paths(video_id: str) -> tuple[str, str]:
    return (
        os.path.join(MEDIA_DIR, f"{video_id}.mp4"),
        os.path.join(MEDIA_DIR, f"{video_id}.json"),
    )


_PARTIAL_RE = re.compile(r"(\.part(-Frag\d+)?|\.ytdl|\.temp|\.f\d+\.(mp4|m4a|webm))$")


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


def _read_meta(meta_path: str) -> dict | None:
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def file_path(video_id: str) -> str | None:
    mp4, meta = _paths(video_id)
    return mp4 if os.path.exists(mp4) and os.path.exists(meta) else None


def meta_for(video_id: str) -> dict | None:
    _, meta_path = _paths(video_id)
    return _read_meta(meta_path)


def list_saved() -> list[dict]:
    ensure_media_dir()
    items: dict[str, dict] = {}

    for name in sorted(os.listdir(MEDIA_DIR)):
        if not name.endswith(".json"):
            continue
        meta = _read_meta(os.path.join(MEDIA_DIR, name))
        if not meta:
            continue
        vid = meta.get("id") or name[:-5]
        mp4, _ = _paths(vid)
        if not os.path.exists(mp4):
            continue
        meta["status"] = "ready"
        meta["size"] = os.path.getsize(mp4)
        items[vid] = meta

    for vid, job in _jobs.items():
        if job["status"] == "ready" and vid in items:
            continue
        items[vid] = {
            "id": vid,
            "title": job.get("title") or vid,
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "status": job["status"],
            "progress": job.get("progress"),
            "error": job.get("error"),
        }

    return sorted(items.values(), key=lambda m: m.get("savedAt", 0), reverse=True)


def _purge(video_id: str) -> None:
    if not os.path.isdir(MEDIA_DIR):
        return
    for name in os.listdir(MEDIA_DIR):
        if name.startswith(video_id + "."):
            try:
                os.remove(os.path.join(MEDIA_DIR, name))
            except OSError:
                pass


def _on_progress(video_id: str, d: dict) -> None:
    job = _jobs.get(video_id)
    if not job:
        return
    if d.get("status") == "downloading":
        pct = (d.get("_percent_str") or "").strip()
        job["progress"] = f"descargando {pct}" if pct else "descargando…"
        title = (d.get("info_dict") or {}).get("title")
        if title and not job.get("title"):
            job["title"] = title
    elif d.get("status") == "finished":
        job["progress"] = "uniendo audio y video…"


def can_manage(video_id: str, user_id: int, is_admin: bool) -> bool:
    """Whether a user may delete / re-download a saved video.

    The library is shared (everyone sees every saved video), but only whoever
    saved it or a superadmin may remove it. Videos saved before ``savedBy`` was
    recorded are admin-only.
    """
    if is_admin:
        return True
    job = _jobs.get(video_id)
    if job and job.get("savedBy") is not None:
        return job["savedBy"] == user_id
    meta = meta_for(video_id)
    if meta is None:
        # Nothing saved and no job: there is nothing of anyone else's to touch.
        return job is None
    return meta.get("savedBy") == user_id


def _download_sync(video_id: str, quality: int, saved_by: int | None = None) -> dict:
    mp4, meta_path = _paths(video_id)
    opts = {
        **_base_opts(),
        "skip_download": False,
        "format": (
            f"bv*[height<={quality}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={quality}]+ba/b[height<={quality}]/b"
        ),
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(MEDIA_DIR, "%(id)s.%(ext)s"),
        "postprocessors": [{"key": "FFmpegMetadata"}],
        "progress_hooks": [lambda d: _on_progress(video_id, d)],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_watch_url(video_id), download=True)

    if not os.path.exists(mp4):
        for ext in ("mkv", "webm"):
            alt = os.path.join(MEDIA_DIR, f"{video_id}.{ext}")
            if os.path.exists(alt):
                os.replace(alt, mp4)
                break
    if not os.path.exists(mp4):
        raise RuntimeError("no output file produced")

    meta = {
        "id": video_id,
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": _fmt_duration(info.get("duration")),
        "durationSeconds": info.get("duration"),
        "height": info.get("height"),
        "quality": quality,
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "savedAt": int(time.time()),
        "savedBy": saved_by,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    return meta


async def start_save(
    video_id: str, quality: int, *, force: bool = False, saved_by: int | None = None
) -> str:
    if force:
        delete_saved(video_id)

    if file_path(video_id):
        return "ready"

    job = _jobs.get(video_id)
    if job and job["status"] == "downloading":
        return "downloading"

    _jobs[video_id] = {
        "status": "downloading",
        "progress": "en cola…",
        "title": None,
        "error": None,
        "savedBy": saved_by,
    }

    async def _run() -> None:
        async with _sem:
            try:
                meta = await run_in_threadpool(
                    _download_sync, video_id, quality, saved_by
                )
                _jobs[video_id] = {
                    "savedBy": saved_by,
                    "status": "ready",
                    "progress": None,
                    "title": meta.get("title"),
                    "error": None,
                }
            except Exception as exc:  # noqa: BLE001
                _purge(video_id)
                _jobs[video_id] = {
                    "savedBy": saved_by,
                    "status": "error",
                    "progress": None,
                    "title": None,
                    "error": str(exc),
                }

    asyncio.create_task(_run())
    return "downloading"


def delete_saved(video_id: str) -> bool:
    mp4, meta_path = _paths(video_id)
    removed = False
    for path in (mp4, meta_path):
        if os.path.exists(path):
            try:
                os.remove(path)
                removed = True
            except OSError:
                pass
    _jobs.pop(video_id, None)
    return removed
