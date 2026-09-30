import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, related: vi.fn() };
});

import { related } from "../api";
import type { Track } from "../types";
import { freshTracks, useRadio } from "./radio";

const t = (id: string): Track => ({ id, title: id, artists: [] }) as unknown as Track;

describe("freshTracks", () => {
  it("drops tracks already queued and caps at 20", () => {
    const many = Array.from({ length: 30 }, (_, i) => t(`n${i}`));
    const out = freshTracks([t("a"), ...many], [t("a"), t("b")]);
    expect(out).toHaveLength(20);
    expect(out[0].id).toBe("n0");
  });
});

describe("useRadio", () => {
  beforeEach(() => vi.mocked(related).mockReset());

  it("fills the queue when switched on with nothing queued", async () => {
    vi.mocked(related).mockResolvedValue([t("a"), t("x"), t("y")]);
    const appendMany = vi.fn();
    const props = { radio: false, current: t("a"), hasNext: false, queue: [t("a")], appendMany };
    const { rerender } = renderHook((p) => useRadio(p), { initialProps: props });
    expect(related).not.toHaveBeenCalled();

    rerender({ ...props, radio: true });
    await waitFor(() => expect(appendMany).toHaveBeenCalledWith([t("x"), t("y")]));
  });

  it("does nothing on switch-on when more songs are queued", () => {
    const appendMany = vi.fn();
    const props = { radio: false, current: t("a"), hasNext: true, queue: [t("a"), t("b")], appendMany };
    const { rerender } = renderHook((p) => useRadio(p), { initialProps: props });
    rerender({ ...props, radio: true });
    expect(related).not.toHaveBeenCalled();
  });

  it("extendIfNeeded tops up at the end of the queue only while radio is on", async () => {
    vi.mocked(related).mockResolvedValue([t("z")]);
    const appendMany = vi.fn();
    const props = { radio: true, current: t("a"), hasNext: false, queue: [t("a")], appendMany };
    const { result, rerender } = renderHook((p) => useRadio(p), { initialProps: props });
    await waitFor(() => expect(appendMany).toHaveBeenCalledTimes(0));

    await act(() => result.current());
    expect(appendMany).toHaveBeenCalledWith([t("z")]);

    appendMany.mockClear();
    vi.mocked(related).mockClear();
    rerender({ ...props, radio: false });
    await act(() => result.current());
    expect(related).not.toHaveBeenCalled();
  });

  it("extendIfNeeded swallows a failed lookup", async () => {
    // A malformed response makes the lookup throw inside the hook. (A mock
    // returning a rejected promise can't be used: vitest reports the
    // rejection of a mock's return value itself, even when it is handled.)
    vi.mocked(related).mockResolvedValue(null as unknown as Track[]);
    const appendMany = vi.fn();
    const props = { radio: true, current: t("a"), hasNext: false, queue: [], appendMany };
    const { result } = renderHook((p) => useRadio(p), { initialProps: props });
    await act(async () => {
      await expect(result.current()).resolves.toBeUndefined();
    });
    expect(appendMany).not.toHaveBeenCalled();
  });
});
