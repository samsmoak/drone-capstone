/**
 * The desktop window: status, manual control, log.
 *
 * The contract with the agent is not invented here — it is the one in
 * `backend/agent/cropwatcher/api/rest.py::manual_socket`:
 *
 *   → {type:"intent", keys:{up,down,forward,back,left,right,yaw_left,yaw_right}}
 *   → {type:"heartbeat"}      ~10 Hz
 *   → {type:"panic"} | {type:"land"}
 *   ← {ready:true} | {state,thrust} | {error}
 *
 * **This file never generates a setpoint stream.** The agent runs its own
 * 50 Hz loop and lands the drone if this window goes quiet. Sending one packet
 * per keypress is the failure that design exists to prevent: the Crazyflie
 * commander stops accepting control below ~10 Hz and the drone drops.
 */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

/** Held-key state. Mirrors `Intent` in `api/manual.py` field for field. */
type Intent = {
  up: boolean;
  down: boolean;
  forward: boolean;
  back: boolean;
  left: boolean;
  right: boolean;
  yaw_left: boolean;
  yaw_right: boolean;
};

const EMPTY_INTENT: Intent = {
  up: false,
  down: false,
  forward: false,
  back: false,
  left: false,
  right: false,
  yaw_left: false,
  yaw_right: false,
};

/**
 * Physical key → intent field, by `KeyboardEvent.code`.
 *
 * `code` rather than `key`, so the bindings sit on the same physical keys on
 * an AZERTY keyboard — W/A/S/D by letter would scatter across the board.
 */
const KEY_MAP: Record<string, keyof Intent> = {
  ArrowUp: "forward",
  ArrowDown: "back",
  ArrowLeft: "left",
  ArrowRight: "right",
  KeyW: "up",
  KeyS: "down",
  KeyA: "yaw_left",
  KeyD: "yaw_right",
};

/** The agent expects a ping about ten times a second; it lands after 0.5 s. */
const HEARTBEAT_MS = 100;
const STATUS_POLL_MS = 2000;

const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const agentState = el<HTMLElement>("agent-state");
const droneState = el<HTMLElement>("drone-state");
const controlState = el<HTMLElement>("control-state");
const thrustValue = el<HTMLElement>("thrust-value");
const connectButton = el<HTMLButtonElement>("connect");
const panicButton = el<HTMLButtonElement>("panic");
const clearLogButton = el<HTMLButtonElement>("clear-log");
const manualNote = el<HTMLParagraphElement>("manual-note");
const logBox = el<HTMLDivElement>("log");

let port = 8765;
let socket: WebSocket | null = null;
let heartbeat: number | null = null;
let intent: Intent = { ...EMPTY_INTENT };

// ── log ──────────────────────────────────────────────────────────────

/** Keep the log bounded: a long flight at 10 Hz would otherwise grow forever. */
const MAX_LOG_LINES = 500;

function appendLog(line: string, stream: "stdout" | "stderr" = "stdout") {
  const empty = document.getElementById("log-empty");
  if (empty) empty.remove();

  // Pinned to the bottom only when the operator is already there, so scrolling
  // back to read an error is not yanked away by the next line.
  const atBottom =
    logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 40;

  const p = document.createElement("p");
  p.dataset.stream = stream;
  p.textContent = line;
  logBox.appendChild(p);

  while (logBox.childElementCount > MAX_LOG_LINES) {
    logBox.firstElementChild?.remove();
  }
  if (atBottom) logBox.scrollTop = logBox.scrollHeight;
}

clearLogButton.addEventListener("click", () => {
  logBox.replaceChildren();
  appendLog("Log cleared.");
});

// ── status ───────────────────────────────────────────────────────────

function setStatus(node: HTMLElement, text: string, status: string) {
  node.textContent = text;
  node.dataset.status = status;
}

/**
 * Poll the agent for what it can see.
 *
 * Every outcome says something. "Not running" is a real answer an operator can
 * act on; a blank panel would read as "idle" next to a drone that is armed.
 */
async function pollStatus() {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/status`, {
      signal: AbortSignal.timeout(1500),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const body = await response.json();
    setStatus(agentState, "running", "good");
    setStatus(
      droneState,
      body.drone_connected ? (body.uri ?? "connected") : "not found",
      body.drone_connected ? "good" : "warning",
    );
    if (!socket) {
      setStatus(controlState, body.busy ? (body.current ?? "busy") : "idle", "idle");
    }
  } catch {
    setStatus(agentState, "not running", "critical");
    setStatus(droneState, "unknown", "idle");
  }
}

// ── manual control ───────────────────────────────────────────────────

function sendIntent() {
  socket?.send(JSON.stringify({ type: "intent", keys: intent }));
}

function paintHeldKeys() {
  document.querySelectorAll<HTMLElement>("kbd[data-key]").forEach((kbd) => {
    const field = KEY_MAP[kbd.dataset.key ?? ""];
    kbd.dataset.held = String(field ? intent[field] : false);
  });
}

function connect() {
  if (socket) return;

  connectButton.disabled = true;
  connectButton.textContent = "Connecting…";

  const ws = new WebSocket(`ws://127.0.0.1:${port}/ws/manual`);
  socket = ws;

  ws.addEventListener("open", () => {
    // Heartbeat, not a setpoint stream. It carries no control data — it only
    // tells the agent this window is still alive.
    heartbeat = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "heartbeat" }));
      }
    }, HEARTBEAT_MS);
  });

  ws.addEventListener("message", (event) => {
    const data = JSON.parse(event.data as string);

    if (data.error) {
      manualNote.dataset.tone = "error";
      manualNote.textContent = data.error;
      appendLog(`manual control: ${data.error}`, "stderr");
      return;
    }
    if (data.ready) {
      connectButton.disabled = false;
      connectButton.textContent = "Release control";
      manualNote.removeAttribute("data-tone");
      manualNote.textContent =
        "You have control. Hold the keys below — the drone descends whenever you are not asking it to climb.";
      appendLog("manual control: ready");
    }
    if (data.state) setStatus(controlState, data.state, data.state === "flying" ? "good" : "idle");
    if (typeof data.thrust === "number") thrustValue.textContent = String(data.thrust);
  });

  ws.addEventListener("close", () => {
    teardown();
    manualNote.textContent =
      "Control released. The agent lands the drone by itself if this window stops responding.";
  });

  ws.addEventListener("error", () => {
    manualNote.dataset.tone = "error";
    manualNote.textContent =
      "Could not reach the agent on this computer. Check the status bar above, then try again.";
    appendLog("manual control: socket error", "stderr");
    teardown();
  });
}

function teardown() {
  if (heartbeat !== null) {
    window.clearInterval(heartbeat);
    heartbeat = null;
  }
  socket = null;
  intent = { ...EMPTY_INTENT };
  paintHeldKeys();
  thrustValue.textContent = "0";
  setStatus(controlState, "idle", "idle");
  connectButton.disabled = false;
  connectButton.textContent = "Take control";
}

connectButton.addEventListener("click", () => {
  if (socket) {
    socket.send(JSON.stringify({ type: "land" }));
    socket.close();
  } else {
    connect();
  }
});

/**
 * Cut motors.
 *
 * Goes over the socket when there is one and falls back to the agent's REST
 * stop otherwise, so the button still works when the socket is the thing that
 * has wedged. It is never disabled.
 */
async function panicStop() {
  appendLog("PANIC — cutting motors", "stderr");
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "panic" }));
  }
  try {
    await invoke("panic_stop");
  } catch (error) {
    appendLog(`stop failed: ${String(error)}`, "stderr");
  }
  intent = { ...EMPTY_INTENT };
  paintHeldKeys();
}

panicButton.addEventListener("click", panicStop);

// ── keyboard ─────────────────────────────────────────────────────────

/**
 * Track key *state*, not the OS repeat stream.
 *
 * Holding a key fires `keydown` repeatedly at whatever rate the OS is set to,
 * which has nothing to do with how fast the drone should be commanded.
 * `event.repeat` is dropped and intent is only sent when it actually changes.
 */
window.addEventListener("keydown", (event) => {
  // Checked before anything else, so a panic is never queued behind a move.
  // P, not Space: Space is the key most easily hit by accident, and cutting
  // the motors in the air drops the drone. Deliberate over reachable; the
  // Cut motors button stays for the reachable case.
  if (event.code === "KeyP") {
    event.preventDefault();
    void panicStop();
    return;
  }
  // Space does nothing — the webview must not treat it as a button press.
  if (event.code === "Space") {
    event.preventDefault();
    return;
  }

  if (event.repeat) return;

  if (event.code === "KeyQ") {
    event.preventDefault();
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "land" }));
      appendLog("land requested");
    }
    return;
  }

  const field = KEY_MAP[event.code];
  if (!field || intent[field]) return;

  event.preventDefault();
  intent = { ...intent, [field]: true };
  paintHeldKeys();
  if (socket?.readyState === WebSocket.OPEN) sendIntent();
});

window.addEventListener("keyup", (event) => {
  // WKWebView activates a focused button on Space *keyup*. Blocking only
  // keydown would leave a focused Cut motors button one Space away.
  if (event.code === "Space") {
    event.preventDefault();
    return;
  }
  const field = KEY_MAP[event.code];
  if (!field) return;

  event.preventDefault();
  intent = { ...intent, [field]: false };
  paintHeldKeys();
  if (socket?.readyState === WebSocket.OPEN) sendIntent();
});

/**
 * A window that loses focus cannot see `keyup`.
 *
 * Without this, alt-tabbing while holding forward leaves the agent believing
 * forward is still held. Releasing everything is the safe reading: thrust
 * decays and the drone comes down.
 */
window.addEventListener("blur", () => {
  if (Object.values(intent).some(Boolean)) {
    intent = { ...EMPTY_INTENT };
    paintHeldKeys();
    if (socket?.readyState === WebSocket.OPEN) sendIntent();
    appendLog("window lost focus — all controls released");
  }
});

// ── startup ──────────────────────────────────────────────────────────

listen<{ stream: "stdout" | "stderr"; line: string }>("agent-log", (event) => {
  if (event.payload.line) appendLog(event.payload.line, event.payload.stream);
});

(async () => {
  try {
    port = await invoke<number>("agent_port");
  } catch {
    // Keep the default and say so rather than failing silently.
    appendLog(`could not read the agent port; assuming ${port}`, "stderr");
  }
  void pollStatus();
  window.setInterval(pollStatus, STATUS_POLL_MS);
})();
