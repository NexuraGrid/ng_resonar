export interface Track {
  id: string;
  title: string;
  artists: string[];
  album?: string | null;
  duration?: string | null;
  durationSeconds?: number | null;
  thumbnail?: string | null;
}

export interface VideoItem {
  id: string;
  title: string;
  uploader?: string | null;
  duration?: string | null;
  durationSeconds?: number | null;
  views?: number | null;
  thumbnail: string;
}

export interface ArtistCard {
  browseId: string;
  name: string;
  thumbnail?: string | null;
}

export interface AlbumCard {
  browseId: string;
  playlistId?: string | null;
  title: string;
  artists: string[];
  year?: string | null;
  type?: string | null;
  thumbnail?: string | null;
}

export interface Album extends AlbumCard {
  duration?: string | null;
  trackCount?: number | null;
  tracks: Track[];
}

export interface Artist {
  browseId: string;
  name: string;
  thumbnail?: string | null;
  description?: string | null;
  topSongs: Track[];
  albums: AlbumCard[];
  singles: AlbumCard[];
}

export interface HistoryEntry {
  videoId: string;
  title: string;
  artist?: string | null;
  thumbnail?: string | null;
  kind: "song" | "video";
  playedAt: number;
  playCount: number;
  source?: string | null;
}

export interface SavedVideo {
  id: string;
  title?: string | null;
  uploader?: string | null;
  duration?: string | null;
  durationSeconds?: number | null;
  thumbnail: string;
  status: "downloading" | "ready" | "error";
  progress?: string | null;
  error?: string | null;
  quality?: number;
  height?: number | null;
  size?: number;
  savedAt?: number;
  /** Whether the current user may remove / re-download it (saver or admin). */
  canDelete?: boolean;
}

export interface PlaylistSummary {
  id: string;
  name: string;
  count: number;
  thumbnail?: string | null;
  updatedAt: number;
}

export interface Playlist extends PlaylistSummary {
  tracks: Track[];
  createdAt: number;
}

export interface LyricLine {
  time: number;
  text: string;
}

export interface Lyrics {
  synced: LyricLine[];
  plain: string | null;
  source: string | null;
}

export interface BatchStatus {
  status: "downloading" | "ready" | "error";
  progress?: { done: number; total: number } | null;
  error?: string | null;
  ready: boolean;
}

export interface AppSettings {
  listenbrainz: { enabled: boolean; hasToken: boolean };
  lastfm: {
    enabled: boolean;
    hasKeys: boolean;
    connected: boolean;
    username: string;
  };
}

export type DownloadFormat = "mp3" | "m4a" | "opus" | "flac";

export type UserRole = "superadmin" | "user";

export interface AuthUser {
  id: number;
  username: string;
  role: UserRole;
  mustChangePassword: boolean;
}

export interface MeResponse {
  authenticated: boolean;
  user?: AuthUser;
  bootstrapAvailable?: boolean;
}

export interface UserSummary {
  id: number;
  username: string;
  role: UserRole;
  mustChangePassword: boolean;
  createdAt?: number;
}
