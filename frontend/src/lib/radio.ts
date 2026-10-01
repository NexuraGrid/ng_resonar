import { useCallback, useEffect, useRef } from "react";

import { related } from "../api";
import type { Track } from "../types";

/** Up to 20 of `candidates` that aren't already in `queue`. */
export function freshTracks(candidates: Track[], queue: Track[]): Track[] {
  const have = new Set(queue.map((t) => t.id));
  return candidates.filter((t) => !have.has(t.id)).slice(0, 20);
}

/**
 * "Radio": keep the queue going with songs similar to the current one.
 *
 * Whenever radio is on and the current track is the last one queued, fetches
 * similar songs right away — not when the track ends — so the player always
 * has a next track lined up and can move on with the screen off. Also
 * returns `extendIfNeeded` for the "track ended" handler, as a fallback.
 */
export function useRadio({
  radio,
  current,
  hasNext,
  queue,
  appendMany,
}: {
  radio: boolean;
  current: Track | undefined;
  hasNext: boolean;
  queue: Track[];
  appendMany: (tracks: Track[]) => void;
}): () => Promise<void> {
  const queueRef = useRef(queue);
  queueRef.current = queue;
  const appendRef = useRef(appendMany);
  appendRef.current = appendMany;
  // One look-ahead fetch per track, even if nothing fresh comes back.
  const filledFor = useRef<string | null>(null);

  useEffect(() => {
    if (!radio) filledFor.current = null;
    if (!radio || !current || hasNext || filledFor.current === current.id) return;
    filledFor.current = current.id;
    let alive = true;
    related(current.id)
      .then((more) => {
        if (!alive) return;
        const fresh = freshTracks(more, queueRef.current);
        if (fresh.length) appendRef.current(fresh);
      })
      .catch(() => {});
    return () => {
      alive = false;
      if (filledFor.current === current.id) filledFor.current = null;
    };
  }, [radio, current, hasNext]);

  return useCallback(async () => {
    if (!radio || hasNext || !current) return;
    try {
      const fresh = freshTracks(await related(current.id), queue);
      if (fresh.length) appendMany(fresh);
    } catch {
      /* ignore */
    }
  }, [radio, hasNext, current, queue, appendMany]);
}
