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
import type { History } from "@/App";
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
  prop_test: { ok: false, failed: [2, 3] },
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
if (agentToken) {
  (window as unknown as { __TAURI_INTERNALS__: unknown }).__TAURI_INTERNALS__ = {
    invoke: async (command: string) =>
      command === "agent_port" ? Number(query.get("port") ?? 8765)
        : command === "agent_token" ? agentToken
          : null,
  };
  await connectToShell();
}

createRoot(document.getElementById("root")!).render(
  <div className="mx-auto grid w-full max-w-6xl gap-6 bg-[var(--background)] px-6 py-8 text-[var(--foreground)]">
    <StartupPage connected={false} />
    <HomePage session={session} telemetry={telemetry} sync={null} connected run={noop} onGo={() => {}} />
    <ControlPage session={{ ...session, state: "awaiting_confirmation" }} telemetry={telemetry} intent={EMPTY_INTENT} flying={false} run={noop} historyKey="h" onOpenSession={() => {}} onOpenSessions={() => {}} />
    <ControlPage
      session={{ ...session, state: "ready", mode: "manual" }}
      telemetry={telemetry} intent={EMPTY_INTENT} flying={false} run={noop}
      historyKey="h" onOpenSession={() => {}} onOpenSessions={() => {}}
    />
    {WINDOWS.map((w) => (
      <SensorWindow key={w.key} windowKey={w.key} telemetry={telemetry} history={history} session={session} onOpenLog={() => {}} />
    ))}
    {agentToken && (
      <>
        <WindowLog windowKey="flight" refreshKey="h" mode={(query.get("mode") as "auto" | "manual") ?? "manual"} onBack={() => {}} />
        <SessionsPage refreshKey="h" mode={(query.get("mode") as "auto" | "manual") ?? "manual"} selectedId={query.get("session")} onSelect={() => {}} />
      </>
    )}
  </div>,
);
