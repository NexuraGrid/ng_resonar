import { useEffect, useMemo, useSyncExternalStore } from "react";

import {
  addTracksApi,
  createPlaylistApi,
  importPlaylistFileApi,
  deletePlaylistApi,
  getPlaylist,
  listPlaylists,
  removeTrackApi,
  renamePlaylistApi,
  reorderPlaylistApi,
} from "../api";
import type { Playlist, PlaylistSummary, Track } from "../types";

let summaries: PlaylistSummary[] = [];
let details: Record<string, Playlist> = {};
let initialized = false;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

async function refreshList() {
  try {
    summaries = await listPlaylists();
    emit();
  } catch {
    /* keep last */
  }
}

async function refreshOne(id: string) {
  try {
    const pl = await getPlaylist(id);
    details = { ...details, [id]: pl };
    emit();
  } catch {
    /* ignore */
  }
}

function ensureInit() {
  if (initialized) return;
  initialized = true;
  refreshList();
}

/** Fetch tracks for every playlist we don't have cached yet. Idempotent. */
async function ensureAllDetails() {
  const missing = summaries.filter((s) => !details[s.id]);
  if (missing.length === 0) return;
  await Promise.all(missing.map((s) => refreshOne(s.id)));
}

const subscribe = (cb: () => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};

export function usePlaylists(): PlaylistSummary[] {
  ensureInit();
  return useSyncExternalStore(
    subscribe,
    () => summaries,
    () => summaries,
  );
}

/**
 * Every playlist WITH its tracks. Loads any missing details on mount / when the
 * playlist list changes. `enabled` lets a caller defer the extra fetches until
 * they're actually needed (e.g. only once the user has searched something).
 */
export function useAllPlaylistDetails(enabled = true): Playlist[] {
  ensureInit();
  const detailSnap = useSyncExternalStore(
    subscribe,
    () => details,
    () => details,
  );
  const list = useSyncExternalStore(
    subscribe,
    () => summaries,
    () => summaries,
  );
  useEffect(() => {
    if (enabled) ensureAllDetails();
  }, [enabled, list]);
  return useMemo(
    () => list.map((s) => detailSnap[s.id]).filter(Boolean) as Playlist[],
    [list, detailSnap],
  );
}

export function usePlaylist(id: string | null): Playlist | undefined {
  ensureInit();
  const snap = useSyncExternalStore(
    subscribe,
    () => details,
    () => details,
  );
  useEffect(() => {
    if (id) refreshOne(id);
  }, [id]);
  return id ? snap[id] : undefined;
}

// ---- mutations (refresh affected state afterwards) ----

export async function createPlaylist(name: string, fromUrl?: string) {
  const pl = await createPlaylistApi(name, fromUrl);
  details = { ...details, [pl.id]: pl };
  await refreshList();
  return pl;
}

/** Import a playlist someone exported (the parsed ``.resonar.json``). */
export async function importPlaylistFile(file: unknown) {
  const pl = await importPlaylistFileApi(file);
  details = { ...details, [pl.id]: pl };
  await refreshList();
  return pl;
}

export async function renamePlaylist(id: string, name: string) {
  await renamePlaylistApi(id, name);
  await Promise.all([refreshOne(id), refreshList()]);
}

export async function deletePlaylist(id: string) {
  await deletePlaylistApi(id);
  const { [id]: _drop, ...rest } = details;
  details = rest;
  await refreshList();
}

export async function addToPlaylist(id: string, tracks: Track | Track[]) {
  await addTracksApi(id, Array.isArray(tracks) ? tracks : [tracks]);
  await Promise.all([refreshOne(id), refreshList()]);
}

export async function removeFromPlaylist(id: string, trackId: string) {
  await removeTrackApi(id, trackId);
  await Promise.all([refreshOne(id), refreshList()]);
}

export async function reorderPlaylist(id: string, ids: string[]) {
  await reorderPlaylistApi(id, ids);
  await refreshOne(id);
}

/** Drop every cached playlist so the next mount reseeds for the new user. */
export function resetPlaylists() {
  summaries = [];
  details = {};
  initialized = false;
  emit();
}

export { resetPlaylists as reset };
