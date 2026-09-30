import { useState } from "react";

import { usePlayer } from "../state/player";
import { useRadio } from "../lib/radio";
import { useAudioEngine } from "../lib/useAudioEngine";
import { useExpandedPlayer } from "../lib/useExpandedPlayer";
import { usePlayerKeyboard } from "../lib/usePlayerKeyboard";
import ArtistLinks from "./ArtistLinks";
import Icon from "./Icon";
import LyricsPanel from "./LyricsPanel";
import PlayerActions from "./PlayerActions";
import QueuePanel from "./QueuePanel";

/**
 * The music player footer. Composition only: playback lives in
 * `useAudioEngine`, the radio in `useRadio`, full-screen in
 * `useExpandedPlayer`, shortcuts in `usePlayerKeyboard`, and the toolbar in
 * `PlayerActions`.
 */
export default function PlayerBar() {
  const { current, next, prev, hasNext, radio, toggleRadio, appendMany, queue, index } =
    usePlayer();
  const upcoming = Math.max(0, queue.length - index - 1);
  const [queueOpen, setQueueOpen] = useState(false);
  const [lyricsOpen, setLyricsOpen] = useState(false);
  const { expanded, open: openExpanded, close: closeExpanded } = useExpandedPlayer(!!current);

  const extendRadio = useRadio({ radio, current, hasNext, queue, appendMany });
  const engine = useAudioEngine({
    current,
    next,
    prev,
    onEnded: () => {
      void extendRadio().then(() => engine.actionsRef.current.next());
    },
  });
  usePlayerKeyboard(engine.plyrRef, engine.actionsRef);

  return (
    <>
      <QueuePanel open={queueOpen} onClose={() => setQueueOpen(false)} />
      <LyricsPanel open={lyricsOpen} onClose={() => setLyricsOpen(false)} />

      <footer
        className={"player" + (expanded ? " player--expanded" : "")}
        data-expanded={expanded || undefined}
        role={expanded ? "dialog" : undefined}
        aria-label={expanded ? "Reproduciendo ahora" : undefined}
      >
        {expanded && (
          <button
            className="player__collapse"
            onClick={closeExpanded}
            aria-label="Contraer reproductor"
          >
            <Icon name="chevronDown" size={22} />
          </button>
        )}

        {expanded && current && (
          <span className="player__rings" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
        )}

        <button
          type="button"
          className="player__meta"
          onClick={openExpanded}
          disabled={!current}
          aria-label="Abrir pantalla completa"
        >
          {current?.thumbnail ? (
            <img src={current.thumbnail} alt="" className="player__art" />
          ) : (
            <div className="player__art player__art--empty" aria-hidden>
              <Icon name="video" size={18} />
            </div>
          )}
          <div className="player__text">
            <span className="player__title">{current?.title ?? "Nada sonando"}</span>
            <span className="player__artist">
              {current ? <ArtistLinks artists={current.artists} /> : "Elige una canción"}
            </span>
          </div>
        </button>

        <div className="player__center">
          <div className="player__transport">
            <button onClick={prev} aria-label="Anterior">
              <Icon name="skipBack" size={16} />
            </button>
            <button onClick={next} aria-label="Siguiente">
              <Icon name="skipForward" size={16} />
            </button>
          </div>
          <audio ref={engine.audioRef} />
        </div>

        <PlayerActions
          current={current}
          leveled={engine.leveled}
          onToggleLevel={engine.toggleLevel}
          lyricsOpen={lyricsOpen}
          onToggleLyrics={() => setLyricsOpen((v) => !v)}
          radio={radio}
          onToggleRadio={toggleRadio}
          queueOpen={queueOpen}
          onToggleQueue={() => setQueueOpen((v) => !v)}
          upcoming={upcoming}
        />
      </footer>
    </>
  );
}
