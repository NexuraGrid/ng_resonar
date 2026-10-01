import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// A minimal Plyr: `on` just listens on the <audio> element.
vi.mock("plyr", () => ({
  default: class {
    media: HTMLMediaElement;
    constructor(el: HTMLMediaElement) {
      this.media = el;
    }
    on(ev: string, cb: () => void) {
      this.media.addEventListener(ev, cb);
    }
    destroy() {}
  },
}));
vi.mock("plyr/dist/plyr.css", () => ({}));
vi.mock("../api", () => ({
  prefetchStream: vi.fn(() => Promise.resolve()),
  recordPlay: vi.fn(),
  scrobbleNowPlaying: vi.fn(),
  scrobbleSubmit: vi.fn(),
  streamUrl: (id: string) => `/api/stream/${id}`,
}));
vi.mock("../state/offline", () => ({ getOfflineBlob: vi.fn(() => Promise.resolve(null)) }));

import { prefetchStream, recordPlay } from "../api";
import type { Track } from "../types";
import { useAudioEngine } from "./useAudioEngine";

const t = (id: string): Track => ({ id, title: id, artists: [] }) as unknown as Track;

function setup() {
  const audio = document.createElement("audio");
  const play = vi.fn(() => Promise.resolve());
  audio.play = play;
  const onEnded = vi.fn();
  const hook = renderHook(
    (p: { current: Track; upcoming: Track | undefined }) => {
      const engine = useAudioEngine({ ...p, next: vi.fn(), prev: vi.fn(), onEnded });
      // Attach our element before the engine's mount effects run.
      if (!engine.audioRef.current) {
        (engine.audioRef as { current: HTMLAudioElement }).current = audio;
      }
      return engine;
    },
    { initialProps: { current: t("a"), upcoming: t("b") as Track | undefined } },
  );
  return { audio, play, onEnded, ...hook };
}

describe("useAudioEngine", () => {
  beforeEach(() => {
    vi.mocked(recordPlay).mockClear();
    vi.mocked(prefetchStream).mockClear();
    localStorage.clear();
  });

  it("starts the next track inside the 'ended' event, before React moves on", async () => {
    const { audio, play, onEnded, rerender } = setup();
    await waitFor(() => expect(audio.src).toContain("/api/stream/a"));
    await waitFor(() => expect(prefetchStream).toHaveBeenCalledWith("b"));
    play.mockClear();

    act(() => {
      audio.dispatchEvent(new Event("ended"));
    });
    // Synchronously swapped and started — no await, no re-render needed.
    expect(audio.src).toContain("/api/stream/b");
    expect(play).toHaveBeenCalledTimes(1);
    expect(onEnded).toHaveBeenCalledTimes(1);

    // The queue then advances: the engine logs the play but doesn't reload.
    rerender({ current: t("b"), upcoming: undefined });
    await waitFor(() =>
      expect(recordPlay).toHaveBeenLastCalledWith(t("b"), "song", "player"),
    );
    expect(play).toHaveBeenCalledTimes(1);
  });

  it("leaves it to the caller when nothing is lined up", async () => {
    const { audio, play, onEnded, rerender } = setup();
    rerender({ current: t("a"), upcoming: undefined });
    await waitFor(() => expect(audio.src).toContain("/api/stream/a"));
    play.mockClear();

    act(() => {
      audio.dispatchEvent(new Event("ended"));
    });
    expect(audio.src).toContain("/api/stream/a");
    expect(play).not.toHaveBeenCalled();
    expect(onEnded).toHaveBeenCalledTimes(1);
  });
});
