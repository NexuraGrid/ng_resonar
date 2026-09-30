import type { Track } from "../types";

/**
 * Lock-screen / headset integration: metadata and the action handlers for
 * the track now loaded in `audio`. `onNext` / `onPrev` are called lazily so
 * the handlers always reach the latest queue actions.
 */
export function bindMediaSession(
  track: Track,
  getAudio: () => HTMLAudioElement | null,
  onNext: () => void,
  onPrev: () => void,
): void {
  if (!("mediaSession" in navigator)) return;
  const ms = navigator.mediaSession;
  ms.metadata = new MediaMetadata({
    title: track.title,
    artist: track.artists.join(", "),
    album: track.album ?? "",
    artwork: track.thumbnail
      ? [{ src: track.thumbnail, sizes: "544x544", type: "image/jpeg" }]
      : [],
  });
  const seekBy = (delta: number) => {
    const a = getAudio();
    if (a) a.currentTime = Math.max(0, a.currentTime + delta);
  };
  ms.setActionHandler("play", () => getAudio()?.play());
  ms.setActionHandler("pause", () => getAudio()?.pause());
  ms.setActionHandler("stop", () => getAudio()?.pause());
  ms.setActionHandler("previoustrack", () => onPrev());
  ms.setActionHandler("nexttrack", () => onNext());
  ms.setActionHandler("seekbackward", (d) => seekBy(-(d.seekOffset || 10)));
  ms.setActionHandler("seekforward", (d) => seekBy(d.seekOffset || 10));
  ms.setActionHandler("seekto", (d) => {
    const a = getAudio();
    if (d.seekTime != null && a) a.currentTime = d.seekTime;
  });
}

export function setMediaSessionState(state: MediaSessionPlaybackState): void {
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = state;
}

export function setMediaSessionPosition(position: number, duration: number): void {
  if (!("mediaSession" in navigator) || !(duration > 0) || !Number.isFinite(duration)) {
    return;
  }
  try {
    navigator.mediaSession.setPositionState?.({
      duration,
      playbackRate: 1,
      position: Math.min(position, duration),
    });
  } catch {
    /* position can briefly exceed duration */
  }
}
