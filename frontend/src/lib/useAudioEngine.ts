import { useEffect, useRef } from "react";
import Plyr from "plyr";
import "plyr/dist/plyr.css";

import { recordPlay, scrobbleNowPlaying, scrobbleSubmit, streamUrl } from "../api";
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

/**
 * The music player's single `<audio>` + Plyr instance and everything that
 * follows the current track:
 *
 * - loads it (the offline copy when there is one, else the stream);
 * - autoplays it, and if the browser blocks that (a track change while the
 *   app is backgrounded) retries on the next tap or when the tab is visible;
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
  next,
  prev,
  onEnded,
}: {
  current: Track | undefined;
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
      setNowPlaying({ paused: true });
      setMediaSessionState("paused");
    });
    player.on("ended", () => onEndedRef.current());

    const off = onPlaybackClaim((kind) => {
      if (kind !== "music") audioRef.current?.pause();
    });
    return () => {
      off();
      resumeCleanupRef.current?.();
      player.destroy();
      closeAudioCtx();
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

    let cancelled = false;
    let revokeSrc: (() => void) | null = null;

    (async () => {
      // Prefer the on-device copy so a downloaded track plays with no
      // connection at all.
      const blob = await getOfflineBlob(track.id).catch(() => null);
      if (cancelled) return;
      if (blob) {
        const url = URL.createObjectURL(blob);
        revokeSrc = () => URL.revokeObjectURL(url);
        audio.src = url;
      } else {
        audio.src = streamUrl(track.id);
      }

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
      revokeSrc?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  return {
    audioRef,
    plyrRef,
    actionsRef,
    leveled: leveling.leveled,
    toggleLevel: leveling.toggleLevel,
  };
}
