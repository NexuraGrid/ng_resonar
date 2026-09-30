"""Redis-backed job state, batch zips and the saved-video library."""

from __future__ import annotations

import asyncio
import json
import os
import time
import zipfile

import pytest
from fastapi.concurrency import run_in_threadpool

from app.services import audiobatch, jobs, videolib, ytdlp

VID = "dQw4w9WgXcQ"


async def _settle(pred, timeout=5.0):
    """Wait for a background task to reach a state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("background job did not settle")


# --- JobStore -----------------------------------------------------------------
async def test_store_roundtrip_and_index(fake_redis):
    store = jobs.JobStore("t")
    await store.create("j1", status="queued", progress={"done": 0, "total": 3})
    await store.update("j1", status="downloading")
    job = await store.get("j1")
    assert job["status"] == "downloading"
    assert job["progress"] == {"done": 0, "total": 3}
    assert list(await store.all()) == ["j1"]
    assert await fake_redis.ttl("job:t:j1") > 0

    await store.delete("j1")
    assert await store.get("j1") is None
    assert await store.all() == {}


async def test_update_of_missing_job_does_not_recreate_it(fake_redis):
    store = jobs.JobStore("t")
    await store.update("gone", status="ready")
    assert await store.get("gone") is None


async def test_unfinished_job_without_heartbeat_reads_as_interrupted(fake_redis):
    store = jobs.JobStore("t")
    await store.create("j", status="downloading")
    await store.update("j", beat=time.time() - jobs.STALE_AFTER - 1)
    job = await store.get("j")
    assert job["status"] == "error"
    assert job["error"] == jobs.INTERRUPTED

    await store.update("j", status="ready")
    assert (await store.get("j"))["status"] == "ready"


async def test_running_refreshes_heartbeat(fake_redis, monkeypatch):
    monkeypatch.setattr(jobs, "HEARTBEAT_EVERY", 0.01)
    store = jobs.JobStore("t")
    await store.create("j", status="downloading")
    await store.update("j", beat=0)
    async with store.running("j"):
        await asyncio.sleep(0.05)
    assert (await store.get("j"))["beat"] > 0


async def test_update_from_worker_thread(fake_redis):
    store = jobs.JobStore("t")
    await store.create("j", status="downloading")
    await run_in_threadpool(store.update_from_thread, "j", progress="50%")
    assert (await store.get("j"))["progress"] == "50%"


async def test_jobs_are_shared_across_store_instances(fake_redis):
    # Two stores of the same kind = two uvicorn workers.
    await jobs.JobStore("t").create("j", status="queued")
    assert (await jobs.JobStore("t").get("j"))["status"] == "queued"


# --- batch zips -----------------------------------------------------------------
@pytest.fixture
def batch_env(fake_redis, monkeypatch, tmp_path):
    monkeypatch.setattr(audiobatch, "BATCH_DIR", str(tmp_path / "batches"))

    def fake_download(video_id, fmt):
        d = tmp_path / f"dl-{video_id}"
        d.mkdir()
        f = d / f"{video_id}.{fmt}"
        f.write_bytes(b"audio")
        return str(f), str(d)

    monkeypatch.setattr(ytdlp, "download_audio_sync", fake_download)
    return tmp_path


async def test_batch_runs_to_a_zip_only_its_owner_sees(batch_env):
    job_id = await audiobatch.start([VID, "aaaaaaaaaaa"], "mp3", "Mix", owner=1)

    async def ready():
        job = await audiobatch.status(job_id, owner=1)
        return job and job["status"] == "ready"

    await _settle(ready)
    job = await audiobatch.status(job_id, owner=1)
    assert job["count"] == 2 and job["filename"] == "Mix.zip"
    assert job["progress"] == {"done": 2, "total": 2}
    with zipfile.ZipFile(audiobatch.zip_path(job_id)) as zf:
        assert sorted(zf.namelist()) == sorted([f"{VID}.mp3", "aaaaaaaaaaa.mp3"])
    assert await audiobatch.status(job_id, owner=2) is None


async def test_batch_with_no_downloadable_tracks_errors(batch_env, monkeypatch):
    def boom(*a):
        raise RuntimeError("nope")

    monkeypatch.setattr(ytdlp, "download_audio_sync", boom)
    job_id = await audiobatch.start([VID], "mp3", None, owner=1)

    async def failed():
        return (await audiobatch.status(job_id, owner=1))["status"] == "error"

    await _settle(failed)


async def test_batch_jobs_are_capped_per_user(batch_env, monkeypatch):
    async def no_run(*a):
        return None

    monkeypatch.setattr(audiobatch, "_run", no_run)
    for i in range(audiobatch.MAX_ACTIVE_PER_USER):
        await audiobatch.store.create(f"b_{i:032x}", owner=1, status="queued")
    with pytest.raises(audiobatch.TooManyJobs):
        await audiobatch.start([VID], "mp3", None, owner=1)
    assert (await audiobatch.start([VID], "mp3", None, owner=2)).startswith("b_")


async def test_batch_status_rejects_malformed_ids(fake_redis):
    assert await audiobatch.status("../../etc/passwd", owner=1) is None
    assert audiobatch.zip_path("../../etc/passwd") is None


# --- saved videos ---------------------------------------------------------------
@pytest.fixture
def media(fake_redis, monkeypatch, tmp_path, pg_engine, db_reset):
    monkeypatch.setattr(videolib, "MEDIA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def users(pg_engine, db_reset):
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        ids = []
        for name in ("alice", "bob"):
            u = User(username=name, password_hash="x", role="user")
            db.add(u)
            db.flush()
            ids.append(u.id)
        db.commit()
    return ids


@pytest.fixture
def db():
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session
        session.commit()


def _fake_video_download(tmp_path, *, fail=False, gate=None):
    def fake(video_id, quality, out_dir, on_progress=None):
        if gate is not None:
            gate.wait(5)
        if on_progress:
            on_progress({"status": "downloading", "_percent_str": " 50%",
                         "info_dict": {"title": "Song"}})
        if fail:
            raise RuntimeError("yt-dlp exploded")
        (tmp_path / f"{video_id}.mp4").write_bytes(b"x" * 10)
        return {"title": "Song", "uploader": "U", "duration_seconds": 65, "height": 720}

    return fake


async def test_save_records_a_row_and_clears_the_job(media, users, db, monkeypatch):
    alice, bob = users
    monkeypatch.setattr(ytdlp, "download_video_sync", _fake_video_download(media))

    assert await videolib.start_save(db, VID, 720, saved_by=alice) == "downloading"

    async def saved():
        db.expire_all()
        return await videolib.file_path(db, VID) is not None

    await _settle(saved)
    assert await videolib.store.get(VID) is None

    [item] = await videolib.list_saved(db, alice, False)
    assert item["status"] == "ready"
    assert item["title"] == "Song" and item["duration"] == "1:05"
    assert item["size"] == 10 and item["canDelete"] is True
    [as_bob] = await videolib.list_saved(db, bob, False)
    assert as_bob["canDelete"] is False

    assert await videolib.can_manage(db, VID, alice, False)
    assert not await videolib.can_manage(db, VID, bob, False)
    assert await videolib.can_manage(db, VID, bob, True)
    assert await videolib.start_save(db, VID, 720, saved_by=bob) == "ready"


async def test_failed_save_leaves_an_error_job_anyone_can_clear(
    media, users, db, monkeypatch
):
    alice, bob = users
    monkeypatch.setattr(
        ytdlp, "download_video_sync", _fake_video_download(media, fail=True)
    )
    await videolib.start_save(db, VID, 720, saved_by=alice)

    async def failed():
        job = await videolib.store.get(VID)
        return job and job["status"] == "error"

    await _settle(failed)
    [item] = await videolib.list_saved(db, bob, False)
    assert item["status"] == "error" and "exploded" in item["error"]
    assert item["canDelete"] is True
    assert await videolib.can_manage(db, VID, bob, False)


async def test_running_download_belongs_to_its_starter(media, users, db, monkeypatch):
    import threading

    alice, bob = users
    gate = threading.Event()
    monkeypatch.setattr(
        ytdlp, "download_video_sync", _fake_video_download(media, gate=gate)
    )
    await videolib.start_save(db, VID, 720, saved_by=alice)
    [item] = await videolib.list_saved(db, bob, False)
    assert item["status"] == "downloading" and item["canDelete"] is False
    assert not await videolib.can_manage(db, VID, bob, False)

    # Alice removes it mid-download: it must not come back when it finishes.
    await videolib.delete_saved(db, VID)
    gate.set()
    await asyncio.sleep(0.3)
    db.expire_all()
    assert await videolib.file_path(db, VID) is None
    assert not (media / f"{VID}.mp4").exists()


async def test_legacy_sidecars_are_imported_once(media, users, db):
    alice, _ = users
    (media / f"{VID}.mp4").write_bytes(b"x" * 5)
    (media / f"{VID}.json").write_text(
        json.dumps({"id": VID, "title": "Old", "savedAt": 1_700_000_000,
                    "savedBy": alice, "quality": 480, "durationSeconds": 30})
    )
    (media / "orphan.json").write_text("{}")

    assert videolib.import_legacy_sidecars() == 1
    assert videolib.import_legacy_sidecars() == 0
    assert (media / f"{VID}.json.migrated").exists()
    [item] = await videolib.list_saved(db, alice, False)
    assert item["title"] == "Old" and item["savedAt"] == 1_700_000_000
    assert item["canDelete"] is True
