import { renderHook } from "@testing-library/react";
import type Plyr from "plyr";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../state/mediabus", () => ({ isVideoActive: vi.fn(() => false) }));

import { isVideoActive } from "../state/mediabus";
import { usePlayerKeyboard } from "./usePlayerKeyboard";

function setup() {
  const plyr = { togglePlay: vi.fn(), currentTime: 10, duration: 100, muted: false };
  const actions = { next: vi.fn(), prev: vi.fn() };
  renderHook(() =>
    usePlayerKeyboard({ current: plyr as unknown as Plyr }, { current: actions }),
  );
  return { plyr, actions };
}

const press = (key: string, target: EventTarget = window) =>
  target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));

describe("usePlayerKeyboard", () => {
  afterEach(() => vi.mocked(isVideoActive).mockReturnValue(false));

  it("maps the music shortcuts", () => {
    const { plyr, actions } = setup();
    press(" ");
    expect(plyr.togglePlay).toHaveBeenCalled();
    press("ArrowRight");
    expect(plyr.currentTime).toBe(15);
    press("ArrowLeft");
    press("ArrowLeft");
    expect(plyr.currentTime).toBe(5);
    press("n");
    press("P");
    expect(actions.next).toHaveBeenCalledTimes(1);
    expect(actions.prev).toHaveBeenCalledTimes(1);
    press("m");
    expect(plyr.muted).toBe(true);
  });

  it("stands down while typing or when a video owns playback", () => {
    const { plyr } = setup();
    const input = document.createElement("input");
    document.body.appendChild(input);
    press(" ", input);
    expect(plyr.togglePlay).not.toHaveBeenCalled();
    input.remove();

    vi.mocked(isVideoActive).mockReturnValue(true);
    press(" ");
    expect(plyr.togglePlay).not.toHaveBeenCalled();
  });
});
