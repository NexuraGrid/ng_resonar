"""Turn a YouTube / YT Music playlist or album URL into a list of tracks."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from . import ytdlp, ytmusic


# Only YouTube hosts are ever handed to yt-dlp. Its generic extractor will
# otherwise fetch any URL a user pastes, turning the importer into a request
# forwarder into the Docker network and the LAN (db, redis, the router...).
_ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


class UnsupportedUrl(ValueError):
    """Raised for anything that is not an http(s) YouTube / YT Music URL."""


def check_url(url: str) -> str:
    """Return ``url`` stripped, or raise ``UnsupportedUrl``."""
    url = (url or "").strip()
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise UnsupportedUrl("URL inválida") from exc
    if (
        parsed.scheme not in ("http", "https")
        or host not in _ALLOWED_HOSTS
        or port not in (None, 80, 443)
        or parsed.username
        or parsed.password
    ):
        raise UnsupportedUrl("Solo se pueden importar URLs de YouTube o YouTube Music.")
    return url


def _extract_list_id(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    if query.get("list"):
        return query["list"][0]
    m = re.search(r"/browse/(MPREb_[\w-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/playlist/([\w-]+)", url)
    if m:
        return m.group(1)
    return None


def _extract_video_id(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    if query.get("v"):
        return query["v"][0]
    m = re.search(r"(?:youtu\.be/|/shorts/|/embed/|/watch/)([\w-]{11})", url)
    return m.group(1) if m else None


_QUALIFIER_RE = re.compile(
    r"\s*[\(\[][^\)\]]*[\)\]]"  # (...) / [...]
    r"|\s*[-–—]\s*(?:official|lyric|topic|audio|video|remaster(?:ed)?|"
    r"\d{4}\s*remaster|hd|hq|live|visualizer).*$",
    re.IGNORECASE,
)


def _norm_title(title: str) -> str:
    """Collapse a title to a comparison key: lowercase, drop
    parenthetical/qualifier tails, strip apostrophes and punctuation, squeeze
    whitespace. 'I Know It's Over', 'I Know It’s Over', 'I Know Its Over
    (2011 Remaster)' all map to 'i know its over'."""
    t = title.lower().replace("’", "'").replace("`", "'")
    t = _QUALIFIER_RE.sub("", t)
    t = t.replace("'", "")
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t


def _dedupe(tracks: list[dict], aggressive: bool = False) -> list[dict]:
    """Drop repeats. Always exact by videoId. When ``aggressive`` (Mix/radio
    imports), also collapse the same song served as
    '… (Remaster)' / '… (Live)' / a Topic re-upload / a different apostrophe."""
    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_named: set[tuple[str, str]] = set()
    for t in tracks:
        vid = t.get("id")
        if not vid or vid in seen_ids:
            continue
        if aggressive:
            key = (
                _norm_title(t.get("title") or ""),
                (t.get("artists") or [""])[0].strip().lower(),
            )
            if key[0] and key in seen_named:
                continue
            seen_named.add(key)
        seen_ids.add(vid)
        out.append(t)
    return out


async def import_url(url: str, limit: int = 300) -> dict:
    url = check_url(url)
    list_id = _extract_list_id(url)
    seed = _extract_video_id(url)
    is_mix = bool(list_id and list_id.startswith("RD"))
    # A Mix / radio is an infinite personalised stream — importing 300 just
    # gives you the same handful of songs looped. Snapshot a sane slice.
    eff_limit = min(limit, 50) if is_mix else limit

    def _finish(res: dict, fallback_title: str | None = None) -> dict:
        tracks = _dedupe(res.get("tracks") or [], aggressive=is_mix)[:eff_limit]
        return {"title": res.get("title") or fallback_title, "tracks": tracks}

    if list_id:
        try:
            res = await ytmusic.playlist(
                list_id, eff_limit, seed_video_id=seed
            )
            if res.get("tracks"):
                return _finish(res, "Mix de YouTube" if is_mix else None)
        except Exception:  # noqa: BLE001 - fall back to yt-dlp
            pass

    try:
        res = await ytdlp.playlist_entries(url, eff_limit)
        if res.get("tracks"):
            return _finish(res, "Mix de YouTube" if is_mix else None)
    except Exception:  # noqa: BLE001
        pass

    # Last resort: a URL that only carries a video id (a Mix with no usable
    # list, e.g. ".../watch?v=X&list=RDX&start_radio=1") — import that track's
    # radio as a one-off snapshot.
    if seed:
        tracks = await ytmusic.related(seed, 50)
        if tracks:
            return {
                "title": "Mix de YouTube",
                "tracks": _dedupe(tracks, aggressive=True)[:50],
            }

    return {"title": None, "tracks": []}
