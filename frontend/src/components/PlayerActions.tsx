import { downloadUrl } from "../api";
import { isSaved, toggleLibrary, useLibrary } from "../state/library";
import {
  downloadOffline,
  isOffline,
  offlineStatus,
  removeOffline,
  useOfflineTracks,
} from "../state/offline";
import type { Track } from "../types";
import AddToPlaylistButton from "./AddToPlaylistButton";
import Icon from "./Icon";

/** The player's right-hand toolbar: favourite, playlist, leveling, lyrics,
 * radio, queue, offline and MP3 download for the current track. */
export default function PlayerActions({
  current,
  leveled,
  onToggleLevel,
  lyricsOpen,
  onToggleLyrics,
  radio,
  onToggleRadio,
  queueOpen,
  onToggleQueue,
  upcoming,
}: {
  current: Track | undefined;
  leveled: boolean;
  onToggleLevel: () => void;
  lyricsOpen: boolean;
  onToggleLyrics: () => void;
  radio: boolean;
  onToggleRadio: () => void;
  queueOpen: boolean;
  onToggleQueue: () => void;
  upcoming: number;
}) {
  const library = useLibrary();
  const offlineTracks = useOfflineTracks();
  const favourite = !!current && isSaved(current.id, library);
  const offlineOn = current ? isOffline(current.id, offlineTracks) : false;
  const offlineBusy = current
    ? offlineStatus(current.id, offlineTracks) === "downloading"
    : false;

  return (
    <div className="player__actions">
      <button
        className={"player__toggle" + (favourite ? " is-on" : "")}
        onClick={() => current && toggleLibrary(current)}
        disabled={!current}
        title={favourite ? "Quitar de favoritos" : "Añadir a favoritos"}
        aria-label="Favorito"
      >
        <Icon name="heart" size={16} filled={favourite} />
      </button>
      {current && (
        <AddToPlaylistButton track={current} className="player__toggle" size={16} />
      )}
      <button
        className={"player__toggle" + (leveled ? " is-on" : "")}
        onClick={onToggleLevel}
        title="Nivelar volumen entre canciones"
        aria-label="Nivelar volumen"
      >
        <Icon name="level" size={16} />
      </button>
      <button
        className={"player__toggle" + (lyricsOpen ? " is-on" : "")}
        onClick={onToggleLyrics}
        title="Letra"
        aria-label="Letra"
      >
        <Icon name="lyrics" size={16} />
      </button>
      <button
        className={"player__toggle" + (radio ? " is-on" : "")}
        onClick={onToggleRadio}
        title="Radio: seguir con canciones similares al terminar"
        aria-label="Radio"
      >
        <Icon name="radio" size={16} />
      </button>
      <button
        className={"player__toggle" + (queueOpen ? " is-on" : "")}
        onClick={onToggleQueue}
        title="Cola"
        aria-label="Cola"
      >
        <Icon name="queue" size={16} />
        {upcoming > 0 && <span className="player__badge">{upcoming}</span>}
      </button>
      {current && (
        <button
          className={"player__toggle" + (offlineOn ? " is-on" : "")}
          onClick={() =>
            offlineOn ? removeOffline(current.id) : downloadOffline(current)
          }
          disabled={offlineBusy}
          title={offlineOn ? "Quitar de escuchar sin conexión" : "Escuchar sin conexión"}
          aria-label="Escuchar sin conexión"
        >
          {offlineBusy ? (
            <span className="spinner" />
          ) : (
            <Icon name="offline" size={16} filled={offlineOn} />
          )}
        </button>
      )}
      {current && (
        <a className="player__download" href={downloadUrl(current.id, "mp3")} download>
          <Icon name="download" size={14} /> MP3
        </a>
      )}
    </div>
  );
}
