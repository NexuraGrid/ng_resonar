import { beforeEach, describe, expect, it } from "vitest";

import { loadPosition, POS_KEY, savePosition } from "./playbackPosition";

describe("playbackPosition", () => {
  beforeEach(() => localStorage.clear());

  it("round-trips the position of the same track", () => {
    savePosition("abc", 42.5);
    expect(loadPosition("abc")).toBe(42.5);
  });

  it("ignores another track's position", () => {
    savePosition("abc", 42);
    expect(loadPosition("xyz")).toBeNull();
  });

  it("doesn't save or resume the first seconds", () => {
    savePosition("abc", 2);
    expect(localStorage.getItem(POS_KEY)).toBeNull();
    localStorage.setItem(POS_KEY, JSON.stringify({ id: "abc", t: 1 }));
    expect(loadPosition("abc")).toBeNull();
  });

  it("survives garbage in storage", () => {
    localStorage.setItem(POS_KEY, "{not json");
    expect(loadPosition("abc")).toBeNull();
  });
});
