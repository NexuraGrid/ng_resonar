import { useRef, useState } from "react";

import {
  createPlaylist,
  deletePlaylist,
  importPlaylistFile,
  usePlaylists,
} from "../state/playlists";
import Icon from "./Icon";

export default function PlaylistsView({
  onOpen,
}: {
  onOpen: (id: string) => void;
}) {
  const lists = usePlaylists();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function newEmpty() {
    const name = window.prompt("Nombre de la playlist");
    if (!name) return;
    setError("");
    try {
      const pl = await createPlaylist(name);
      onOpen(pl.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function importUrl() {
    const url = window.prompt(
      "Pega la URL de una playlist o álbum de YouTube / YouTube Music",
    );
    if (!url) return;
    setBusy(true);
    setError("");
    try {
      const pl = await createPlaylist("", url);
      onOpen(pl.id);
    } catch (e) {
      const raw = e instanceof Error ? e.message : "";
      // send() throws "<status> <detail>" — show the server's detail if we got one.
      const detail = raw.replace(/^\d{3}\s*/, "").trim();
      setError(detail || "No se pudo importar esa URL.");
    } finally {
      setBusy(false);
    }
  }

  // A `.resonar.json` someone exported from their playlist: becomes a copy
  // of that playlist in this account.
  async function importFile(file: File) {
    setError("");
    if (file.size > 900_000) {
      setError("El archivo es demasiado grande.");
      return;
    }
    let data: unknown;
    try {
      data = JSON.parse(await file.text());
    } catch {
      setError("Ese archivo no es una playlist exportada de Resonar.");
      return;
    }
    setBusy(true);
    try {
      const pl = await importPlaylistFile(data);
      onOpen(pl.id);
    } catch (e) {
      const raw = e instanceof Error ? e.message : "";
      const detail = raw.replace(/^\d{3}\s*/, "").trim();
      setError(detail || "No se pudo importar ese archivo.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="view">
      <div className="view__bar">
        <h1 className="view__title">Playlists</h1>
        <div className="view__bar-actions">
          <button className="btn" onClick={newEmpty}>
            <Icon name="plus" size={15} /> Nueva
          </button>
          <button className="btn" onClick={importUrl} disabled={busy}>
            {busy ? <span className="spinner" /> : <Icon name="list" size={15} />}{" "}
            Importar de URL
          </button>
          <button
            className="btn"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
            title="Importar una playlist que alguien te compartió (.resonar.json)"
          >
            <Icon name="upload" size={15} /> Importar archivo
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            hidden
            data-testid="playlist-file"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void importFile(file);
            }}
          />
        </div>
      </div>

      {error && <p className="hint hint--error">{error}</p>}

      {lists.length === 0 ? (
        <div className="empty">
          <p>Aún no tienes playlists.</p>
          <p className="empty__sub">
            Crea una, importa desde una URL de YouTube / YT Music, o importa
            el archivo de una playlist que alguien te compartió.
          </p>
        </div>
      ) : (
        <div className="plgrid">
          {lists.map((pl) => (
            <div key={pl.id} className="plcard-wrap">
              <button className="plcard" onClick={() => onOpen(pl.id)}>
                <span className="plcard__art">
                  {pl.thumbnail ? (
                    <img src={pl.thumbnail} alt="" loading="lazy" />
                  ) : (
                    <Icon name="list" size={24} />
                  )}
                </span>
                <span className="plcard__name">{pl.name}</span>
                <span className="plcard__count">{pl.count} pistas</span>
              </button>
              <button
                className="plcard__del"
                aria-label={`Borrar la playlist ${pl.name}`}
                title="Borrar playlist"
                onClick={() => {
                  if (window.confirm(`¿Borrar la playlist "${pl.name}"?`)) {
                    deletePlaylist(pl.id);
                  }
                }}
              >
                <Icon name="trash" size={15} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
