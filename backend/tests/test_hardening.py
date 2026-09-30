"""Regression tests for the 2026-09 security hardening pass."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.origin_check import OriginCheckMiddleware
from app.services import audiobatch, importer, videolib


# --- importer: only YouTube URLs reach yt-dlp --------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/playlist?list=PL123",
        "https://music.youtube.com/browse/MPREb_abc",
        "https://youtu.be/dQw4w9WgXcQ",
        "http://m.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ",
    ],
)
def test_importer_accepts_youtube_urls(url):
    assert importer.check_url(f"  {url} ") == url


@pytest.mark.parametrize(
    "url",
    [
        "http://db:5432/",
        "http://redis:6379/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "https://youtube.com.evil.example/playlist?list=PL1",
        "https://evil.example/?u=https://www.youtube.com/",
        "https://user:pw@www.youtube.com/playlist?list=PL1",
        "https://www.youtube.com:8443/playlist?list=PL1",
        "ytsearch:anything",
        "",
    ],
)
def test_importer_rejects_non_youtube_urls(url):
    with pytest.raises(importer.UnsupportedUrl):
        importer.check_url(url)


def test_import_url_never_calls_ytdlp_for_foreign_hosts(monkeypatch):
    called = []
    monkeypatch.setattr(
        importer, "_ytdlp_playlist_sync", lambda *a, **k: called.append(a)
    )
    with pytest.raises(importer.UnsupportedUrl):
        asyncio.run(importer.import_url("http://redis:6379/"))
    assert called == []


# --- origin check -------------------------------------------------------------
def _origin_app() -> TestClient:
    app = FastAPI()
    app.add_middleware(
        OriginCheckMiddleware, allowed_origins=["https://dev.example.org"]
    )

    @app.post("/api/thing")
    async def thing():
        return {"ok": True}

    @app.get("/api/thing")
    async def read_thing():
        return {"ok": True}

    return TestClient(app, base_url="https://ngyou.example.org")


def test_origin_check_allows_same_origin_and_missing_origin():
    c = _origin_app()
    assert c.post("/api/thing", headers={"Origin": "https://ngyou.example.org"}).status_code == 200
    assert c.post("/api/thing").status_code == 200


def test_origin_check_allows_configured_cors_origin():
    c = _origin_app()
    assert c.post("/api/thing", headers={"Origin": "https://dev.example.org"}).status_code == 200


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example.org", "https://sibling.example.org", "null"],
)
def test_origin_check_blocks_cross_origin_writes(origin):
    c = _origin_app()
    assert c.post("/api/thing", headers={"Origin": origin}).status_code == 403


def test_origin_check_ignores_safe_methods():
    c = _origin_app()
    assert c.get("/api/thing", headers={"Origin": "https://evil.example.org"}).status_code == 200


# --- batch downloads are per-user --------------------------------------------
@pytest.fixture
def batch_jobs(monkeypatch):
    monkeypatch.setattr(audiobatch, "_jobs", {})
    monkeypatch.setattr(audiobatch, "_run_sync", lambda *a, **k: None)
    return audiobatch._jobs


def test_batch_job_is_only_visible_to_its_owner(batch_jobs):
    async def go():
        return await audiobatch.start(["dQw4w9WgXcQ"], "mp3", "x", owner=1)

    job_id = asyncio.run(go())
    assert audiobatch.status(job_id, owner=1) is not None
    assert audiobatch.status(job_id, owner=2) is None


def test_batch_jobs_are_capped_per_user(batch_jobs):
    for i in range(audiobatch.MAX_ACTIVE_PER_USER):
        batch_jobs[f"b_{i}"] = {"owner": 1, "status": "downloading"}
    with pytest.raises(audiobatch.TooManyJobs):
        asyncio.run(audiobatch.start(["dQw4w9WgXcQ"], "mp3", None, owner=1))
    # Another user is unaffected.
    async def other():
        return await audiobatch.start(["dQw4w9WgXcQ"], "mp3", None, owner=2)

    assert asyncio.run(other()).startswith("b_")


def test_zip_path_rejects_traversal():
    assert audiobatch.zip_path("../../etc/passwd") is None


# --- saved videos: only the saver or an admin may remove ---------------------
def test_saved_video_manage_rules(monkeypatch, tmp_path):
    monkeypatch.setattr(videolib, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(videolib, "_jobs", {})
    vid = "dQw4w9WgXcQ"
    (tmp_path / f"{vid}.mp4").write_bytes(b"")
    (tmp_path / f"{vid}.json").write_text('{"id": "%s", "savedBy": 7}' % vid)

    assert videolib.can_manage(vid, 7, False)
    assert not videolib.can_manage(vid, 8, False)
    assert videolib.can_manage(vid, 8, True)

    legacy = "aaaaaaaaaaa"
    (tmp_path / f"{legacy}.mp4").write_bytes(b"")
    (tmp_path / f"{legacy}.json").write_text('{"id": "%s"}' % legacy)
    assert not videolib.can_manage(legacy, 7, False)
    assert videolib.can_manage(legacy, 7, True)

    # Nothing saved and no job: saving it fresh is fine for anyone.
    assert videolib.can_manage("bbbbbbbbbbb", 7, False)

    videolib._jobs["ccccccccccc"] = {"status": "downloading", "savedBy": 7}
    assert not videolib.can_manage("ccccccccccc", 8, False)
