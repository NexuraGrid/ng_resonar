/**
 * Where the current track was, so a hard reload (Ctrl+Shift+R) resumes the
 * same spot. Only the reload-restore path reads it; every other way of
 * reaching a track starts it from 0.
 */
export const POS_KEY = "resonar:pos";

/** Positions this close to the start aren't worth resuming. */
const MIN_RESUME_SECONDS = 3;

export function savePosition(id: string, t: number): void {
  if (t <= MIN_RESUME_SECONDS) return;
  try {
    localStorage.setItem(POS_KEY, JSON.stringify({ id, t }));
  } catch {
    /* ignore */
  }
}

/** The saved position for `id`, or null if none / another track / too early. */
export function loadPosition(id: string): number | null {
  try {
    const saved = JSON.parse(localStorage.getItem(POS_KEY) || "null") as {
      id?: string;
      t?: number;
    } | null;
    if (saved && saved.id === id && (saved.t ?? 0) > MIN_RESUME_SECONDS) {
      return saved.t as number;
    }
  } catch {
    /* ignore */
  }
  return null;
}
