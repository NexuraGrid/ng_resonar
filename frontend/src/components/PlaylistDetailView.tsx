import { useEffect, useRef, useState } from "react";

import { batchFileUrl, batchStatusApi, playlistExportUrl, startBatchApi } from "../api";
import {
  deletePlaylist,
  removeFromPlaylist,
  renamePlaylist,
  reorderPlaylist,
  usePlaylist,
} from "../state/playlists";
import { downloadManyOffline } from "../state/offline";
import { usePlayer } from "../state/player";
import { shuffled } from "../lib/shuffle";
import { useListKeyboard } from "../lib/useListKeyboard";
import Icon from "./Icon";
import PlaylistTrackRow from "./PlaylistTrackRow";

function moved(ids: string[], from: number, to: number): string[] {
  const copy = ids.slice();
  const [x] = copy.splice(from, 1);
  copy.splice(to, 0, x);
  return copy;
}

type Batch =
  | { state: "idle" }
  | { state: "running"; done: number; total: number }
  | { state: "error"; msg: string };

export default function PlaylistDetailView({
  id,
  onBack,
}: {
  id: string;
  onBack: () => void;
}) {
  const pl = usePlaylist(id);
  const { playList, queueNext } = usePlayer();
  const [batch, setBatch] = useState<Batch>({ state: "idle" });
  const pollRef = useRef<number>();

  useEffect(() => () => window.clearInterval(pollRef.current), []);

  const plTracks = pl?.tracks ?? [];
  const { activeIndex, listRef } = useListKeyboard(
    plTracks.length,
    (i) => playList(plTracks, i),
  );

  if (!pl) {
    return (
      <div className="view">
        <button className="watch__back" onClick={onBack}>
          <Icon name="back" size={16} /> Volver
        </button>
        <p className="hint">Cargando…</p>
      </div>
    );
  }

  const tracks = pl.tracks;
  const name = pl.name;
  const ids = tracks.map((t) => t.id);

  async function startBatch() {
    if (!tracks.length) return;
    setBatch({ state: "running", done: 0, total: tracks.length });
    try {
      const { jobId } = await startBatchApi(ids, name, "mp3");
      pollRef.current = window.setInterval(async () => {
        try {
          const st = await batchStatusApi(jobId);
          if (st.ready) {
            window.clearInterval(pollRef.current);
            setBatch({ state: "idle" });
            window.location.href = batchFileUrl(jobId);
          } else if (st.status === "error") {
            window.clearInterval(pollRef.current);
            setBatch({ state: "error", msg: st.error ?? "falló la descarga" });
          } else {
            setBatch({
              state: "running",
              done: st.progress?.done ?? 0,
              total: st.progress?.total ?? tracks.length,
            });
          }
        } catch {
          /* keep polling */
        }
      }, 2000);
    } catch {
      setBatch({ state: "error", msg: "no se pudo iniciar" });
    }
  }

  return (
    <div className="view">
      <button className="watch__back" onClick={onBack}>
        <Icon name="back" size={16} /> Volver
      </button>

      <div className="pldetail__head">
        <div className="pldetail__art">
          {pl.tracks[0]?.thumbnail ? (
            <img src={pl.tracks[0].thumbnail} alt="" />
          ) : (
            <Icon name="list" size={30} />
          )}
        </div>
        <div className="pldetail__meta">
          <h1>{pl.name}</h1>
          <p>{pl.tracks.length} pistas</p>
          <div className="pldetail__actions">
            <button
              className="btn btn--accent"
              disabled={!pl.tracks.length}
              onClick={() => playList(pl.tracks, 0)}
            >
              <Icon name="play" size={14} filled /> Reproducir
            </button>
            <button
              className="btn"
              disabled={!pl.tracks.length}
              onClick={() => playList(shuffled(pl.tracks), 0)}
            >
              <Icon name="shuffle" size={14} /> Aleatorio
            </button>
            <button
              className="btn btn--ghost"
              disabled={!pl.tracks.length}
              onClick={() => queueNext(pl.tracks)}
              title="Añadir todas a la cola"
            >
              <Icon name="queue" size={14} /> A la cola
            </button>
            <button
              className="btn btn--ghost"
              disabled={!pl.tracks.length}
              onClick={() =>
                downloadManyOffline(pl.tracks, { collection: { id, name: pl.name } })
              }
              title="Descargar toda la playlist para escuchar sin conexión"
            >
              <Icon name="offline" size={14} /> Sin conexión
            </button>
            <a
              className="btn"
              href={playlistExportUrl(id)}
              download
              title="Descarga un archivo para compartir esta playlist: quien lo importe tendrá su propia copia"
            >
              <Icon name="upload" size={14} /> Compartir (exportar)
            </a>
            <button
              className="btn"
              onClick={() => {
                const n = window.prompt("Nuevo nombre", pl.name);
                if (n) renamePlaylist(id, n);
              }}
            >
              <Icon name="pencil" size={14} /> Renombrar
            </button>
            <button
              className="btn"
              disabled={!pl.tracks.length || batch.state === "running"}
              onClick={startBatch}
            >
              {batch.state === "running" ? (
                <>
                  <span className="spinner" /> Preparando {batch.done}/
                  {batch.total}…
                </>
              ) : (
                <>
                  <Icon name="download" size={14} /> Descargar todo (MP3)
                </>
              )}
            </button>
            <button
              className="btn btn--ghost"
              onClick={() => {
                if (window.confirm(`¿Borrar la playlist "${pl.name}"?`)) {
                  deletePlaylist(id);
                  onBack();
                }
              }}
            >
              <Icon name="trash" size={14} /> Borrar
            </button>
          </div>
          {batch.state === "error" && (
            <p className="hint hint--error">No se pudo descargar: {batch.msg}</p>
          )}
        </div>
      </div>

      {pl.tracks.length === 0 ? (
        <div className="empty">
          <p>Esta playlist está vacía.</p>
          <p className="empty__sub">
            Añade canciones desde la búsqueda con el botón ＋.
          </p>
        </div>
      ) : (
        <div className="tracklist tracklist--pl" ref={listRef}>
          {pl.tracks.map((track, i) => (
            <PlaylistTrackRow
              key={track.id}
              track={track}
              index={i}
              selected={i === activeIndex}
              onPlay={() => playList(pl.tracks, i)}
              onRemove={() => removeFromPlaylist(id, track.id)}
              onUp={i > 0 ? () => reorderPlaylist(id, moved(ids, i, i - 1)) : undefined}
              onDown={
                i < pl.tracks.length - 1
                  ? () => reorderPlaylist(id, moved(ids, i, i + 1))
                  : undefined
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
