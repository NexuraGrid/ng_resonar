"""Playlist export / import (sharing a playlist as a file)."""

from __future__ import annotations

import pytest

from app.services import playlist_share

A, B = "dQw4w9WgXcQ", "9bZkp7q19f0"


def _track(vid: str, **extra) -> dict:
    return {
        "id": vid,
        "title": f"Song {vid}",
        "artists": ["Artist"],
        "album": "Album",
        "duration": "3:33",
        "durationSeconds": 213,
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        **extra,
    }


# --- unit ---------------------------------------------------------------------
def test_export_then_parse_roundtrips():
    payload = playlist_share.export_payload(
        {"name": "Road trip", "tracks": [_track(A), _track(B)]}
    )
    assert payload["format"] == "resonar-playlist" and payload["version"] == 1
    name, tracks = playlist_share.parse_import(payload)
    assert name == "Road trip"
    assert tracks == [_track(A), _track(B)]


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"format": "something-else", "version": 1, "tracks": [_track(A)]},
        {"format": "resonar-playlist", "version": 99, "tracks": [_track(A)]},
        {"format": "resonar-playlist", "version": 1, "tracks": "nope"},
        {"format": "resonar-playlist", "version": 1, "tracks": [{"id": "../../x"}]},
        {"format": "resonar-playlist", "version": 1, "tracks": [_track(A)] * 1001},
    ],
)
def test_parse_rejects_bad_files(data):
    with pytest.raises(playlist_share.InvalidPlaylistFile):
        playlist_share.parse_import(data)


def test_parse_sanitizes_untrusted_fields():
    evil = _track(
        A,
        title="x" * 5000,
        artists=["ok", 42, {"a": 1}, ""],
        thumbnail="javascript:alert(1)",
        durationSeconds=True,
        injected="<script>",
    )
    _, [track] = playlist_share.parse_import(
        {"format": "resonar-playlist", "version": 1, "name": "  ", "tracks": [evil, {"id": "bad"}]}
    )
    assert set(track) == {
        "id", "title", "artists", "album", "duration", "durationSeconds", "thumbnail"
    }
    assert len(track["title"]) == 300
    assert track["artists"] == ["ok"]
    assert track["thumbnail"] is None
    assert track["durationSeconds"] is None


def test_filename_strips_path_characters():
    assert playlist_share.filename_for('Mis/"favs":2026') == "Misfavs2026.resonar.json"
    assert playlist_share.filename_for("   ") == "playlist.resonar.json"


# --- API ------------------------------------------------------------------------
def test_export_download_and_import_as_another_user(api, as_user, db_reset):
    as_user("alice")
    pl = api.post("/api/playlists", json={"name": "Canciones de Alice"}).json()
    api.post(f"/api/playlists/{pl['id']}/tracks", json={"tracks": [_track(A), _track(B)]})

    res = api.get(f"/api/playlists/{pl['id']}/export")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert "Canciones%20de%20Alice.resonar.json" in res.headers["content-disposition"]
    exported = res.json()

    as_user("bob")
    created = api.post("/api/playlists/import", json=exported)
    assert created.status_code == 200
    copy = created.json()
    assert copy["id"] != pl["id"]
    assert copy["name"] == "Canciones de Alice"
    assert [t["id"] for t in copy["tracks"]] == [A, B]
    assert [p["id"] for p in api.get("/api/playlists").json()["results"]] == [copy["id"]]

    # A copy, not a link: Alice's playlist is untouched and still only hers.
    as_user("alice")
    assert [p["id"] for p in api.get("/api/playlists").json()["results"]] == [pl["id"]]


def test_cannot_export_someone_elses_playlist(api, as_user, db_reset):
    as_user("alice")
    pl = api.post("/api/playlists", json={"name": "Privada"}).json()
    as_user("bob")
    assert api.get(f"/api/playlists/{pl['id']}/export").status_code == 404


def test_import_of_invalid_file_is_422(api, as_user, db_reset):
    as_user("alice")
    res = api.post("/api/playlists/import", json={"hello": "world"})
    assert res.status_code == 422
    assert "Resonar" in res.json()["detail"]
