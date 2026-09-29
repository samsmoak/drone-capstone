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
import type { FlowStart } from "@/pages/control/auto/MissionFlow";
import type { Run } from "@/App";
import { SensorWindow, WINDOWS } from "@/pages/windows/SensorWindow";
import { WindowLog } from "@/pages/sessions/WindowLog";
import { SessionsPage } from "@/pages/sessions/SessionsPage";
import { StartupPage } from "@/pages/startup/StartupPage";
import {
  EMPTY_INTENT, connectToShell,
  type MissionView, type PlanLimits, type RoomView, type Session, type Telemetry,
} from "@/lib/agent";
import type { LogLine } from "@/lib/commandLog";
import { FlightStrip } from "@/components/FlightStrip";
import { Sidebar } from "@/components/Sidebar";
import type { History } from "@/App";
import { reportInto } from "@/measure";
import "./styles.css";

const session: Session = {
  state: "checks_failed",
  mode: "manual",
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
  radio: { state: "connected", hardware_id: "cf-002f002a3334471239333335", message: null },
  mission: null,
  processing: {
    on: true, chosen: false, last_flight_id: "f1c2d3e4-flight",
    jobs: [{ flight_id: "f1c2d3e4-flight", state: "done", queued_at: "2026-09-29T10:00:00+00:00",
             finished_at: "2026-09-29T10:00:02+00:00", error: null }],
  },
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
 * The Control page's actions really run, against the fake fetch below — so
 * Save in the mission editor saves and goes back to the list. Anything the
 * fake does not answer fails quietly, as a refused command would.
 */
const runHere: Run = async (action, label) => {
  try { await action(); } catch (e) { console.warn(`harness: ${label ?? "action"} failed`, e); }
};

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
// `?map=2d|3d` pins the room map's view (RoomMap remembers it per machine).
const mapView = query.get("map");
if (mapView === "2d" || mapView === "3d") {
  try { localStorage.setItem("cropwatcher.auto.mapView", mapView); } catch { /* private window */ }
}
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
 * The Auto page's plans, served in place of the agent when no agent is given.
 *
 * Worst case on purpose: a long room and mission name, every obstacle kind, a
 * label that wraps, and one leg the agent flags — so the editor, the list and
 * the problem panel are measured with the most they will ever show. Only the
 * plan routes are answered here; everything else goes to the real fetch.
 */
const sampleLimits: PlanLimits = {
  outer: { vertices: [[-2, -2], [2, -2], [2, 2], [-2, 2]], measured: false },
  default_clearance_m: 0.25, min_hold_s: 5, z_min_m: 0.1, z_max_m: 1.0,
  move_speed_m_s: 0.2, climb_rate_m_s: 0.15,
};
const sampleRoom: RoomView = {
  format: 1, id: "lab", name: "Engineering lab, north bay (bench row B and the pump skid)",
  geofence: { shape: "rectangle", vertices: [[-1.7, -1.5], [1.7, -1.5], [1.7, 1.5], [-1.7, 1.5]], z_min: 0.1, z_max: 1.0 },
  obstacles: [
    { id: "bench", kind: "rectangle", label: "Bench", points: [[-0.4, -0.3], [0.4, 0.3]], height_m: 0.9 },
    { id: "pillar", kind: "circle", label: "Pillar", points: [[1.1, -0.9]], radius: 0.2, height_m: null },
    { id: "rail", kind: "line", label: "Guard rail", points: [[-1.4, 1.1], [-0.4, 1.1]], height_m: 1.1 },
  ],
  coverage: null, clearance_m: 0.25, revision: 3,
  created_at: "2026-09-28T10:00:00+00:00", updated_at: "2026-09-28T11:30:00+00:00",
  outer: sampleLimits.outer,
  problems: [{ code: "coverage_not_measured", severity: "warning", where: null,
    message: "This room's Lighthouse coverage has not been measured, so the fence is checked against the agent's default flying area instead. Measure it before trusting the edges of the room." }],
  valid: true,
};
const sampleMission: MissionView = {
  format: 1, id: "m-long", name: "Weekly thermal sweep of pumps, valves and the compressor manifold",
  room_id: "lab", home: [-1.2, -1.0],
  points: [
    { id: "P1", label: "Pump 1 bearing housing", x_m: -1.2, y_m: 0.6, z_m: 0.4, hold_s: 6 },
    { id: "P2", label: "Pump 2", x_m: 0.9, y_m: 0.7, z_m: 0.5, hold_s: 5 },
    { id: "P3", label: "Compressor manifold, upper flange", x_m: 1.2, y_m: 0.0, z_m: 0.6, hold_s: 8 },
    { id: "P4", label: null, x_m: 0.0, y_m: -1.0, z_m: 0.4, hold_s: 5 },
  ],
  cruise_height_m: 0.4, return_to_start: false, end_point_id: "P3", revision: 2, flown_revision: 1,
  created_at: "2026-09-27T09:00:00+00:00", updated_at: "2026-09-28T11:31:00+00:00",
  problems: [
    sampleRoom.problems[0],
    { code: "leg_near_obstacle", severity: "error", where: "P2 → P3", message: "The leg P2 → P3 passes 0.12 m from obstacle Pillar; it needs 0.25 m." },
  ],
  valid: false, path_length_m: 8.4, estimated_duration_s: 96,
};
const sessionShown = session;
const sampleMissions: MissionView[] = [
  sampleMission,
  { ...sampleMission, id: "m-ok", name: "Pump check", points: sampleMission.points.slice(0, 2),
    problems: [sampleRoom.problems[0]], valid: true, flown_revision: null, estimated_duration_s: 41 },
];
if (!agentToken) {
  const realFetch = window.fetch.bind(window);
  const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  // Saving is kept for the page's life, so Save → the list can be checked:
  // the saved mission comes back with its revision bumped, as the agent does.
  const rooms: RoomView[] = [sampleRoom];
  const missions: MissionView[] = [...sampleMissions];
  const upsert = <T extends { id: string }>(list: T[], item: T) => {
    const at = list.findIndex((x) => x.id === item.id);
    if (at < 0) list.push(item); else list[at] = item;
    return item;
  };
  window.fetch = async (input, init) => {
    const path = new URL(String(input), location.href).pathname;
    const post = init?.method === "POST";
    const body = post && typeof init?.body === "string" ? JSON.parse(init.body) : null;
    if (path === "/plan/limits") return json(sampleLimits);
    if (path === "/rooms" && body) return json(upsert(rooms, { ...sampleRoom, ...body }));
    if (path === "/rooms") return json(rooms);
    if (path.startsWith("/rooms/")) return json(rooms.find((r) => path.endsWith(r.id)) ?? sampleRoom);
    if (path === "/missions" && body) {
      const before = missions.find((m) => m.id === body.id);
      return json(upsert(missions, { ...sampleMission, problems: [], valid: true, ...body,
        revision: (before?.revision ?? 0) + 1, flown_revision: before?.flown_revision ?? null,
        updated_at: new Date().toISOString() }));
    }
    if (path === "/missions") return json(missions);
    if (path === "/missions/validate") return json(sampleMission);
    if (path.endsWith("/from-drone")) {
      return json({ position: [values["stateEstimate.x"], values["stateEstimate.y"]],
                    mission: { ...sampleMission, home: [values["stateEstimate.x"], values["stateEstimate.y"]] } });
    }
    if (path.startsWith("/flights/") && path.endsWith("/result")) {
      return json({
        flight_id: "f1c2d3e4-flight", job: sessionShown.processing.jobs[0],
        result: {
          flight_id: "f1c2d3e4-flight", pipeline_version: "0.1.0", stages: { clean: "stub", classify: "stub" },
          created_at: "2026-09-29T10:00:02+00:00", failures: [],
          points: ["P1", "P2", "P3"].map((id) => ({ point_id: id, verdict: "insufficient_data",
            reasons: ["No model gave a verdict: no classifier yet."], alerts: [] })),
          summary: { P1: { readings: 60, frames: 22 }, P2: { readings: 52, frames: 18 }, P3: { readings: 81, frames: 30 } },
        },
      });
    }
    if (path.startsWith("/missions/")) return json(missions.find((m) => path.endsWith(m.id)) ?? sampleMission);
    return realFetch(input, init);
  };
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
/**
 * `?only=<substring>` renders just the sections whose label matches.
 *
 * The harness stacks every page, so a screenshot captures whichever one happens
 * to be at the top. Isolating a section is how a canvas — the Scene tab, which
 * the DOM measurement cannot see into — gets looked at at all.
 */
const only = query.get("only")?.toLowerCase();

function Shell({ label, children }: { label: string; children: React.ReactNode }) {
  if (only && !label.toLowerCase().includes(only)) return null;
  return (
    <section className="border-b-4 border-[var(--primary)]">
      <p className="bg-[var(--primary)] px-3 py-1 text-xs font-bold text-[var(--on-primary)]">{label}</p>
      <div className="flex h-[900px] bg-[var(--background)] text-[var(--foreground)]">
        <Sidebar
          page="control"
          onNavigate={() => {}}
          session={session}
          starting={false}
          flying={false}
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

const control = (label: string, override: Partial<Session>, autoStart?: FlowStart) => (
  <Shell label={label}>
    <ControlPage
      autoStart={autoStart}
      session={{ ...session, ...override }}
      telemetry={telemetry}
      history={history}
      intent={{ ...EMPTY_INTENT, up: true, yaw_left: true }}
      flying={false}
      run={runHere}
      logLines={logLines}
      onClearLog={() => {}}
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
    {control("Control · Auto, ready", { state: "ready", mode: "manual", assisted: true, message: null })}
    {control("Auto · ① Mission list", { state: "idle", mode: "auto", assisted: true, message: null, checks: [], health_test: null })}
    {control("Auto · ① Mission editor", { state: "idle", mode: "auto", assisted: true, message: null, checks: [], health_test: null },
             { step: 1, missionId: "m-long", view: "edit" })}
    {control("Auto · ② Check", { state: "awaiting_confirmation", mode: "auto", assisted: true, message: null },
             { step: 2, missionId: "m-long" })}
    {control("Auto · ③ Fly, flying", {
      state: "busy", mode: "auto", activity: "mission", assisted: true, message: "Holding at P2",
      mission: {
        id: "m-long", name: sampleMission.name, revision: 2, room_id: "lab", points: ["P1", "P2", "P3", "P4"],
        state: "holding", current_point_id: "P2", completed_point_ids: ["P1"],
        last_event: { kind: "hold_started", at_s: 31.2, point_id: "P2", detail: "Holding at P2 for 5 s — 4 cm off the point" },
      },
    }, { step: 3, missionId: "m-long" })}
    {control("Auto · ③ Fly, landed", {
      state: "ready", mode: "auto", activity: null, assisted: true, message: null,
      mission: {
        id: "m-long", name: sampleMission.name, revision: 2, room_id: "lab", points: ["P1", "P2", "P3"],
        state: "done", current_point_id: null, completed_point_ids: ["P1", "P2", "P3"],
        last_event: { kind: "done", at_s: 88.0, point_id: null, detail: "Mission complete" },
      },
    }, { step: 3, missionId: "m-long" })}
    {control("Auto · full screen editor", { state: "idle", mode: "auto", assisted: true, message: null, checks: [], health_test: null },
             { step: 1, missionId: "m-long", view: "edit", full: true })}
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
