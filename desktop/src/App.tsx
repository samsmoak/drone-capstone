/**
 * The CropWatcher window.
 *
 * A top bar with the Auto/Manual toggle and the pages, then one page at a time:
 * Home (where you are and what to do next), Control (what you do), and the live
 * sensor windows (what the drone reports). Home opens first — an operator who
 * has just installed this needs the next step, not six tabs.
 *
 * Two controls are always present while a session is running, because the
 * moment you need them is the moment something is going wrong:
 *
 * - **Land** — the normal way to end a flight, and the keyboard's `L`.
 * - **Emergency stop** — hold for a second. No keyboard shortcut: cutting the
 *   motors in the air drops the drone, so it must be deliberate.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AgentError,
  EMPTY_INTENT,
  LiveConnection,
  api,
  connectToShell,
  type Intent,
  type Mode,
  type Session,
  type SyncStatus,
  type Telemetry,
} from "./agent";
import { ControlPage } from "./ControlPage";
import { HomePage } from "./HomePage";
import { ProfileMenu } from "./ProfileMenu";
import { SessionsPage, WindowLog } from "./HistoryPages";
import { StartupPage } from "./StartupPage";
import { SensorWindow, WINDOWS, type WindowKey } from "./windows";
import { Button, Message, StatusDot } from "./ui";

/** One width and one side padding for the bar and the page, so their edges line up. */
export const CONTAINER = "mx-auto w-full max-w-6xl px-6";

/** Physical key → intent field. `code`, so the keys stay in the same place on AZERTY. */
export const KEY_MAP: Record<string, keyof Intent> = {
  ArrowUp: "forward",
  ArrowDown: "back",
  ArrowLeft: "left",
  ArrowRight: "right",
  KeyW: "up",
  KeyS: "down",
  KeyA: "yaw_left",
  KeyD: "yaw_right",
};

const HISTORY_S = 60;
const HISTORY_LIMIT = HISTORY_S * 10;      // 10 Hz

export type History = { t: number; values: Record<string, number>; height_m: number | null }[];

export type Page = "home" | "control" | "sessions" | WindowKey;

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const [history, setHistory] = useState<History>([]);
  const [connected, setConnected] = useState(false);
  const [page, setPageState] = useState<Page>("home");
  // Drill-downs within a page: one session's detail, or a window's history log.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [logWindow, setLogWindow] = useState<WindowKey | null>(null);
  const setPage = useCallback((next: Page) => {
    setPageState(next);
    setSessionId(null);
    setLogWindow(null);
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [intent, setIntent] = useState<Intent>(EMPTY_INTENT);

  const live = useRef<LiveConnection | null>(null);
  const startedAt = useRef<number | null>(null);

  // ── connect to the agent ───────────────────────────────────────────
  useEffect(() => {
    let connection: LiveConnection | null = null;
    void (async () => {
      await connectToShell();
      connection = new LiveConnection({
        onSession: setSession,
        onRefused: setRefused,
        onSync: setSync,
        onConnection: setConnected,
        onTelemetry: (frame) => {
          setTelemetry(frame);
          if (startedAt.current === null) startedAt.current = frame.at;
          setHistory((previous) => {
            const next = [...previous, {
              t: frame.at - (startedAt.current ?? frame.at),
              values: frame.values,
              height_m: frame.height_m,
            }];
            return next.length > HISTORY_LIMIT ? next.slice(-HISTORY_LIMIT) : next;
          });
        },
      });
      connection.open();
      live.current = connection;
    })();
    return () => connection?.close();
  }, []);

  /** Run a command, showing its refusal verbatim if it declines. */
  const run = useCallback(async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof AgentError ? e.message : "Something went wrong.");
    }
  }, []);

  const flying = session?.activity === "manual" || session?.activity === "program";
  const manualFlying = session?.activity === "manual";

  // ── keyboard: key *state*, not the OS repeat stream ────────────────
  useEffect(() => {
    const onDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      // Space does nothing — including activating a focused button, which is
      // how it could otherwise stop the motors by accident (WebKit activates
      // on keyup, so that is blocked below too).
      if (event.code === "Space") {
        event.preventDefault();
        return;
      }
      if (event.code === "KeyL") {
        event.preventDefault();
        void run(api.land);
        return;
      }
      if (event.repeat || !manualFlying) return;

      const field = KEY_MAP[event.code];
      if (!field) return;
      event.preventDefault();
      setIntent((current) => {
        if (current[field]) return current;
        const next = { ...current, [field]: true };
        live.current?.sendIntent(next);
        return next;
      });
    };

    const onUp = (event: KeyboardEvent) => {
      if (event.code === "Space") {
        event.preventDefault();
        return;
      }
      const field = KEY_MAP[event.code];
      if (!field) return;
      event.preventDefault();
      setIntent((current) => {
        if (!current[field]) return current;
        const next = { ...current, [field]: false };
        live.current?.sendIntent(next);
        return next;
      });
    };

    // A window that loses focus never sees keyup. Releasing everything is the
    // safe reading: the drone holds its height instead of drifting on.
    const onBlur = () => {
      setIntent((current) => {
        if (!Object.values(current).some(Boolean)) return current;
        live.current?.sendIntent(EMPTY_INTENT);
        return EMPTY_INTENT;
      });
    };

    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
      window.removeEventListener("blur", onBlur);
    };
  }, [manualFlying, run]);

  // Nothing is known yet: the agent has not answered, or it is still trying the
  // saved sign-in. Hold the shape rather than claim "signed out".
  const starting = session === null || session.restoring;
  const inSession = session != null &&
    !["signed_out", "idle"].includes(session.state);
  // History reloads whenever a session starts or ends.
  const historyKey = `${session?.session_id ?? "none"}:${session?.state ?? ""}`;
  // The Auto/Manual toggle also chooses which history every page shows.
  const viewMode: Mode = session?.mode ?? "auto";

  const pages: { key: Page; label: string }[] = useMemo(
    () => [{ key: "home", label: "Home" },
           { key: "control", label: "Control" },
           { key: "sessions", label: "Sessions" },
           ...WINDOWS.map((w) => ({ key: w.key as Page, label: w.label }))],
    [],
  );

  return (
    <div className="flex h-screen flex-col bg-[var(--background)] text-[var(--foreground)]">
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div className={`${CONTAINER} flex flex-wrap items-center gap-x-5 gap-y-3 py-3`}>
          <button
            type="button"
            onClick={() => setPage("home")}
            aria-label="CropWatcher — go to Home"
            className="font-display min-h-10 rounded-md text-xl font-semibold"
          >
            CropWatcher
          </button>

          {/* Auto / Manual — the toggle that changes what Control shows.
              Locked while a flight is running: switching mid-air would hand the
              drone to a different controller without warning. */}
          <div role="group" aria-label="Flight mode" className="flex rounded-lg border border-[var(--border)] p-0.5">
            {(["auto", "manual"] as Mode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-pressed={session?.mode === mode}
                disabled={starting || session?.state === "busy"}
                title={session?.state === "busy" ? "Finish the current flight first" : undefined}
                onClick={() => void run(() => api.setMode(mode))}
                className={`min-h-9 rounded-md px-4 text-sm font-medium capitalize disabled:opacity-50 ${
                  session?.mode === mode
                    ? "bg-[var(--primary)] text-[var(--on-primary)]"
                    : "text-[var(--muted)]"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>

          <nav aria-label="Pages" className="flex flex-wrap gap-1">
            {pages.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-current={page === item.key ? "page" : undefined}
                onClick={() => setPage(item.key)}
                className={`min-h-9 rounded-md px-3 text-sm ${
                  page === item.key
                    ? "bg-[var(--surface-2)] font-medium text-[var(--heading)] shadow-[inset_0_-2px_0_var(--primary)]"
                    : "text-[var(--muted)]"
                }`}
              >
                {item.label}
              </button>
            ))}
          </nav>

          {/* The right cluster wraps rather than pushing the window into a
              horizontal scroll: at the 720 px minimum width an email address
              and two buttons do not fit beside the pages. */}
          <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-3 text-sm">
            <SyncBadge sync={sync} connected={connected} />
            {flying && (
              <>
                <Button onClick={() => void run(api.land)} title="Land gracefully (L)">
                  Land <kbd className="rounded border border-[var(--border)] px-1 text-xs">L</kbd>
                </Button>
                <HoldToStop onStop={() => void run(api.emergencyStop)} />
              </>
            )}
            {inSession && !flying && session?.state !== "ending" && (
              <Button variant="danger" onClick={() => void run(api.endSession)} title="Land if needed, save and upload, then disconnect">
                End session
              </Button>
            )}
            <ProfileMenu
              session={session}
              onSignIn={() => setPage("home")}
              onSignOut={() => void run(api.signOut)}
            />
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className={`${CONTAINER} grid gap-6 py-8`}>
          {!connected && (
            <Message tone="critical" text="Not connected to the flight agent on this computer." />
          )}
          {error && <Message tone="critical" text={error} />}

          {refused ? (
            <Message tone="critical" text={refused} />
          ) : starting ? (
            <StartupPage connected={connected} />
          ) : page === "home" ? (
            <HomePage
              session={session}
              telemetry={telemetry}
              sync={sync}
              connected={connected}
              run={run}
              onGo={setPage}
            />
          ) : page === "control" ? (
            <ControlPage
              session={session}
              telemetry={telemetry}
              intent={intent}
              flying={Boolean(flying)}
              run={run}
              historyKey={historyKey}
              onOpenSession={(id) => { setPageState("sessions"); setSessionId(id); }}
              onOpenSessions={() => setPage("sessions")}
            />
          ) : page === "sessions" ? (
            <SessionsPage refreshKey={historyKey} mode={viewMode} selectedId={sessionId} onSelect={setSessionId} />
          ) : logWindow === page ? (
            <WindowLog windowKey={page} refreshKey={historyKey} mode={viewMode} onBack={() => setLogWindow(null)} />
          ) : (
            <SensorWindow
              windowKey={page}
              telemetry={telemetry}
              history={history}
              session={session}
              onOpenLog={() => setLogWindow(page)}
            />
          )}
        </div>
      </main>
    </div>
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
      className="relative min-h-11 overflow-hidden rounded-lg border-2 border-[var(--status-critical)] px-4 text-sm font-bold text-[var(--status-critical)]"
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
