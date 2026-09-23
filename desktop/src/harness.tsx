/**
 * Layout harness — renders the real pages with worst-case data, in a browser.
 *
 * The app itself cannot be measured in a browser: it reaches the agent through
 * Tauri's `invoke`, which does not exist outside the window. This mounts the
 * same components with the longest values they will ever be handed (a full
 * email address, a hardware id, a failed check with a long reason) so overflow
 * can be measured at the window's minimum width instead of guessed at.
 *
 * Not shipped: `vite build` only builds index.html.
 */

import { createRoot } from "react-dom/client";
import { HomePage } from "@/pages/home/HomePage";
import { ControlPage } from "@/pages/control/ControlPage";
import { SensorWindow, WINDOWS } from "@/pages/windows/SensorWindow";
import { WindowLog } from "@/pages/sessions/WindowLog";
import { SessionsPage } from "@/pages/sessions/SessionsPage";
import { StartupPage } from "@/pages/startup/StartupPage";
import { EMPTY_INTENT, connectToShell, type Session, type Telemetry } from "@/lib/agent";
import type { LogLine } from "@/lib/commandLog";
import { FlightStrip } from "@/components/FlightStrip";
import { Sidebar } from "@/components/Sidebar";
import type { History } from "@/App";
import { reportInto } from "@/measure";
import "./styles.css";

const session: Session = {
  state: "checks_failed",
  mode: "auto",
  operator: { id: "a0afd4e8", email: "zebachsmoak@gmail.com", name: null },
  drone: { hardware_id: "cf-4a3b2c1d0e9f8a7b", battery_v: 3.82, endurance_s: 420 },
  session_id: "3f1c",
  activity: null,
  checks: [
    { key: "radio", label: "Radio", status: "passed", detail: "cf-4a3b2c1d0e9f8a7b answered", data: {} },
    { key: "battery", label: "Battery", status: "passed", detail: "3.82 V — the drone reports it can fly", data: {} },
    {
      key: "positioning", label: "Positioning", status: "failed",
      data: {},
      detail: "Only 0 of 4 base stations are being received. Stored geometry is not signal — re-run geometry estimation in cfclient before flying.",
    },
  ],
  health_test: {
    ok: false,
    motors: { passed: [1, 4], failed: [2, 3], ok: false },
    battery: { sag_v: 0.61, passed: false, idle_vbat: 4.12, pwm_ratio: 0 },
    battery_error: null,
  },
  retry_required: false,
  flight: null,
  message: "The checks did not pass, so the drone will not arm.",
  can_fly: false,
  restoring: false,
  assisted: false,
  unassisted_reason: "No base station signal is reaching the drone. Check both base stations are on (front LED solid green), the drone is upright, and nothing blocks the line of sight.",
};

const values: Record<string, number> = {
  "stateEstimate.x": 0.12, "stateEstimate.y": -0.34, "stateEstimate.z": 0.31,
  "stateEstimate.vx": 0.02, "stateEstimate.vy": -0.01, "stateEstimate.vz": 0.0,
  "stabilizer.roll": 1.2, "stabilizer.pitch": -0.8, "stabilizer.yaw": 178.4,
  "stabilizer.thrust": 38412, "supervisor.info": 0,
  "pm.vbat": 3.82, "pm.state": 0, "sys.canfly": 1,
  "motor.m1": 38000, "motor.m2": 38210, "motor.m3": 37980, "motor.m4": 38110,
  "baro.temp": 28.6, "baro.pressure": 1013.2,
  "acc.x": 0.01, "acc.y": -0.02, "acc.z": 1.0,
  "gyro.x": 0.4, "gyro.y": -0.3, "gyro.z": 0.1,
  "lighthouse.bsReceive": 0b1111, "lighthouse.bsActive": 0b1111,
  "lighthouse.bsCalVal": 0b0011, "lighthouse.bsGeoVal": 0b0001,
  "lighthouse.bsAvailable": 0b1111,
  "kalman.varPX": 0.004, "kalman.varPY": 0.003, "kalman.varPZ": 0.001,
};
const telemetry: Telemetry = { values, height_m: 0.31, at: 0 };
const history: History = Array.from({ length: 120 }, (_, i) => ({
  t: i / 10, values, height_m: 0.3 + Math.sin(i / 8) * 0.02,
}));

const noop = async () => {};

/**
 * `?agent=<token>` measures the session views against the agent already running
 * on this machine, by standing in for the Tauri bridge the browser lacks. The
 * token is per-launch and never stored here; without the parameter the harness
 * renders the static pages exactly as before.
 */
const query = new URLSearchParams(location.search);
const agentToken = query.get("agent");

// `?theme=dark|light` pins the tokens, so both themes get measured rather than
// whichever one this machine happens to be set to.
const theme = query.get("theme");
if (theme === "dark" || theme === "light") document.documentElement.dataset.theme = theme;
if (agentToken) {
  (window as unknown as { __TAURI_INTERNALS__: unknown }).__TAURI_INTERNALS__ = {
    invoke: async (command: string) =>
      command === "agent_port" ? Number(query.get("port") ?? 8765)
        : command === "agent_token" ? agentToken
          : null,
  };
  await connectToShell();
}

/**
 * The console's worst case: the longest refusal the agent actually sends, a
 * check detail that wraps, and enough lines to make the pane scroll.
 */
const logLines: LogLine[] = [
  { id: 1, at: Date.now() - 42000, kind: "link", text: "Flight agent connected" },
  { id: 2, at: Date.now() - 38000, kind: "command", text: "Start session" },
  { id: 3, at: Date.now() - 37000, kind: "state", text: "idle → starting" },
  { id: 4, at: Date.now() - 36000, kind: "ok", text: "Radio: passed", detail: "cf-4a3b2c1d0e9f8a7b answered" },
  { id: 5, at: Date.now() - 35000, kind: "ok", text: "Battery: passed", detail: "3.82 V — the drone reports it can fly" },
  {
    id: 6, at: Date.now() - 34000, kind: "refused", text: "Positioning: failed",
    detail: "Only 0 of 4 base stations are being received. Stored geometry is not signal — re-run geometry estimation in cfclient before flying.",
  },
  { id: 7, at: Date.now() - 33000, kind: "state", text: "starting → checks_failed" },
  { id: 8, at: Date.now() - 20000, kind: "command", text: "Battery & motor test" },
  { id: 9, at: Date.now() - 12000, kind: "refused", text: "Battery & motor test: did not pass", detail: "Motors 2, 3 failed" },
  { id: 10, at: Date.now() - 4000, kind: "flight", text: "takeoff", detail: "rising to 0.30 m above the captured ground" },
];

/**
 * Every page is measured inside the REAL shell now — sidebar, flight strip and
 * all. Measuring a page on its own was fine when the chrome was a single bar;
 * with a 15rem rail taken out of the width it would measure a window nobody
 * runs.
 */
function Shell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="border-b-4 border-[var(--primary)]">
      <p className="bg-[var(--primary)] px-3 py-1 text-xs font-bold text-[var(--on-primary)]">{label}</p>
      <div className="flex h-[900px] bg-[var(--background)] text-[var(--foreground)]">
        <Sidebar
          page="control"
          onNavigate={() => {}}
          session={session}
          starting={false}
          onSetMode={() => {}}
          onSignOut={() => {}}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <FlightStrip
            session={session}
            sync={{ pending_flights: 2, pending_events: 5, uploading: null, last_error: null, everything_sent: false }}
            connected
            flying={false}
            inSession
            onLand={() => {}}
            onStop={() => {}}
            onEndSession={() => {}}
          />
          <main className="console-scroll min-w-0 flex-1 overflow-y-auto">
            <div className="grid gap-5 px-4 py-5">{children}</div>
          </main>
        </div>
      </div>
    </section>
  );
}

const control = (label: string, override: Partial<Session>) => (
  <Shell label={label}>
    <ControlPage
      session={{ ...session, ...override }}
      telemetry={telemetry}
      history={history}
      intent={{ ...EMPTY_INTENT, up: true, yaw_left: true }}
      flying={false}
      run={noop}
      logLines={logLines}
      onClearLog={() => {}}
      historyKey="h"
      onOpenSession={() => {}}
      onOpenSessions={() => {}}
    />
  </Shell>
);

createRoot(document.getElementById("root")!).render(
  <div className="bg-[var(--background)] text-[var(--foreground)]">
    <Shell label="Startup"><StartupPage connected={false} /></Shell>
    <Shell label="Home">
      <HomePage session={session} telemetry={telemetry} sync={null} connected run={noop} onGo={() => {}} />
    </Shell>
    {control("Control · awaiting confirmation", { state: "awaiting_confirmation" })}
    {control("Control · retry required", {
      state: "ready", retry_required: true,
      message: "The drone reports it has tumbled — motors stopped. The flight ended early — press Retry to check the drone again before flying.",
    })}
    {control("Control · Auto, ready", { state: "ready", mode: "auto", assisted: true, message: null })}
    {control("Control · Manual, armed", {
      state: "busy", mode: "manual", activity: "manual", assisted: true, message: null,
    })}
    {WINDOWS.map((w) => (
      <Shell key={w.key} label={`Window · ${w.label}`}>
        <SensorWindow windowKey={w.key} telemetry={telemetry} history={history} session={session} onOpenLog={() => {}} />
      </Shell>
    ))}
    {agentToken && (
      <>
        <Shell label="Window log · Flight">
          <WindowLog windowKey="flight" refreshKey="h" mode={(query.get("mode") as "auto" | "manual") ?? "manual"} onBack={() => {}} />
        </Shell>
        <Shell label="Sessions">
          <SessionsPage refreshKey="h" mode={(query.get("mode") as "auto" | "manual") ?? "manual"} selectedId={query.get("session")} onSelect={() => {}} />
        </Shell>
      </>
    )}
  </div>,
);

// `?measure=1` walks the rendered DOM for anything crossing the viewport and
// writes the verdict into the page, where --dump-dom can read it. Two frames,
// so React has committed and the canvas has had its first ResizeObserver pass.
if (query.has("measure")) {
  requestAnimationFrame(() => requestAnimationFrame(() => reportInto("measure-report")));
}
