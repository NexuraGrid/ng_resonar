"""The yt-dlp adapter, driven by a fake ``YoutubeDL`` (no network)."""

from __future__ import annotations

import os
import time

import pytest

from app.services import ytdlp


class FakeYDL:
    """Stands in for ``yt_dlp.YoutubeDL``; records opts, returns ``info``."""

    info: dict = {}
    on_extract = None  # optional callable(opts, url)
    calls: list = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        FakeYDL.calls.append((url, download, self.opts))
        if FakeYDL.on_extract:
            FakeYDL.on_extract(self.opts, url)
        return FakeYDL.info


@pytest.fixture
def ydl(monkeypatch):
    FakeYDL.info, FakeYDL.on_extract, FakeYDL.calls = {}, None, []
    monkeypatch.setattr(ytdlp.yt_dlp, "YoutubeDL", FakeYDL)
    return FakeYDL


def test_resolve_audio_picks_highest_bitrate_audio_only(ydl):
    exp = int(time.time()) + 3600
    ydl.info = {
        "title": "T",
        "formats": [
            {"acodec": "opus", "vcodec": "none", "abr": 50, "ext": "webm", "url": "u1"},
            {"acodec": "mp4a", "vcodec": "none", "abr": 128, "ext": "m4a",
             "url": f"https://x/?expire={exp}"},
            {"acodec": "mp4a", "vcodec": "avc1", "abr": 999, "ext": "mp4", "url": "muxed"},
        ],
    }
    out = ytdlp._resolve_audio_sync("dQw4w9WgXcQ")
    assert out["url"].startswith("https://x/")
    assert out["mime"] == "audio/mp4"
    assert 3000 < out["ttl"] <= 3600
    assert ydl.calls[0][0] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_resolve_audio_without_audio_formats_raises(ydl):
    ydl.info = {"formats": [{"acodec": "none", "vcodec": "avc1", "url": "v"}]}
    with pytest.raises(RuntimeError):
        ytdlp._resolve_audio_sync("dQw4w9WgXcQ")


def test_resolve_video_prefers_mp4_and_caps_height(ydl):
    ydl.info = {
        "formats": [
            {"acodec": "a", "vcodec": "v", "ext": "webm", "height": 720,
             "protocol": "https", "url": "webm720"},
            {"acodec": "a", "vcodec": "v", "ext": "mp4", "height": 360,
             "protocol": "https", "url": "mp4-360"},
            {"acodec": "a", "vcodec": "v", "ext": "mp4", "height": 1080,
             "protocol": "m3u8", "url": "hls"},
        ]
    }
    assert ytdlp._resolve_video_sync("dQw4w9WgXcQ")["url"] == "mp4-360"


def test_fmt_duration():
    assert ytdlp.fmt_duration(None) is None
    assert ytdlp.fmt_duration(65) == "1:05"
    assert ytdlp.fmt_duration(3725) == "1:02:05"


def test_download_audio_returns_file_and_tempdir(ydl):
    def fake(opts, url):
        outdir = os.path.dirname(opts["outtmpl"])
        open(os.path.join(outdir, "Artist - Song.jpg"), "w").close()
        open(os.path.join(outdir, "Artist - Song.mp3"), "w").close()

    ydl.on_extract = fake
    path, tmpdir = ytdlp.download_audio_sync("dQw4w9WgXcQ", "mp3")
    try:
        assert path.endswith("Artist - Song.mp3")
        assert os.path.dirname(path) == tmpdir
    finally:
        import shutil

        shutil.rmtree(tmpdir)


def test_download_video_renames_mkv_and_reports_progress(ydl, tmp_path):
    seen = []

    def fake(opts, url):
        for hook in opts.get("progress_hooks", []):
            hook({"status": "finished"})
        (tmp_path / "dQw4w9WgXcQ.mkv").write_bytes(b"x")

    ydl.on_extract = fake
    ydl.info = {"title": "Song", "channel": "Chan", "duration": 200, "height": 720}
    meta = ytdlp.download_video_sync("dQw4w9WgXcQ", 720, str(tmp_path), seen.append)
    assert (tmp_path / "dQw4w9WgXcQ.mp4").exists()
    assert meta == {
        "title": "Song",
        "uploader": "Chan",
        "duration_seconds": 200,
        "height": 720,
    }
    assert seen == [{"status": "finished"}]
    assert "height<=720" in ydl.calls[0][2]["format"]


def test_download_video_without_output_raises(ydl, tmp_path):
    with pytest.raises(RuntimeError):
        ytdlp.download_video_sync("dQw4w9WgXcQ", 720, str(tmp_path))


def test_playlist_entries_maps_flat_entries(ydl):
    ydl.info = {
        "title": "Mix",
        "entries": [
            {"id": "aaaaaaaaaaa", "title": "A", "uploader": "U", "duration": 10},
            {"title": "no id"},
            {"id": "bbbbbbbbbbb", "title": "B", "channel": "C"},
        ],
    }
    out = ytdlp.playlist_entries_sync("https://www.youtube.com/playlist?list=PL1", 5)
    assert out["title"] == "Mix"
    assert [t["id"] for t in out["tracks"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert out["tracks"][1]["artists"] == ["C"]
    assert ydl.calls[0][2]["playlistend"] == 5
