import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

function reducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Full-screen "now playing" = a CSS expansion of the player footer; this only
 * owns the boolean. Opening pushes a history entry (`np: true`) so the Back
 * gesture collapses the player instead of leaving the app, and the flip runs
 * inside a View Transition when the browser supports it.
 */
export function useExpandedPlayer(canOpen: boolean) {
  const [expanded, setExpanded] = useState(false);

  function flip(v: boolean) {
    if (typeof document.startViewTransition === "function" && !reducedMotion()) {
      document.startViewTransition(() => flushSync(() => setExpanded(v)));
    } else {
      setExpanded(v);
    }
  }

  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      flip(Boolean((e.state as NavHistoryState | null)?.np));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function open() {
    if (!canOpen || expanded) return;
    history.pushState({ ...(history.state || {}), np: true }, "");
    flip(true);
  }

  function close() {
    if ((history.state as NavHistoryState | null)?.np) history.back();
    else flip(false);
  }

  return { expanded, open, close };
}
