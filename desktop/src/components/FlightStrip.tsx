/**
 * The strip across the top of the window.
 *
 * It exists so that **Land and Emergency stop are always visible** while a
 * session is running. That is a safety decision recorded in
 * docs/features/desktop/pages-and-windows.txt, and it is the reason the
 * navigation moved to a sidebar but these did not: a nav rail scrolls, and an
 * abort control that can be scrolled out of reach is not an abort control.
 *
 * Everything here is *state and stopping*. Everything that starts something is
 * on the Control page.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Session, SyncStatus } from "@/lib/agent";
import { Button, StatusDot, type Tone } from "@/components/ui";

/** The session state, as a chip: what the window is, in two or three words. */
const STATE_LABEL: Record<Session["state"], string> = {
  signed_out: "Signed out",
  idle: "Idle",
  starting: "Running checks",
  checks_failed: "Checks failed",
  awaiting_confirmation: "Awaiting confirmation",
  ready: "Ready",
  busy: "Busy",
  ending: "Ending",
};

const STATE_TONE: Record<Session["state"], Tone> = {
  signed_out: "idle",
  idle: "idle",
  starting: "idle",
  checks_failed: "critical",
  awaiting_confirmation: "warning",
  ready: "good",
  busy: "good",
  ending: "idle",
};

export function FlightStrip({
  session, sync, connected, flying, inSession, onLand, onStop, onEndSession,
}: {
  session: Session | null;
  sync: SyncStatus | null;
  connected: boolean;
  flying: boolean;
  inSession: boolean;
  onLand: () => void;
  onStop: () => void;
  onEndSession: () => void;
}) {
  // While flying, the activity is more use than the state: "busy" says nothing,
  // "manual" or the program's own phase says what the drone is doing.
  const activity = flying ? (session?.flight?.phase ?? session?.activity ?? null) : null;

  return (
    // py-1.5, so a 44 px Land/Stop button makes this a 56 px strip rather than
    // a 60 px one. The buttons set the height here, not the padding.
    <header className="flex min-h-12 flex-wrap items-center gap-x-4 gap-y-2 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-1.5">
      <div className="mono flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs uppercase tracking-[0.06em]">
        {session && (
          <StatusDot tone={STATE_TONE[session.state]}>
            {activity ? `${STATE_LABEL[session.state]} · ${activity}` : STATE_LABEL[session.state]}
          </StatusDot>
        )}
        {session && session.state !== "signed_out" && (
          <span className="text-[var(--muted)]">
            {session.mode}
            {session.state !== "idle" && (session.assisted ? " · assisted" : " · barometer")}
          </span>
        )}
      </div>

      <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-3 text-sm">
        <SyncBadge sync={sync} connected={connected} />
        {flying && (
          <>
            <Button onClick={onLand} title="Land gracefully (L)">
              Land <kbd className="border border-[var(--border)] px-1 text-xs">L</kbd>
            </Button>
            <HoldToStop onStop={onStop} />
          </>
        )}
        {inSession && !flying && session?.state !== "ending" && (
          <Button
            variant="danger"
            onClick={onEndSession}
            title="Land if needed, save and upload, then disconnect"
          >
            End session
          </Button>
        )}
      </div>
    </header>
  );
}

function SyncBadge({ sync, connected }: { sync: SyncStatus | null; connected: boolean }) {
  if (!connected || !sync) return null;
  const pending = sync.pending_flights + sync.pending_events;
  if (pending === 0) {
    return <StatusDot tone="good">All data synced</StatusDot>;
  }
  return (
    <StatusDot tone="warning">
      {sync.pending_flights > 0
        ? `${sync.pending_flights} flight${sync.pending_flights === 1 ? "" : "s"} to upload`
        : "Records to upload"}
    </StatusDot>
  );
}

/**
 * Emergency stop: hold for a second.
 *
 * Stopping the motors mid-air drops the drone, so it takes a deliberate press
 * and has no keyboard shortcut. Land is the normal way to come down.
 *
 * Moved here verbatim from App.tsx — the timing, the pointer handling and the
 * keyboard refusal are unchanged.
 */
const HOLD_MS = 1000;

function HoldToStop({ onStop }: { onStop: () => void }) {
  const [progress, setProgress] = useState(0);
  const timer = useRef<number | null>(null);

  const cancel = useCallback(() => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    setProgress(0);
  }, []);

  const begin = useCallback(() => {
    if (timer.current !== null) return;
    const started = Date.now();
    timer.current = window.setInterval(() => {
      const ratio = Math.min(1, (Date.now() - started) / HOLD_MS);
      setProgress(ratio);
      if (ratio >= 1) {
        cancel();
        onStop();
      }
    }, 30);
  }, [cancel, onStop]);

  useEffect(() => cancel, [cancel]);

  return (
    <button
      type="button"
      onPointerDown={begin}
      onPointerUp={cancel}
      onPointerLeave={cancel}
      onKeyDown={(e) => {
        // Enter and Space would "click" this in one keystroke; the whole point
        // is that it cannot happen by accident.
        e.preventDefault();
      }}
      aria-label="Emergency stop — hold for one second"
      // min-h-11 is 44 px and stays 44 px. The strip got shorter everywhere
      // else; this target does not shrink with it. It is the control an
      // operator reaches for while something is going wrong.
      className="relative min-h-11 overflow-hidden border-2 border-[var(--status-critical)] px-4 text-sm font-bold text-[var(--status-critical)]"
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-0 bg-[var(--status-critical)]"
        style={{ width: `${progress * 100}%` }}
      />
      <span className="relative" style={{ color: progress > 0.5 ? "var(--on-critical)" : undefined }}>
        {progress > 0 ? "Hold…" : "Emergency stop"}
      </span>
    </button>
  );
}
