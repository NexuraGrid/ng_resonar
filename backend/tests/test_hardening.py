"""Regression tests for the 2026-09 security hardening pass."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.origin_check import OriginCheckMiddleware
from app.services import importer


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
    async def fake_entries(*a, **k):
        called.append(a)
        return {}

    monkeypatch.setattr(importer.ytdlp, "playlist_entries", fake_entries)
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
