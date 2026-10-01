/**
 * A session belongs to the mode it started in (2026-10-01; the agent's
 * Session.set_mode refuses a change while one is open — sessions-and-modes.txt).
 *
 * The sidebar's Auto/Manual switch therefore does two different things:
 *   - no session open: it sets the mode the next session opens in (the agent);
 *   - a session open:  it only changes which page you LOOK at. The other
 *     mode's page says the session is open and offers the way back.
 */

import type { Mode, Session } from "@/lib/agent";

/** Mirrors the agent's Session._session_open_locked — UX only; the agent decides. */
export function sessionOpen(session: Session | null): boolean {
  if (!session) return false;
  if (session.session_id !== null) return true;
  return ["starting", "awaiting_confirmation", "ready", "busy", "ending"].includes(session.state);
}

/** The mode whose page is shown: the session's, unless the operator is looking at the other. */
export function shownMode(session: Session | null, lookingAt: Mode | null): Mode {
  const mode = session?.mode ?? "manual";
  return sessionOpen(session) && lookingAt ? lookingAt : mode;
}

export function modeName(mode: Mode): string {
  return mode === "auto" ? "Auto" : "Manual";
}
