import { useEffect, useRef } from "react";
import Plyr from "plyr";
import "plyr/dist/plyr.css";

import {
  prefetchStream,
  recordPlay,
  scrobbleNowPlaying,
  scrobbleSubmit,
  streamUrl,
} from "../api";
import { claimPlayback, onPlaybackClaim } from "../state/mediabus";
import { registerSeeker, setNowPlaying } from "../state/nowPlaying";
import { getOfflineBlob } from "../state/offline";
import { scrobblingOn } from "../state/settings";
import type { Track } from "../types";
import {
  bindMediaSession,
  setMediaSessionPosition,
  setMediaSessionState,
} from "./mediaSession";
import { loadPosition, savePosition } from "./playbackPosition";
import { useVolumeLeveling } from "./useVolumeLeveling";

/** How often (ms) time updates reach the now-playing store. */
const TIME_PUSH_EVERY = 200;
/** How often (ms) the playback position is persisted for reload-resume. */
const POSITION_SAVE_EVERY = 4000;

/** A listen counts once half the track (or 4 min) has played. */
function shouldScrobble(t: number, duration: number): boolean {
  return duration > 30 && (t >= 240 || t >= duration / 2);
}

interface Loaded {
  id: string;
  url: string;
  revoke?: () => void;
}

/**
 * Where to play `id` from: the on-device copy when there is one (so a
 * downloaded track plays with no connection at all), else the stream —
 * optionally asking the server to resolve that stream ahead of time.
 */
async function sourceFor(id: string, { warm = false } = {}): Promise<Loaded> {
  const blob = await getOfflineBlob(id).catch(() => null);
  if (blob) {
    const url = URL.createObjectURL(blob);
    return { id, url, revoke: () => URL.revokeObjectURL(url) };
  }
  if (warm) prefetchStream(id).catch(() => {});
  return { id, url: streamUrl(id) };
}

/**
 * The music player's single `<audio>` + Plyr instance and everything that
 * follows the current track:
 *
 * - loads it (the offline copy when there is one, else the stream);
 * - prepares `upcoming` (its offline copy, or a server-side stream warm-up)
 *   and, when a track ends, swaps it into the `<audio>` element right inside
 *   the `ended` event — no React round-trip, no await — so the next song
 *   starts with the screen off / app in the background, like a native
 *   player. The browser (Android especially) won't start audio again once
 *   the page has gone silent in the background, so the gap must be zero;
 * - autoplays it, and if the browser blocks that anyway retries on the next
 *   tap or when the tab is visible;
 * - on a hard reload, restores the queue's track at its saved position
 *   without autoplaying or re-logging the play;
 * - logs the play, scrobbles now-playing / the listen, keeps the lock screen
 *   (Media Session) and the now-playing store in sync;
 * - hands the element to volume leveling.
 *
 * `onEnded` runs when a track finishes (the caller advances the queue).
 * Returns the refs the caller renders (`<audio ref={audioRef} />`) and
 * drives (keyboard shortcuts), plus the leveling toggle.
 */
export function useAudioEngine({
  current,
  upcoming,
  next,
  prev,
  onEnded,
}: {
  current: Track | undefined;
  /** The track `next()` will move to, if any. */
  upcoming: Track | undefined;
  next: () => void;
  prev: () => void;
  onEnded: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const plyrRef = useRef<Plyr | null>(null);

  // Latest values for listeners registered once.
  const actionsRef = useRef({ next, prev });
  actionsRef.current = { next, prev };
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;
  const currentRef = useRef(current);
  currentRef.current = current;
  const upcomingRef = useRef(upcoming);
  upcomingRef.current = upcoming;

  // What the <audio> element holds right now (`revoke` frees a blob URL).
  const loadedRef = useRef<Loaded | null>(null);
  // The upcoming track's source, ready to swap in synchronously on "ended".
  const preparedRef = useRef<Loaded | null>(null);
  // Set when "ended" already loaded the next track, so the load effect for
  // that track only does the bookkeeping instead of reloading it.
  const handedOffRef = useRef<string | null>(null);

  function setSource(audio: HTMLAudioElement, src: Loaded) {
    const prevSrc = loadedRef.current;
    audio.src = src.url;
    loadedRef.current = src;
    if (prevSrc && prevSrc.url !== src.url) prevSrc.revoke?.();
  }

  // Track finished: start the next one in this same task, while the page is
  // still "playing audio" as far as the OS is concerned.
  function handOffToUpcoming(audio: HTMLAudioElement): boolean {
    const up = upcomingRef.current;
    const prepared = preparedRef.current;
    if (!up || !prepared || prepared.id !== up.id) return false;
    preparedRef.current = null; // ownership moves to loadedRef
    setSource(audio, prepared);
    handedOffRef.current = up.id;
    audio.play().catch(() => {
      setMediaSessionState("paused");
      scheduleAutoplayResume();
    });
    return true;
  }

  const scrobbledRef = useRef(false);
  // True only for the first track when it came back from a persisted queue.
  const restoringRef = useRef<boolean>(!!current);
  const resumeCleanupRef = useRef<(() => void) | null>(null);

  const leveling = useVolumeLeveling(audioRef);
  const { resume: resumeAudioCtx, close: closeAudioCtx } = leveling;

  // Autoplay was blocked: try again on the next tap or when we're visible.
  function scheduleAutoplayResume() {
    resumeCleanupRef.current?.();
    function attempt() {
      cleanup();
      audioRef.current?.play().catch(() => {
        /* still blocked; nothing more to do until a real interaction */
      });
    }
    function onVisible() {
      if (document.visibilityState === "visible") attempt();
    }
    function cleanup() {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pointerdown", attempt);
      resumeCleanupRef.current = null;
    }
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pointerdown", attempt, { once: true });
    resumeCleanupRef.current = cleanup;
  }

  // ---- Plyr lifecycle (once) ----
  useEffect(() => {
    if (!audioRef.current) return;
    const player = new Plyr(audioRef.current, {
      controls: ["play", "progress", "current-time", "duration", "mute", "volume"],
      seekTime: 5,
      storage: { enabled: true, key: "resonar" },
    });
    plyrRef.current = player;
    registerSeeker((t) => {
      try {
        player.currentTime = t;
      } catch {
        /* ignore */
      }
    });

    let lastPush = 0;
    let lastPosSave = 0;
    player.on("timeupdate", () => {
      const now = performance.now();
      if (now - lastPush < TIME_PUSH_EVERY) return;
      lastPush = now;
      const t = player.currentTime;
      const d = player.duration || 0;
      setNowPlaying({ time: t, duration: d });

      const c = currentRef.current;
      if (c && t > 3 && now - lastPosSave > POSITION_SAVE_EVERY) {
        lastPosSave = now;
        savePosition(c.id, t);
      }
      setMediaSessionPosition(t, d);
      if (c && !scrobbledRef.current && shouldScrobble(t, d)) {
        scrobbledRef.current = true;
        if (scrobblingOn()) scrobbleSubmit(c);
      }
    });
    player.on("play", () => {
      claimPlayback("music");
      resumeAudioCtx();
      setNowPlaying({ paused: false });
      setMediaSessionState("playing");
    });
    player.on("pause", () => {
      // "pause" fires right before "ended": if a next track is lined up,
      // don't tell the OS we stopped — it may drop us in the background.
      const a = audioRef.current;
      const up = upcomingRef.current;
      if (a?.ended && up && preparedRef.current?.id === up.id) return;
      setNowPlaying({ paused: true });
      setMediaSessionState("paused");
    });
    player.on("ended", () => {
      const a = audioRef.current;
      if (a) handOffToUpcoming(a);
      onEndedRef.current();
    });

    const off = onPlaybackClaim((kind) => {
      if (kind !== "music") audioRef.current?.pause();
    });
    return () => {
      off();
      resumeCleanupRef.current?.();
      player.destroy();
      closeAudioCtx();
      loadedRef.current?.revoke?.();
      preparedRef.current?.revoke?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Load the current track ----
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !current) return;
    const track = current;

    const restoring = restoringRef.current;
    restoringRef.current = false;
    // A new track supersedes any pending "resume the blocked autoplay".
    resumeCleanupRef.current?.();
    scrobbledRef.current = false;

    const handedOff = handedOffRef.current === track.id && !restoring;
    handedOffRef.current = null;
    if (handedOff) {
      // "ended" already swapped this track in and started it.
      if (!audio.paused) setMediaSessionState("playing");
      recordPlay(track, "song", "player");
      if (scrobblingOn()) scrobbleNowPlaying(track);
      bindMediaSession(
        track,
        () => audioRef.current,
        () => actionsRef.current.next(),
        () => actionsRef.current.prev(),
      );
      return;
    }

    let cancelled = false;

    (async () => {
      const src = await sourceFor(track.id);
      if (cancelled) {
        src.revoke?.();
        return;
      }
      setSource(audio, src);

      if (restoring) {
        // Back from a hard reload: ready-to-play at the saved spot, but no
        // autoplay (the browser blocks it) and no second play log.
        const t = loadPosition(track.id);
        if (t != null) {
          const onMeta = () => {
            try {
              audio.currentTime = t;
            } catch {
              /* ignore */
            }
            audio.removeEventListener("loadedmetadata", onMeta);
          };
          audio.addEventListener("loadedmetadata", onMeta);
        }
      } else {
        audio.play().catch(() => {
          // Blocked — show the real state on the lock screen and retry as
          // soon as we're foregrounded or tapped.
          setMediaSessionState("paused");
          scheduleAutoplayResume();
        });
        recordPlay(track, "song", "player");
        if (scrobblingOn()) scrobbleNowPlaying(track);
      }

      bindMediaSession(
        track,
        () => audioRef.current,
        () => actionsRef.current.next(),
        () => actionsRef.current.prev(),
      );
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  // ---- Line up the next track so "ended" can start it instantly ----
  useEffect(() => {
    if (!upcoming) return;
    const id = upcoming.id;
    let mine: Loaded | null = null;
    let cancelled = false;
    (async () => {
      const src = await sourceFor(id, { warm: true });
      if (cancelled) {
        src.revoke?.();
        return;
      }
      mine = src;
      preparedRef.current?.revoke?.();
      preparedRef.current = src;
    })();
    return () => {
      cancelled = true;
      // Not consumed by a hand-off: free it.
      if (mine && preparedRef.current === mine) {
        preparedRef.current = null;
        mine.revoke?.();
      }
    };
  }, [upcoming?.id]);

  return {
    audioRef,
    plyrRef,
    actionsRef,
    leveled: leveling.leveled,
    toggleLevel: leveling.toggleLevel,
  };
}
