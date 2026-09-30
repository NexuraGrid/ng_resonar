"""Background job: download N tracks as MP3/etc and zip them up.

Job state lives in Redis (``jobs.JobStore``); the zip lands in
``{data_dir}/batches/<job_id>.zip`` and is swept after a day.
"""

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
from .jobs import UNFINISHED, JobStore

BATCH_DIR = os.path.join(settings.data_dir, "batches")
store = JobStore("batch")
# One batch runs at a time per process: each is up to 100 yt-dlp + ffmpeg runs.
_sem = asyncio.Semaphore(1)
# Unfinished (queued or running) batch jobs one user may have at once.
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


async def status(job_id: str, owner: int) -> dict | None:
    """The job, or ``None`` if unknown or not ``owner``'s."""
    if not _JOB_ID_RE.match(job_id):
        return None
    job = await store.get(job_id)
    if job is None or job.get("owner") != owner:
        return None
    return job


def zip_path(job_id: str) -> str | None:
    if not _JOB_ID_RE.match(job_id):
        return None
    path = os.path.join(BATCH_DIR, f"{job_id}.zip")
    return path if os.path.exists(path) else None


def _run_sync(job_id: str, ids: list[str], fmt: str) -> int:
    """Download + zip on a worker thread. Returns the number of tracks zipped."""
    workdir = tempfile.mkdtemp(prefix="resonar-batch-")
    files: list[str] = []
    try:
        for i, vid in enumerate(ids):
            store.update_from_thread(job_id, progress={"done": i, "total": len(ids)})
            try:
                path, tmpd = ytdlp.download_audio_sync(vid, fmt)
                dest = os.path.join(workdir, os.path.basename(path))
                shutil.move(path, dest)
                shutil.rmtree(tmpd, ignore_errors=True)
                files.append(dest)
            except Exception:  # noqa: BLE001 - skip the ones that fail
                continue
        store.update_from_thread(
            job_id, progress={"done": len(ids), "total": len(ids)}
        )
        if not files:
            raise RuntimeError("no se pudo descargar ninguna pista")
        ensure_dir()
        zpath = os.path.join(BATCH_DIR, f"{job_id}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as zf:
            for fp in files:
                zf.write(fp, arcname=os.path.basename(fp))
        return len(files)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def _run(job_id: str, ids: list[str], fmt: str) -> None:
    async with store.running(job_id):
        async with _sem:
            await store.update(job_id, status="downloading")
            try:
                count = await run_in_threadpool(_run_sync, job_id, ids, fmt)
            except Exception as exc:  # noqa: BLE001
                await store.update(job_id, status="error", error=str(exc))
            else:
                await store.update(job_id, status="ready", count=count)


async def start(
    ids: list[str], fmt: str, name: str | None, *, owner: int
) -> str:
    active = sum(
        1
        for job in (await store.all()).values()
        if job.get("owner") == owner and job.get("status") in UNFINISHED
    )
    if active >= MAX_ACTIVE_PER_USER:
        raise TooManyJobs()
    job_id = "b_" + uuid.uuid4().hex
    await store.create(
        job_id,
        owner=owner,
        status="queued",
        progress={"done": 0, "total": len(ids)},
        error=None,
        filename=f"{(name or 'playlist').strip() or 'playlist'}.zip",
    )
    asyncio.create_task(_run(job_id, ids, fmt))
    return job_id
