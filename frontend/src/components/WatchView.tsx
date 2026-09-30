import { useCallback, useEffect, useState } from "react";

import {
  savedVideoDownloadUrl,
  searchVideos,
} from "../api";
import type { VideoItem } from "../types";
import {
  removeSavedVideo,
  saveVideo,
  savedEntry,
  useSavedVideos,
} from "../state/savedVideos";
import { useVideo } from "../state/video";
import Icon from "./Icon";
import VideoCard from "./VideoCard";

const QUALITIES = [720, 1080, 1440];

/**
 * The full-screen "watch" surface. The `<video>` / Plyr instance itself lives in
 * `VideoProvider` and survives navigation — this view only borrows the player
 * node into its stage (`attachTo`) and renders the surrounding chrome.
 */
export default function WatchView({
  video,
  onClose,
  onWatch,
}: {
  video: VideoItem;
  onClose: () => void;
  onWatch: (v: VideoItem) => void;
}) {
  const { current, loadState, sbOn, skipFlash, isHD, playVideo, reload, toggleSb, attachTo } =
    useVideo();

  // Stable ref callback so re-renders don't yank the player node out and back.
  const setStage = useCallback(
    (el: HTMLDivElement | null) => attachTo(el, "watch"),
    [attachTo],
  );

  const saved = useSavedVideos();
  const entry = savedEntry(video.id, saved);
  // Only whoever saved it (or an admin) may re-download or remove it.
  const canManage = entry?.canDelete ?? true;

  const [quality, setQuality] = useState(1080);
  const [related, setRelated] = useState<VideoItem[]>([]);

  // Point the persistent player at this video whenever the view opens / changes.
  useEffect(() => {
    playVideo(video);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [video.id]);

  // When opening a video that is already saved, default the picker to the
  // quality it was saved at so "Cambiar calidad" starts from the real value.
  useEffect(() => {
    if (entry?.status === "ready" && entry.quality) setQuality(entry.quality);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [video.id, entry?.status]);

  useEffect(() => {
    let alive = true;
    searchVideos(video.title)
      .then((r) => {
        if (alive) setRelated(r.filter((v) => v.id !== video.id));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [video.id, video.title]);

  // Only reflect load state for the video this view is actually showing.
  const showingThis = current?.id === video.id;

  return (
    <div className="view watch">
      <button className="watch__back" onClick={onClose}>
        <Icon name="back" size={16} /> Volver a videos
      </button>

      <div className="watch__stage">
        {isHD && showingThis && <span className="watch__hd">HD</span>}
        {skipFlash && showingThis && (
          <span className="watch__skip">⏭ Saltado: {skipFlash}</span>
        )}
        <div className="watch__stage-mount" ref={setStage} />
        {showingThis && loadState === "loading" && (
          <div className="watch__stage-overlay">
            <span className="spinner" /> Cargando video…
          </div>
        )}
        {showingThis && loadState === "error" && (
          <div className="watch__stage-overlay">
            <p>No se pudo cargar el video.</p>
            <button className="btn btn--accent" onClick={reload}>
              Reintentar
            </button>
          </div>
        )}
      </div>

      <h1 className="watch__title">{video.title}</h1>
      <p className="watch__meta">{video.uploader}</p>

      <div className="savebox">
        {!entry && (
          <>
            <select
              className="savebox__quality"
              value={quality}
              onChange={(e) => setQuality(Number(e.target.value))}
            >
              {QUALITIES.map((q) => (
                <option key={q} value={q}>
                  {q}p
                </option>
              ))}
            </select>
            <button
              className="btn btn--accent"
              onClick={() => saveVideo(video.id, quality)}
            >
              <Icon name="download" size={15} /> Guardar en HD
            </button>
          </>
        )}

        {entry?.status === "downloading" && (
          <button className="btn" disabled>
            <span className="spinner" /> Guardando… {entry.progress ?? ""}
          </button>
        )}

        {entry?.status === "ready" && (
          <>
            <span className="badge badge--hd">
              Guardado{entry.height ? ` · ${entry.height}p` : ""}
            </span>
            {canManage && (
              <>
                <select
                  className="savebox__quality"
                  value={quality}
                  onChange={(e) => setQuality(Number(e.target.value))}
                  aria-label="Calidad para volver a guardar"
                >
                  {QUALITIES.map((q) => (
                    <option key={q} value={q}>
                      {q}p
                    </option>
                  ))}
                </select>
                <button
                  className="btn"
                  onClick={() => saveVideo(video.id, quality, true)}
                  disabled={quality === entry.quality}
                  title="Vuelve a descargar el video en la calidad elegida"
                >
                  <Icon name="download" size={15} /> Cambiar calidad
                </button>
              </>
            )}
            <a className="btn" href={savedVideoDownloadUrl(video.id)} download>
              <Icon name="download" size={15} /> Descargar archivo
            </a>
            {canManage && (
              <button
                className="btn btn--ghost"
                onClick={() => removeSavedVideo(video.id)}
              >
                Quitar
              </button>
            )}
          </>
        )}

        {entry?.status === "error" && (
          <>
            <span className="hint hint--error">
              No se pudo guardar{entry.error ? `: ${entry.error}` : ""}
            </span>
            <button
              className="btn"
              onClick={() => saveVideo(video.id, quality, true)}
            >
              Reintentar
            </button>
          </>
        )}

        <button
          className={"chip" + (sbOn ? " chip--on" : "")}
          onClick={toggleSb}
          title="Saltar patrocinios e intros automáticamente (SponsorBlock)"
        >
          SponsorBlock {sbOn ? "activado" : "apagado"}
        </button>
      </div>

      <p className="watch__note">
        La vista rápida es 360–720p. «Guardar en HD» une video + audio en el
        servidor y lo deja re-reproducible en alta calidad.
      </p>

      {related.length > 0 && (
        <>
          <h2 className="watch__subhead">A continuación</h2>
          <div className="videogrid videogrid--compact">
            {related.slice(0, 12).map((v) => (
              <VideoCard key={v.id} video={v} onClick={() => onWatch(v)} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
