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
 * Fills the queue as soon as radio is switched on (if nothing is queued after
 * the current track), and returns `extendIfNeeded` for the "track ended"
 * handler to top the queue up before advancing.
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
  const radioWasOn = useRef(radio);
  useEffect(() => {
    const turnedOn = radio && !radioWasOn.current;
    radioWasOn.current = radio;
    if (!turnedOn || !current || hasNext) return;
    let alive = true;
    related(current.id)
      .then((more) => {
        if (!alive) return;
        const fresh = freshTracks(more, queue);
        if (fresh.length) appendMany(fresh);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [radio, current, hasNext, queue, appendMany]);

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
