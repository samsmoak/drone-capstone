/**
 * Talking to the flight agent running on this computer.
 *
 * The contract is the agent's own, from `backend/agent/cropwatcher/api/rest.py`:
 * REST for commands, one WebSocket for everything live. Every command carries
 * the control token, which the Tauri shell hands us — a page on the internet
 * cannot know it, so it cannot fly the drone.
 *
 * **This file never generates a setpoint stream.** It reports which keys are
 * held and pings ~10 times a second; the agent runs the 50 Hz loop and lands
 * the drone by itself if this window goes quiet.
 */

import { invoke } from "@tauri-apps/api/core";

export type Mode = "auto" | "manual";

export type SessionState =
  | "signed_out" | "idle" | "starting" | "checks_failed"
  | "awaiting_confirmation" | "ready" | "busy" | "ending";

export type Check = {
  key: string;
  label: string;
  /** `warning` means flying is allowed with less help from the drone. */
  status: "running" | "passed" | "warning" | "failed";
  detail: string;
  data: Record<string, unknown>;
};

export type Session = {
  state: SessionState;
  mode: Mode;
  operator: { id: string; email: string; name: string | null; role?: string } | null;
  drone: { hardware_id: string; battery_v: number; endurance_s: number } | null;
  session_id: string | null;
  activity: string | null;
  checks: Check[];
  health_test: HealthTest | null;
  flight: { id: string; phase: string; detail: string } | null;
  message: string | null;
  can_fly: boolean;
  /** True until the agent has tried the saved sign-in. Show a loading state,
   *  never a sign-in form: "signed out" is not known to be true yet. */
  restoring: boolean;
  /** False when the drone has no usable position estimate: no height hold, no
   *  programs, and the position guards cannot run. */
  assisted: boolean;
  unassisted_reason: string | null;
  /** The last flight ended abnormally. Nothing flies until Retry has run every
   *  check again in this session — after a tumble the drone holds its motors. */
  retry_required: boolean;
};

/** The firmware's propeller test, then its battery test under load. */
export type HealthTest = {
  ok: boolean;
  motors: { passed: number[]; failed: number[]; ok: boolean };
  battery: {
    sag_v: number;
    passed: boolean;
    idle_vbat: number | null;
    /** What the drone reported for health.batTestPWMRatio; 0 = firmware default. */
    pwm_ratio: number | null;
  } | null;
  battery_error: string | null;
};

export type SyncStatus = {
  pending_flights: number;
  pending_events: number;
  uploading: string | null;
  last_error: string | null;
  everything_sent: boolean;
};

export type Telemetry = {
  values: Record<string, number>;
  height_m: number | null;
  at: number;
};

/** Held-key state. Mirrors `Intent` in the agent, field for field. */
/** What the agent says about the camera. See backend camera/source.py. */
export type CameraStatus = {
  live: boolean;
  /** "none" | "test-pattern" | the deck, once one exists. */
  kind: string;
  reason: string | null;
  /** The DRONE's own answer (deck.bcAI). null until a drone has been asked,
   *  which is not the same as "not fitted". */
  deck_fitted: boolean | null;
};

export type Intent = {
  up: boolean; down: boolean;
  forward: boolean; back: boolean;
  left: boolean; right: boolean;
  yaw_left: boolean; yaw_right: boolean;
};

export const EMPTY_INTENT: Intent = {
  up: false, down: false, forward: false, back: false,
  left: false, right: false, yaw_left: false, yaw_right: false,
};

export const HEARTBEAT_MS = 100;

let port = 8765;
let token = "";

export async function connectToShell(): Promise<void> {
  port = await invoke<number>("agent_port");
  token = await invoke<string>("agent_token");
}

const base = () => `http://127.0.0.1:${port}`;

export class AgentError extends Error {}

/**
 * The URL an <img> loads camera frames from.
 *
 * A bare URL rather than a fetch, because an <img> cannot send the control
 * token in a header — and the agent serves this route unauthenticated for that
 * reason: it is read-only, it commands nothing, and the agent binds localhost.
 * `stamp` defeats the cache so a live feed does not freeze on the first frame.
 */
export const cameraFrameUrl = (stamp: number) => `${base()}/camera/frame?t=${stamp}`;

async function command<T>(path: string, body?: unknown, method: "GET" | "POST" = "POST"): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base()}${path}`, {
      method,
      headers: { "Content-Type": "application/json", "X-Agent-Token": token },
      body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
    });
  } catch {
    throw new AgentError(
      "Could not reach the flight agent on this computer. Restart CropWatcher.",
    );
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    // The agent's refusals are written for the operator; show them verbatim.
    const detail = payload?.detail;
    throw new AgentError(
      typeof detail === "string" ? detail : "That did not work. See the agent log.",
    );
  }
  return payload as T;
}

export const api = {
  signIn: (email: string, password: string) =>
    command<Session>("/auth/sign-in", { email, password }),
  signOut: () => command<Session>("/auth/sign-out"),
  setMode: (mode: Mode) => command<Session>("/session/mode", { mode }),
  start: () => command<Session>("/session/start"),
  confirmArea: (acceptUnassisted = false) =>
    command<Session>("/session/confirm", { accept_unassisted: acceptUnassisted }),
  healthTest: () => command<Session>("/session/health-test"),
  retry: () => command<Session>("/session/retry"),
  runProgram: (height_m: number, hold_s: number, ambient: string) =>
    command<Session>("/session/program", { height_m, hold_s, ambient }),
  armManual: (ambient: string) => command<Session>("/session/manual/arm", { ambient }),
  /** Rise to a height and hold it, in Manual, without holding W. Not the Auto
   *  hover test — that one needs base stations; this works on the barometer. */
  holdManual: (height_m: number) => command<Session>("/session/manual/hold", { height_m }),
  cameraStatus: () => command<CameraStatus>("/camera", undefined, "GET"),
  land: () => command<Session>("/session/land"),
  emergencyStop: () => command<Session>("/session/emergency-stop"),
  endSession: () => command<Session>("/session/end"),
  syncNow: () => command<SyncStatus>("/sync/now"),

  // History: this laptop's own record of every session.
  listSessions: (limit = 20, mode?: Mode) =>
    command<SessionRecord[]>(
      `/history/sessions?limit=${limit}${mode ? `&mode=${mode}` : ""}`, undefined, "GET"),
  readSession: (id: string) =>
    command<SessionRecord>(`/history/sessions/${encodeURIComponent(id)}`, undefined, "GET"),
  readSamples: (id: string, variables: readonly string[], mode?: Mode) =>
    command<SampleRow[]>(
      `/history/sessions/${encodeURIComponent(id)}/samples?vars=${encodeURIComponent(variables.join(","))}${mode ? `&mode=${mode}` : ""}`,
      undefined, "GET",
    ),
};

export type FlightRecord = {
  id: string;
  mode: string;
  program: string | null;
  started_at: string;
  ended_at: string | null;
  outcome: string | null;
  abort_reason: string | null;
};

export type SessionRecord = {
  id: string;
  operator_id: string;
  operator_email: string;
  operator_name: string | null;
  drone_hardware_id: string | null;
  mode: string;
  /** Every mode the session used; a session can switch between flights. */
  modes: string[];
  assisted: boolean;
  started_at: string;
  ended_at: string | null;
  end_reason: string | null;
  duration_s: number | null;
  flights: FlightRecord[];
  summary: {
    samples: number;
    battery_start_v: number | null;
    battery_end_v: number | null;
    battery_min_v: number | null;
    max_height_m: number | null;
    temp_min_c: number | null;
    temp_max_c: number | null;
  };
};

export type SampleRow = { recorded_at: string } & Record<string, number | string | null>;

// ── the live socket ───────────────────────────────────────────────────

export type LiveHandlers = {
  onSession: (session: Session) => void;
  /** The agent answered but refused this window — see `onError` callers. */
  onRefused: (message: string) => void;
  onSync: (status: SyncStatus) => void;
  onTelemetry: (telemetry: Telemetry) => void;
  onConnection: (connected: boolean) => void;
};

export class LiveConnection {
  private socket: WebSocket | null = null;
  private heartbeat: number | null = null;
  private retry: number | null = null;
  private closed = false;

  constructor(private handlers: LiveHandlers) {}

  open(): void {
    this.closed = false;
    const socket = new WebSocket(`ws://127.0.0.1:${port}/ws/live`);
    this.socket = socket;

    socket.addEventListener("open", () => {
      // The token goes in the first message, not the URL: a query string ends
      // up in the access log, and this one grants control of a drone.
      socket.send(JSON.stringify({ type: "auth", token }));
      this.handlers.onConnection(true);
      this.heartbeat = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "heartbeat" }));
        }
      }, HEARTBEAT_MS);
    });

    socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (message.type === "error") {
        // The agent is up but will not talk to this window: almost always
        // another copy of the app already holds the port, so this window is
        // talking to that copy's agent with a token it does not know.
        this.closed = true;
        this.handlers.onRefused(
          "Another copy of CropWatcher is already running on this computer. " +
          "Quit it, then reopen this window.",
        );
        socket.close();
        return;
      }
      if (message.type === "session") this.handlers.onSession(message as Session);
      else if (message.type === "sync") this.handlers.onSync(message as SyncStatus);
      else if (message.type === "telemetry") this.handlers.onTelemetry(message as Telemetry);
    });

    const dropped = () => {
      this.stopHeartbeat();
      this.handlers.onConnection(false);
      // The agent is a child of this app, so a dropped socket means it is
      // restarting rather than gone. Keep trying quietly.
      if (!this.closed && this.retry === null) {
        this.retry = window.setTimeout(() => {
          this.retry = null;
          this.open();
        }, 1000);
      }
    };
    socket.addEventListener("close", dropped);
    socket.addEventListener("error", dropped);
  }

  sendIntent(intent: Intent): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "intent", keys: intent }));
    }
  }

  close(): void {
    this.closed = true;
    this.stopHeartbeat();
    this.socket?.close();
  }

  private stopHeartbeat(): void {
    if (this.heartbeat !== null) window.clearInterval(this.heartbeat);
    this.heartbeat = null;
  }
}

/**
 * Every binding, shown on screen.
 *
 * `field` is the intent field a key drives, so a held key can light up. Land
 * and Emergency stop have no intent field: Land is a command, and the stop is
 * hold-to-activate with no keyboard shortcut at all.
 */
export const KEY_LABELS: { keys: { label: string; field?: keyof Intent }[]; action: string }[] = [
  { keys: [{ label: "↑", field: "forward" }, { label: "↓", field: "back" }], action: "Forward / back" },
  { keys: [{ label: "←", field: "left" }, { label: "→", field: "right" }], action: "Left / right" },
  { keys: [{ label: "W", field: "up" }, { label: "S", field: "down" }], action: "Rise / descend, gently" },
  { keys: [{ label: "A", field: "yaw_left" }, { label: "D", field: "yaw_right" }], action: "Rotate left / right" },
  { keys: [{ label: "L" }], action: "Land gracefully" },
];
