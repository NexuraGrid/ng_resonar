import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// A hand-rolled stand-in rather than vi.fn(): a rejected promise returned by
// a vi.fn fails the test even when the component handles it.
const importer = vi.hoisted(() => ({
  calls: [] as unknown[],
  impl: (() => Promise.resolve({ id: "" })) as (f: unknown) => Promise<{ id: string }>,
}));

vi.mock("../state/playlists", () => ({
  usePlaylists: () => [],
  createPlaylist: vi.fn(),
  deletePlaylist: vi.fn(),
  importPlaylistFile: (file: unknown) => {
    importer.calls.push(file);
    return importer.impl(file);
  },
}));

import PlaylistsView from "./PlaylistsView";

// jsdom's File has no .text(); browsers do.
if (!File.prototype.text) {
  File.prototype.text = function text(this: File) {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

function pick(contents: string) {
  const input = screen.getByTestId("playlist-file") as HTMLInputElement;
  const file = new File([contents], "mix.resonar.json", { type: "application/json" });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("PlaylistsView import from file", () => {
  beforeEach(() => {
    importer.calls = [];
  });

  it("imports the parsed file and opens the new playlist", async () => {
    importer.impl = () => Promise.resolve({ id: "new1" });
    const onOpen = vi.fn();
    render(<PlaylistsView onOpen={onOpen} />);
    const payload = { format: "resonar-playlist", version: 1, name: "Mix", tracks: [] };
    pick(JSON.stringify(payload));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith("new1"));
    expect(importer.calls).toEqual([payload]);
  });

  it("rejects a file that isn't JSON without calling the server", async () => {
    render(<PlaylistsView onOpen={vi.fn()} />);
    pick("not json at all");
    expect(await screen.findByText(/no es una playlist exportada/)).toBeTruthy();
    expect(importer.calls).toEqual([]);
  });

  it("shows the server's reason when the import is refused", async () => {
    importer.impl = () =>
      Promise.reject(new Error("422 El archivo no tiene canciones válidas."));
    render(<PlaylistsView onOpen={vi.fn()} />);
    pick("{}");
    expect(await screen.findByText("El archivo no tiene canciones válidas.")).toBeTruthy();
  });
});
