import { useEffect, type RefObject } from "react";
import type Plyr from "plyr";

import { isVideoActive } from "../state/mediabus";

/** Keys that belong to a text field, not to the player. */
function typingInto(el: HTMLElement | null): boolean {
  return (
    !!el &&
    (el.tagName === "INPUT" ||
      el.tagName === "TEXTAREA" ||
      el.tagName === "SELECT" ||
      el.isContentEditable)
  );
}

/**
 * Global music shortcuts: Space play/pause, ←/→ seek 5 s, N / P next /
 * previous, M mute. Stands down while typing or while a video owns playback.
 */
export function usePlayerKeyboard(
  plyrRef: RefObject<Plyr | null>,
  actions: RefObject<{ next: () => void; prev: () => void }>,
): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typingInto(e.target as HTMLElement | null) || isVideoActive()) return;
      const p = plyrRef.current;
      if (!p) return;
      switch (e.key) {
        case " ":
          e.preventDefault();
          p.togglePlay();
          break;
        case "ArrowRight":
          p.currentTime = Math.min(p.duration || Infinity, p.currentTime + 5);
          break;
        case "ArrowLeft":
          p.currentTime = Math.max(0, p.currentTime - 5);
          break;
        case "n":
        case "N":
          actions.current?.next();
          break;
        case "p":
        case "P":
          actions.current?.prev();
          break;
        case "m":
        case "M":
          p.muted = !p.muted;
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [plyrRef, actions]);
}
