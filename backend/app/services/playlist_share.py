"""Playlist export / import as a file a user can hand to someone else.

The file is plain JSON::

    {"format": "resonar-playlist", "version": 1, "name": "...",
     "exportedAt": 1790000000, "tracks": [{"id": "...", "title": "...", ...}]}

Importing creates a *new* playlist owned by the importer — a copy, not a
link back to the original. The file comes from another person, so every
field is re-validated and re-built here rather than stored as received:
unknown keys are dropped, strings are length-capped, ids must be YouTube
video ids and thumbnails must be https URLs.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlparse

FORMAT = "resonar-playlist"
VERSION = 1
MAX_TRACKS = 1000
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_MAX_TEXT = 300
_MAX_ARTISTS = 10


class InvalidPlaylistFile(ValueError):
    """The uploaded file isn't a playlist export this server understands."""


def export_payload(playlist: dict) -> dict:
    """The file contents for a playlist as returned by ``playlists.get``."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "name": playlist["name"],
        "exportedAt": int(time.time()),
        "tracks": [_clean_track(t) for t in playlist.get("tracks") or []],
    }


def filename_for(name: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", name).strip() or "playlist"
    return f"{safe[:80]}.resonar.json"


def parse_import(data: object) -> tuple[str, list[dict]]:
    """Validate an uploaded export; return ``(name, tracks)`` safe to store."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise InvalidPlaylistFile("El archivo no es una playlist exportada de Resonar.")
    if data.get("version") != VERSION:
        raise InvalidPlaylistFile("Versión de archivo no soportada.")
    raw_tracks = data.get("tracks")
    if not isinstance(raw_tracks, list):
        raise InvalidPlaylistFile("El archivo no tiene canciones.")
    if len(raw_tracks) > MAX_TRACKS:
        raise InvalidPlaylistFile(f"Máximo {MAX_TRACKS} canciones por playlist.")

    tracks = []
    for raw in raw_tracks:
        if isinstance(raw, dict) and _VIDEO_ID_RE.match(str(raw.get("id") or "")):
            tracks.append(_clean_track(raw))
    if not tracks:
        raise InvalidPlaylistFile("El archivo no tiene canciones válidas.")
    name = _text(data.get("name")) or "Playlist importada"
    return name, tracks


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:_MAX_TEXT] or None


def _https_url(value: object) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    return text if parsed.scheme == "https" and parsed.hostname else None


def _clean_track(raw: dict) -> dict:
    artists = raw.get("artists")
    seconds = raw.get("durationSeconds")
    return {
        "id": raw["id"],
        "title": _text(raw.get("title")) or raw["id"],
        "artists": [a for a in (_text(x) for x in artists) if a][:_MAX_ARTISTS]
        if isinstance(artists, list)
        else [],
        "album": _text(raw.get("album")),
        "duration": _text(raw.get("duration")),
        "durationSeconds": int(seconds)
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
        and 0 <= seconds < 86_400
        else None,
        "thumbnail": _https_url(raw.get("thumbnail")),
    }
