"""The one module that talks to yt-dlp.

Everything else (stream / video routers, the saved-video library, batch
downloads, the playlist importer) goes through the public functions here, so
yt-dlp options, format selection and output handling live in one place and can
be tested with a fake ``YoutubeDL``. Names starting with ``_`` are internal.

Blocking ``*_sync`` functions are for callers already on a worker thread; the
async wrappers at the bottom are for request handlers.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from urllib.parse import parse_qs, urlparse

from typing import Callable

import yt_dlp
from fastapi.concurrency import run_in_threadpool

from ..config import settings

_AUDIO_MIME = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "webm": "audio/webm",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "mp3": "audio/mpeg",
}
_VIDEO_MIME = {"mp4": "video/mp4", "webm": "video/webm"}

DOWNLOAD_FORMATS = {"mp3", "m4a", "opus", "flac"}

# Muxed (progressive) formats top out around 720p; anything higher on YouTube is
# adaptive (separate video/audio) and would need MSE/DASH on the client.
MAX_VIDEO_HEIGHT = 720


def _base_opts() -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "format": "bestaudio/best",
        "cachedir": "/tmp/ytdlp-cache",
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if settings.ytdlp_cookies and os.path.exists(settings.ytdlp_cookies):
        opts["cookiefile"] = settings.ytdlp_cookies
    if settings.ytdlp_proxy:
        opts["proxy"] = settings.ytdlp_proxy
    return opts


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def thumbnail_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _ttl_from_url(url: str) -> int:
    """Use the googlevideo `expire=` timestamp as the cache TTL when present."""
    expire = parse_qs(urlparse(url).query).get("expire", [None])[0]
    if expire and expire.isdigit():
        return max(60, int(expire) - int(time.time()) - 120)
    return settings.stream_cache_ttl


def fmt_duration(seconds: float | int | None) -> str | None:
    if not seconds:
        return None
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


# --------------------------------------------------------------------------- #
# Audio streaming
# --------------------------------------------------------------------------- #


def _resolve_audio_sync(video_id: str) -> dict:
    with yt_dlp.YoutubeDL(_base_opts()) as ydl:
        info = ydl.extract_info(_watch_url(video_id), download=False)

    formats = [
        f
        for f in info.get("formats", [])
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
    ]
    if not formats:
        formats = [f for f in info.get("formats", []) if f.get("acodec") not in (None, "none")]
    if not formats:
        raise RuntimeError("no audio-only formats available")

    formats.sort(key=lambda f: (f.get("abr") or f.get("tbr") or 0))
    best = formats[-1]
    ext = best.get("ext", "m4a")
    url = best["url"]

    return {
        "url": url,
        "mime": _AUDIO_MIME.get(ext, "audio/mp4"),
        "ext": ext,
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "ttl": _ttl_from_url(url),
    }


# --------------------------------------------------------------------------- #
# Video search + streaming
# --------------------------------------------------------------------------- #


def _search_videos_sync(query: str, limit: int) -> list[dict]:
    opts = {**_base_opts(), "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    out: list[dict] = []
    for entry in info.get("entries") or []:
        vid = entry.get("id")
        if not vid or entry.get("ie_key") not in (None, "Youtube"):
            continue
        out.append(
            {
                "id": vid,
                "title": entry.get("title"),
                "uploader": entry.get("uploader") or entry.get("channel"),
                "duration": fmt_duration(entry.get("duration")),
                "durationSeconds": entry.get("duration"),
                "views": entry.get("view_count"),
                "thumbnail": thumbnail_url(vid),
            }
        )
    return out


def _video_info_sync(video_id: str) -> dict:
    opts = {**_base_opts(), "extract_flat": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_watch_url(video_id), download=False)
    return {
        "id": video_id,
        "title": info.get("title") or video_id,
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": fmt_duration(info.get("duration")),
        "durationSeconds": info.get("duration"),
        "views": info.get("view_count"),
        "thumbnail": thumbnail_url(video_id),
    }


def _resolve_video_sync(video_id: str) -> dict:
    # The default web client only exposes adaptive (separate a/v) streams, which
    # a plain <video> tag can't play. The android client still returns a muxed
    # MP4 (itag 18 = 360p, sometimes itag 22 = 720p) that plays directly.
    opts = {
        **_base_opts(),
        "format": "best",
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_watch_url(video_id), download=False)

    progressive = [
        f
        for f in info.get("formats", [])
        if f.get("acodec") not in (None, "none")
        and f.get("vcodec") not in (None, "none")
        and f.get("url")
        and f.get("protocol") in ("https", "http")
    ]
    if not progressive:
        raise RuntimeError("no progressive (muxed) format available for this video")

    progressive.sort(
        key=lambda f: (
            1 if f.get("ext") == "mp4" else 0,
            min(f.get("height") or 0, MAX_VIDEO_HEIGHT),
            f.get("tbr") or 0,
        )
    )
    best = progressive[-1]
    ext = best.get("ext", "mp4")
    url = best["url"]

    return {
        "url": url,
        "mime": _VIDEO_MIME.get(ext, "video/mp4"),
        "ext": ext,
        "height": best.get("height"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "ttl": _ttl_from_url(url),
    }


# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #


def download_audio_sync(video_id: str, fmt: str) -> tuple[str, str]:
    """Download one track as ``fmt`` into a fresh temp dir.

    Returns ``(file_path, temp_dir)``; the caller owns ``temp_dir`` and must
    remove it.
    """
    outdir = tempfile.mkdtemp(prefix="resonar-dl-")
    postprocessors: list[dict] = [{"key": "FFmpegExtractAudio", "preferredcodec": fmt}]
    if fmt == "mp3":
        postprocessors[0]["preferredquality"] = "0"
    postprocessors.append({"key": "FFmpegMetadata"})
    postprocessors.append({"key": "EmbedThumbnail"})

    opts = {
        **_base_opts(),
        "skip_download": False,
        "writethumbnail": True,
        "outtmpl": os.path.join(outdir, "%(artist,uploader)s - %(title)s.%(ext)s"),
        "postprocessors": postprocessors,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(_watch_url(video_id), download=True)

    audio_exts = (f".{fmt}", ".mp3", ".m4a", ".opus", ".ogg", ".flac")
    for name in sorted(os.listdir(outdir)):
        if name.lower().endswith(f".{fmt}"):
            return os.path.join(outdir, name), outdir
    for name in sorted(os.listdir(outdir)):
        if name.lower().endswith(audio_exts):
            return os.path.join(outdir, name), outdir

    shutil.rmtree(outdir, ignore_errors=True)
    raise RuntimeError("yt-dlp produced no audio file")


def download_video_sync(
    video_id: str,
    quality: int,
    out_dir: str,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Download best video+audio up to ``quality``p merged into
    ``{out_dir}/{video_id}.mp4``. Returns the metadata worth keeping.

    ``on_progress`` receives yt-dlp's progress-hook dicts.
    """
    mp4 = os.path.join(out_dir, f"{video_id}.mp4")
    opts = {
        **_base_opts(),
        "skip_download": False,
        "format": (
            f"bv*[height<={quality}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={quality}]+ba/b[height<={quality}]/b"
        ),
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "postprocessors": [{"key": "FFmpegMetadata"}],
    }
    if on_progress is not None:
        opts["progress_hooks"] = [on_progress]
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_watch_url(video_id), download=True)

    if not os.path.exists(mp4):
        for ext in ("mkv", "webm"):
            alt = os.path.join(out_dir, f"{video_id}.{ext}")
            if os.path.exists(alt):
                os.replace(alt, mp4)
                break
    if not os.path.exists(mp4):
        raise RuntimeError("no output file produced")
    return {
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration_seconds": info.get("duration"),
        "height": info.get("height"),
    }


def playlist_entries_sync(url: str, limit: int) -> dict:
    """Flat-extract up to ``limit`` entries of a playlist URL.

    Callers must have validated ``url`` (see ``importer.check_url``): this
    hands it to yt-dlp as-is.
    """
    opts = {**_base_opts(), "extract_flat": True, "playlistend": limit}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    tracks: list[dict] = []
    for entry in info.get("entries") or []:
        vid = entry.get("id")
        if not vid:
            continue
        artist = entry.get("uploader") or entry.get("channel")
        tracks.append(
            {
                "id": vid,
                "title": entry.get("title"),
                "artists": [artist] if artist else [],
                "album": None,
                "duration": None,
                "durationSeconds": entry.get("duration"),
                "thumbnail": thumbnail_url(vid),
            }
        )
    return {"title": info.get("title"), "tracks": tracks}


# --------------------------------------------------------------------------- #
# Async wrappers
# --------------------------------------------------------------------------- #


async def resolve(video_id: str) -> dict:
    return await run_in_threadpool(_resolve_audio_sync, video_id)


async def resolve_video(video_id: str) -> dict:
    return await run_in_threadpool(_resolve_video_sync, video_id)


async def video_info(video_id: str) -> dict:
    return await run_in_threadpool(_video_info_sync, video_id)


async def search_videos(query: str, limit: int = 24) -> list[dict]:
    return await run_in_threadpool(_search_videos_sync, query, limit)


async def download_audio(video_id: str, fmt: str) -> tuple[str, str]:
    return await run_in_threadpool(download_audio_sync, video_id, fmt)


async def playlist_entries(url: str, limit: int) -> dict:
    return await run_in_threadpool(playlist_entries_sync, url, limit)
