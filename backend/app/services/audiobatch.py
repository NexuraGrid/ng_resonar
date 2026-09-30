"""Background job: download N tracks as MP3/etc and zip them up."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile

from fastapi.concurrency import run_in_threadpool

from ..config import settings
from . import ytdlp

BATCH_DIR = os.path.join(settings.data_dir, "batches")

_jobs: dict[str, dict] = {}
_sem = asyncio.Semaphore(1)
# Unfinished (queued or running) batch jobs one user may have at once. Each job
# is up to 100 tracks of yt-dlp + ffmpeg work and a zip on disk.
MAX_ACTIVE_PER_USER = 2
_JOB_ID_RE = re.compile(r"^b_[0-9a-f]{32}$")


class TooManyJobs(Exception):
    """The user already has ``MAX_ACTIVE_PER_USER`` unfinished jobs."""


def ensure_dir() -> None:
    os.makedirs(BATCH_DIR, exist_ok=True)


def cleanup_old(max_age: int = 86_400) -> None:
    ensure_dir()
    now = time.time()
    for name in os.listdir(BATCH_DIR):
        path = os.path.join(BATCH_DIR, name)
        try:
            if now - os.path.getmtime(path) > max_age:
                os.remove(path)
        except OSError:
            pass


def status(job_id: str, owner: int | None = None) -> dict | None:
    """The job, or ``None`` if unknown or (when ``owner`` is given) not theirs."""
    job = _jobs.get(job_id)
    if job is None or (owner is not None and job.get("owner") != owner):
        return None
    return job


def zip_path(job_id: str) -> str | None:
    if not _JOB_ID_RE.match(job_id):
        return None
    path = os.path.join(BATCH_DIR, f"{job_id}.zip")
    return path if os.path.exists(path) else None


def _run_sync(job_id: str, ids: list[str], fmt: str) -> None:
    job = _jobs[job_id]
    workdir = tempfile.mkdtemp(prefix="resonar-batch-")
    files: list[str] = []
    try:
        for i, vid in enumerate(ids):
            job["progress"] = {"done": i, "total": len(ids)}
            try:
                path, tmpd = ytdlp._download_sync(vid, fmt)
                dest = os.path.join(workdir, os.path.basename(path))
                shutil.move(path, dest)
                shutil.rmtree(tmpd, ignore_errors=True)
                files.append(dest)
            except Exception:  # noqa: BLE001 - skip the ones that fail
                continue
        job["progress"] = {"done": len(ids), "total": len(ids)}

        if not files:
            raise RuntimeError("no se pudo descargar ninguna pista")

        ensure_dir()
        zpath = os.path.join(BATCH_DIR, f"{job_id}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as zf:
            for fp in files:
                zf.write(fp, arcname=os.path.basename(fp))
        job["status"] = "ready"
        job["count"] = len(files)
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def start(
    ids: list[str], fmt: str, name: str | None, *, owner: int
) -> str:
    active = sum(
        1
        for j in _jobs.values()
        if j.get("owner") == owner and j["status"] == "downloading"
    )
    if active >= MAX_ACTIVE_PER_USER:
        raise TooManyJobs()
    job_id = "b_" + uuid.uuid4().hex
    _jobs[job_id] = {
        "owner": owner,
        "status": "downloading",
        "progress": {"done": 0, "total": len(ids)},
        "error": None,
        "filename": f"{(name or 'playlist').strip() or 'playlist'}.zip",
    }

    async def _run() -> None:
        async with _sem:
            await run_in_threadpool(_run_sync, job_id, ids, fmt)

    asyncio.create_task(_run())
    return job_id
