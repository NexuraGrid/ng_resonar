import type {
  Album,
  AlbumCard,
  AppSettings,
  Artist,
  ArtistCard,
  AuthUser,
  BatchStatus,
  DownloadFormat,
  HistoryEntry,
  Lyrics,
  MeResponse,
  Playlist,
  PlaylistSummary,
  SavedVideo,
  Track,
  UserSummary,
  VideoItem,
} from "./types";

const BASE = "/api";

/** Fired whenever any API call gets a 401, so `App.tsx` can return to the login gate. */
export const SESSION_EXPIRED_EVENT = "resonar:session-expired";

/** Error thrown by every failed API call; carries the HTTP status and an optional server code. */
export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/**
 * Single choke point for every `/api` request.
 *
 * - always sends the session cookie (`credentials: "include"`)
 * - on `401`: dispatches `resonar:session-expired` then throws
 * - on `403 {code:"must_change_password"}`: throws an `ApiError` carrying `.code`
 *   (no event — the user is authenticated, just restricted)
 */
async function req(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, { credentials: "include", ...init });
  if (res.ok) return res;

  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
    throw new ApiError(401, "Session expired");
  }

  if (res.status === 403) {
    const body = await res
      .clone()
      .json()
      .catch(() => null);
    // FastAPI wraps `HTTPException(detail=...)` as `{"detail": <detail>}`, so the
    // real backend sends `{"detail":{"code":"must_change_password"}}`. Accept the
    // flat `{"code":...}` shape too in case a future handler unwraps it.
    const code = (body?.detail?.code ?? body?.code) as string | undefined;
    if (code === "must_change_password") {
      throw new ApiError(403, "Password change required", code);
    }
  }

  const detail = await res.text().catch(() => "");
  throw new ApiError(res.status, `${res.status} ${detail}`.trim());
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await req(path);
  return res.json() as Promise<T>;
}

export function search(q: string, type = "songs"): Promise<Track[]> {
  return getJSON<{ results: Track[] }>(
    `/search?q=${encodeURIComponent(q)}&type=${type}`,
  ).then((r) => r.results);
}

export function searchArtists(q: string): Promise<ArtistCard[]> {
  return getJSON<{ results: ArtistCard[] }>(
    `/search?q=${encodeURIComponent(q)}&type=artists&limit=6`,
  )
    .then((r) => r.results)
    .catch(() => []);
}

export function searchAlbums(q: string): Promise<AlbumCard[]> {
  return getJSON<{ results: AlbumCard[] }>(
    `/search?q=${encodeURIComponent(q)}&type=albums&limit=12`,
  )
    .then((r) => r.results)
    .catch(() => []);
}

export const getAlbum = (browseId: string) =>
  getJSON<Album>(`/album/${encodeURIComponent(browseId)}`);

export const getArtist = (browseId: string) =>
  getJSON<Artist>(`/artist/${encodeURIComponent(browseId)}`);

export function suggest(q: string): Promise<string[]> {
  return getJSON<{ suggestions: string[] }>(`/suggest?q=${encodeURIComponent(q)}`)
    .then((r) => r.suggestions ?? [])
    .catch(() => []);
}

export function related(id: string): Promise<Track[]> {
  return getJSON<{ results: Track[] }>(`/related/${id}`)
    .then((r) => r.results)
    .catch(() => []);
}

export function searchVideos(q: string): Promise<VideoItem[]> {
  return getJSON<{ results: VideoItem[] }>(
    `/videos/search?q=${encodeURIComponent(q)}`,
  ).then((r) => r.results);
}

export function homeMusic(): Promise<Track[]> {
  return getJSON<{ results: Track[] }>(`/home`)
    .then((r) => r.results)
    .catch(() => []);
}

export function trendingVideos(): Promise<VideoItem[]> {
  return getJSON<{ results: VideoItem[] }>(`/videos/trending`)
    .then((r) => r.results)
    .catch(() => []);
}

export function videoInfo(id: string): Promise<VideoItem> {
  return getJSON<VideoItem>(`/videos/info/${id}`);
}

export function listSavedVideos(): Promise<SavedVideo[]> {
  return getJSON<{ results: SavedVideo[] }>(`/library/videos`)
    .then((r) => r.results)
    .catch(() => []);
}

export async function apiSaveVideo(
  id: string,
  quality = 1080,
  force = false,
): Promise<{ status: string }> {
  const res = await req(
    `/library/videos/${id}?quality=${quality}&force=${force}`,
    { method: "POST" },
  );
  return res.json();
}

export async function apiDeleteSavedVideo(id: string): Promise<void> {
  await req(`/library/videos/${id}`, { method: "DELETE" });
}

export const streamUrl = (id: string) => `${BASE}/stream/${id}`;
export const videoStreamUrl = (id: string) => `${BASE}/videos/stream/${id}`;
export const savedVideoFileUrl = (id: string) => `${BASE}/library/videos/${id}/file`;
export const savedVideoDownloadUrl = (id: string) =>
  `${BASE}/library/videos/${id}/download`;

export const downloadUrl = (id: string, format: DownloadFormat = "mp3") =>
  `${BASE}/download/${id}?format=${format}`;

// ---- Lyrics ----

export function getLyrics(
  artist: string,
  title: string,
  album = "",
  duration = 0,
): Promise<Lyrics> {
  const q = new URLSearchParams({
    artist,
    title,
    album,
    duration: String(duration || 0),
  });
  return getJSON<Lyrics>(`/lyrics?${q}`).catch(() => ({
    synced: [],
    plain: null,
    source: null,
  }));
}

// ---- Playlists ----

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await req(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json() as Promise<T>;
}

export function listPlaylists(): Promise<PlaylistSummary[]> {
  return getJSON<{ results: PlaylistSummary[] }>(`/playlists`).then(
    (r) => r.results,
  );
}

export const getPlaylist = (id: string) => getJSON<Playlist>(`/playlists/${id}`);

export const createPlaylistApi = (name: string, fromUrl?: string) =>
  send<Playlist>(`/playlists`, "POST", { name, fromUrl });

/** Download URL for a playlist's share file (``<name>.resonar.json``). */
export const playlistExportUrl = (id: string) => `${BASE}/playlists/${id}/export`;

/** Create a copy of an exported playlist file in the current account. */
export const importPlaylistFileApi = (file: unknown) =>
  send<Playlist>(`/playlists/import`, "POST", file);

export const renamePlaylistApi = (id: string, name: string) =>
  send<Playlist>(`/playlists/${id}`, "PATCH", { name });

export const deletePlaylistApi = (id: string) =>
  req(`/playlists/${id}`, { method: "DELETE" })
    .then(() => undefined)
    .catch(() => undefined);

export const addTracksApi = (id: string, tracks: Track[]) =>
  send<Playlist>(`/playlists/${id}/tracks`, "POST", { tracks });

export const removeTrackApi = (id: string, trackId: string) =>
  send<Playlist>(`/playlists/${id}/tracks/${trackId}`, "DELETE");

export const reorderPlaylistApi = (id: string, ids: string[]) =>
  send<Playlist>(`/playlists/${id}/tracks`, "PUT", { ids });

// ---- Batch download ----

export const startBatchApi = (ids: string[], name: string, format = "mp3") =>
  send<{ jobId: string }>(`/download/batch`, "POST", { ids, name, format });

export const batchStatusApi = (jobId: string) =>
  getJSON<BatchStatus>(`/download/batch/${jobId}`);

export const batchFileUrl = (jobId: string) =>
  `${BASE}/download/batch/${jobId}/file`;

// ---- Settings / scrobbling ----

export const getSettings = () => getJSON<AppSettings>(`/settings`);

export const putSettings = (patch: unknown) =>
  send<AppSettings>(`/settings`, "PUT", patch);

export const lastfmAuthUrl = (callback: string) =>
  getJSON<{ url: string }>(
    `/scrobble/lastfm/auth-url?callback=${encodeURIComponent(callback)}`,
  );

export function scrobbleNowPlaying(track: Track): void {
  void req(`/scrobble/now-playing`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ track }),
  }).catch(() => {});
}

export function scrobbleSubmit(track: Track): void {
  void req(`/scrobble/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ track }),
  }).catch(() => {});
}

// ---- Playback history ----

export function recordPlay(
  item: Track | VideoItem,
  kind: "song" | "video",
  source?: string,
): void {
  const body =
    kind === "song"
      ? {
          videoId: (item as Track).id,
          title: item.title,
          artist: (item as Track).artists?.[0],
          thumbnail: item.thumbnail,
          kind,
          source,
        }
      : {
          videoId: (item as VideoItem).id,
          title: item.title,
          artist: (item as VideoItem).uploader,
          thumbnail: item.thumbnail,
          kind,
          source,
        };
  void req(`/history`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => {});
}

export function getHistory(
  limit = 20,
  kind?: "song" | "video",
): Promise<HistoryEntry[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (kind) q.set("kind", kind);
  return getJSON<{ results: HistoryEntry[] }>(`/history?${q}`)
    .then((r) => r.results)
    .catch(() => []);
}

export function clearHistory(kind?: "song" | "video"): Promise<void> {
  const suffix = kind ? `?kind=${kind}` : "";
  return req(`/history${suffix}`, { method: "DELETE" })
    .then(() => undefined)
    .catch(() => undefined);
}

// ---- Recommendations ----

export function recommendations(limit = 30): Promise<Track[]> {
  return getJSON<{ results: Track[] }>(`/recommendations?limit=${limit}`)
    .then((r) => r.results)
    .catch(() => []);
}

// ---- Favorites (server-side, per user) ----

export const getFavorites = () =>
  getJSON<{ results: Track[] }>(`/favorites`).then((r) => r.results);

export const addFavorite = (track: Track) =>
  send<{ ok: boolean; added: boolean }>(`/favorites`, "POST", { track });

export const removeFavorite = (trackId: string) =>
  send<{ ok: boolean; removed: boolean }>(`/favorites/${trackId}`, "DELETE");

// ---- Authentication ----

interface AuthResponse {
  authenticated: boolean;
  user: AuthUser;
}

export const me = () => getJSON<MeResponse>(`/auth/me`);

export const login = (username: string, password: string, remember: boolean) =>
  send<AuthResponse>(`/auth/login`, "POST", { username, password, remember }).then(
    (r) => r.user,
  );

export const logout = () => send<{ ok: boolean }>(`/auth/logout`, "POST");

export const bootstrapSuperadmin = (
  username: string,
  password: string,
  token?: string,
) =>
  send<AuthResponse>(`/auth/bootstrap`, "POST", {
    username,
    password,
    bootstrapToken: token || undefined,
  }).then((r) => r.user);

export const changePassword = (currentPassword: string, newPassword: string) =>
  send<{ ok: boolean }>(`/auth/password`, "PATCH", {
    currentPassword,
    newPassword,
  });

// ---- User administration (superadmin only; consumed in a later slice) ----

export const listUsers = () =>
  getJSON<{ results: UserSummary[] }>(`/users`).then((r) => r.results);

export const createUser = (username: string, password: string) =>
  send<UserSummary>(`/users`, "POST", { username, password });

export const deleteUser = (id: number) =>
  send<{ ok: boolean }>(`/users/${id}`, "DELETE");

export const adminSetPassword = (id: number, newPassword: string) =>
  send<{ ok: boolean }>(`/users/${id}/password`, "PATCH", { newPassword });
