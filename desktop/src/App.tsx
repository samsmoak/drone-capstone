/**
 * The CropWatcher window.
 *
 * A left sidebar for navigation, a strip across the top for flight state and
 * stopping, then one page at a time: Home (where you are and what to do next),
 * Control (what you do), and the live sensor windows (what the drone reports).
 * Home opens first — an operator who has just installed this needs the next
 * step, not eight tabs.
 *
 * The shell is copy-adapted from the web app's operator view, so the two read
 * as one product. The split between the two surfaces is not cosmetic:
 *
 * - **The sidebar navigates.** Pages, the Auto/Manual mode, the account.
 * - **The strip stops things.** Land, Emergency stop, End session, the sync
 *   state. A nav rail scrolls; an abort control must never be scrollable out
 *   of reach, which is why these two are separate surfaces.
 *
 * Two controls are always present while a session is running, because the
 * moment you need them is the moment something is going wrong:
 *
 * - **Land** — the normal way to end a flight, and the keyboard's `L`.
 * - **Emergency stop** — hold for a second. No keyboard shortcut: cutting the
 *   motors in the air drops the drone, so it must be deliberate.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AgentError,
  EMPTY_INTENT,
  LiveConnection,
  api,
  connectToShell,
  type Intent,
  type Mode,
  type CameraWifi,
  type Session,
  type SyncStatus,
  type Telemetry,
} from "@/lib/agent";
import { useCommandLog, useSessionNarration } from "@/lib/commandLog";
import { ControlPage } from "@/pages/control/ControlPage";
import { HomePage } from "@/pages/home/HomePage";
import { FlightStrip } from "@/components/FlightStrip";
import { Sidebar } from "@/components/Sidebar";
import { SessionsPage } from "@/pages/sessions/SessionsPage";
import { WindowLog } from "@/pages/sessions/WindowLog";
import { StartupPage } from "@/pages/startup/StartupPage";
import { SensorWindow, type WindowKey } from "@/pages/windows/SensorWindow";
import { Message } from "@/components/ui";
import { DroneWifiDialog } from "@/components/DroneWifiDialog";
import { PHASE_LABEL, PHASE_TONE, SHOW_DRONE_WIFI, droneWifi } from "@/lib/droneWifi";
import { WifiPage } from "@/pages/wifi/WifiPage";

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

export const HISTORY_S = 60;
const HISTORY_LIMIT = HISTORY_S * 10;      // 10 Hz

export type History = { t: number; values: Record<string, number>; height_m: number | null }[];

export type Page = "home" | "control" | "sessions" | "wifi" | WindowKey;

/** A command, and what to call it in the log. */
export type Run = (action: () => Promise<unknown>, label?: string) => Promise<void>;

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
  // Drone Wi-Fi: the agent's live account of the deck joining, and the dialog.
  const [cameraWifi, setCameraWifi] = useState<CameraWifi | null>(null);
  const [wifiOpen, setWifiOpen] = useState(false);
  // Asked at most once per launch: "Not now" means not now, not every reconnect.
  const wifiAsked = useRef(false);

  const live = useRef<LiveConnection | null>(null);
  const startedAt = useRef<number | null>(null);

  // What the window did and what the agent said back. Observation only — see
  // lib/commandLog.ts. It is not the agent's audit trail.
  const { lines: logLines, push: pushLog, clear: clearLog } = useCommandLog();
  useSessionNarration(session, connected, pushLog);

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
        onCameraWifi: setCameraWifi,
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

  // The agent holds the drone's network in memory only, so it is re-sent every
  // time the window (re)connects to it — a restarted agent would otherwise
  // leave the deck on its own access point. With nothing saved, the operator is
  // asked once after signing in.
  const signedIn = Boolean(session?.operator);
  useEffect(() => {
    if (!connected || !signedIn) return;
    let cancelled = false;
    droneWifi.push()
      .then((state) => {
        if (cancelled) return;
        if (state) setCameraWifi(state);
        else if (!wifiAsked.current) {
          wifiAsked.current = true;
          setWifiOpen(true);
        }
      })
      .catch((e) => { if (!cancelled) pushLog("refused", "Drone Wi-Fi not sent", String(e)); });
    return () => { cancelled = true; };
  }, [connected, signedIn, pushLog]);

  // "Change Wi-Fi" from the Camera tab and the account menu lands on the page.
  useEffect(() => {
    const show = () => setPage("wifi");
    window.addEventListener(SHOW_DRONE_WIFI, show);
    return () => window.removeEventListener(SHOW_DRONE_WIFI, show);
  }, [setPage]);

  const wifiPhase = cameraWifi?.phase ?? "not-set";
  const wifiBadge = {
    tone: PHASE_TONE[wifiPhase],
    label: cameraWifi?.ssid ? `${cameraWifi.ssid} — ${PHASE_LABEL[wifiPhase]}` : PHASE_LABEL[wifiPhase],
  };

  const closeWifi = useCallback(() => setWifiOpen(false), []);

  // Vitals are only true while the radio is up. Without this the last frame
  // stayed on every sensor page marked "Live" after the drone switched off —
  // the same stale claim the Wi-Fi page made about a join (2026-09-24).
  const radioState = session?.radio?.state;
  useEffect(() => {
    if (radioState !== undefined && radioState !== "connected") setTelemetry(null);
  }, [radioState]);

  /**
   * Run a command, showing its refusal verbatim if it declines.
   *
   * `label` is optional and only used for the console: adding it changed no
   * call site, and the error path below is exactly as it was.
   */
  const run = useCallback<Run>(async (action, label) => {
    setError(null);
    if (label) pushLog("command", label);
    try {
      await action();
      if (label) pushLog("ok", `${label} accepted`);
    } catch (e) {
      const message = e instanceof AgentError ? e.message : "Something went wrong.";
      setError(message);
      pushLog("refused", label ? `${label} refused` : "Command refused", message);
    }
  }, [pushLog]);

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
        void run(api.land, "Land (L)");
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
  // The Auto/Manual toggle also chooses which history every page shows. The
  // fallback matches the AGENT's own default (session.py) so the filter does
  // not flip under the operator when the first frame lands.
  const viewMode: Mode = session?.mode ?? "manual";

  return (
    <div className="flex h-screen bg-[var(--background)] text-[var(--foreground)]">
      {wifiOpen && (
        <DroneWifiDialog onClose={closeWifi} onSaved={setCameraWifi} />
      )}
      <Sidebar
        page={page}
        onNavigate={setPage}
        session={session}
        starting={starting}
        // Hover-to-expand is suppressed while flying: expanded, the rail covers
        // the Control page's console, which is what the operator is watching.
        flying={Boolean(flying)}
        onSetMode={(mode) => void run(() => api.setMode(mode), `Set mode to ${mode}`)}
        onSignOut={() => void run(api.signOut, "Sign out")}
        badges={signedIn ? { wifi: wifiBadge } : {}}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <FlightStrip
          session={session}
          sync={sync}
          connected={connected}
          flying={Boolean(flying)}
          inSession={inSession}
          onLand={() => void run(api.land, "Land")}
          onStop={() => void run(api.emergencyStop, "Emergency stop")}
          onEndSession={() => void run(api.endSession, "End session")}
        />

        {(!connected || error) && (
          <div className="grid gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-2">
            {!connected && (
              <Message tone="critical" text="Not connected to the flight agent on this computer." />
            )}
            {error && <Message tone="critical" text={error} />}
          </div>
        )}

        <main className="console-scroll min-w-0 flex-1 overflow-y-auto">
          <div className="grid gap-5 px-4 py-5">
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
                history={history}
                intent={intent}
                flying={Boolean(flying)}
                run={run}
                logLines={logLines}
                onClearLog={clearLog}
                onOpenSessions={() => setPage("sessions")}
              />
            ) : page === "wifi" ? (
              <WifiPage wifi={cameraWifi} session={session} onSaved={setCameraWifi} />
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
    </div>
  );
}
