import { savedVideoDownloadUrl } from "../api";
import type { SavedVideo, VideoItem } from "../types";
import { removeSavedVideo, saveVideo } from "../state/savedVideos";
import Icon from "./Icon";

function humanSize(bytes?: number): string | null {
  if (!bytes) return null;
  const mb = bytes / 1_048_576;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

export default function SavedVideoRow({
  entry,
  onWatch,
}: {
  entry: SavedVideo;
  onWatch: (v: VideoItem) => void;
}) {
  const ready = entry.status === "ready";
  // Older backends don't send it; the server still enforces the rule.
  const canDelete = entry.canDelete ?? true;
  const size = humanSize(entry.size);

  const open = () =>
    onWatch({
      id: entry.id,
      title: entry.title ?? entry.id,
      uploader: entry.uploader,
      duration: entry.duration,
      durationSeconds: entry.durationSeconds ?? null,
      views: null,
      thumbnail: entry.thumbnail,
    });

  return (
    <div className={"srow" + (ready ? "" : " srow--pending")}>
      <button className="srow__thumb" onClick={ready ? open : undefined} disabled={!ready}>
        <img src={entry.thumbnail} alt="" loading="lazy" />
        {ready && (
          <span className="srow__play">
            <Icon name="play" size={18} filled />
          </span>
        )}
        {entry.duration && <span className="srow__dur">{entry.duration}</span>}
      </button>

      <div className="srow__info">
        <span className="srow__title">{entry.title ?? entry.id}</span>
        <span className="srow__meta">
          {entry.status === "downloading" && (
            <>
              <span className="spinner" /> {entry.progress ?? "Guardando…"}
            </>
          )}
          {entry.status === "error" && (
            <span className="hint--error">Error al guardar</span>
          )}
          {ready && (
            <>
              {entry.uploader}
              {entry.uploader && (entry.height || size) ? " · " : ""}
              {entry.height ? `${entry.height}p` : ""}
              {entry.height && size ? " · " : ""}
              {size}
            </>
          )}
        </span>
      </div>

      <div className="srow__actions">
        {ready && (
          <a
            className="track__icon"
            href={savedVideoDownloadUrl(entry.id)}
            download
            title="Descargar archivo"
          >
            <Icon name="download" size={16} />
          </a>
        )}
        {entry.status === "error" && canDelete && (
          <button
            className="track__icon"
            title="Reintentar"
            onClick={() => saveVideo(entry.id, 1080, true)}
          >
            <Icon name="back" size={16} />
          </button>
        )}
        {canDelete && (
          <button
            className="track__icon"
            title="Quitar"
            onClick={() => removeSavedVideo(entry.id)}
          >
            <Icon name="x" size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
