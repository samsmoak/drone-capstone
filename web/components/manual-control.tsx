"use client";

import { useCallback, useEffect, useRef } from "react";
import { EMPTY_INTENT, useManualStore, type Intent } from "@/lib/store";

/**
 * Manual control from the browser, over the agent's WebSocket.
 *
 * A platform port of `desktop/src/main.ts`. The contract is the agent's, from
 * `backend/agent/cropwatcher/api/rest.py::manual_socket`, and is identical in
 * both clients:
 *
 *   → {type:"intent", keys:{up,down,forward,back,left,right,yaw_left,yaw_right}}
 *   → {type:"heartbeat"}      ~10 Hz
 *   → {type:"panic"} | {type:"land"}
 *   ← {ready:true} | {state,thrust} | {error}
 *
 * **The browser sends held-key state, never a setpoint stream.** The agent runs
 * its own 50 Hz loop and lands the drone after 0.5 s without a heartbeat. A
 * packet per keypress is the design that drops a drone the first time one is
 * late: the Crazyflie commander stops accepting control below ~10 Hz.
 */

const AGENT_URL = process.env.NEXT_PUBLIC_AGENT_URL ?? "http://127.0.0.1:8765";
const WS_URL = AGENT_URL.replace(/^http/, "ws") + "/ws/manual";
const HEARTBEAT_MS = 100;

/** Physical key (`KeyboardEvent.code`, so AZERTY keeps the same positions) → intent field. */
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

/** Every binding, shown on screen. A control surface with hidden keys is a crash waiting to happen. */
const BINDINGS: { keys: { code: string; label: string }[]; action: string; danger?: boolean }[] = [
  { keys: [{ code: "ArrowUp", label: "↑" }, { code: "ArrowDown", label: "↓" }], action: "Forward / back" },
  { keys: [{ code: "ArrowLeft", label: "←" }, { code: "ArrowRight", label: "→" }], action: "Left / right" },
  { keys: [{ code: "KeyW", label: "W" }, { code: "KeyS", label: "S" }], action: "Up / down" },
  { keys: [{ code: "KeyA", label: "A" }, { code: "KeyD", label: "D" }], action: "Rotate left / right" },
  { keys: [{ code: "KeyQ", label: "Q" }], action: "Land gently and disarm" },
  { keys: [{ code: "KeyP", label: "P" }], action: "Cut motors immediately", danger: true },
];

export function ManualControl() {
  const socketRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<number | null>(null);

  const socket = useManualStore((s) => s.socket);
  const controlState = useManualStore((s) => s.controlState);
  const thrust = useManualStore((s) => s.thrust);
  const intent = useManualStore((s) => s.intent);
  const message = useManualStore((s) => s.message);
  const { setSocket, setReport, setIntent } = useManualStore.getState();

  const send = (frame: object) => {
    const ws = socketRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(frame));
  };

  const updateIntent = useCallback((next: Intent) => {
    setIntent(next);
    const ws = socketRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "intent", keys: next }));
  }, [setIntent]);

  const teardown = useCallback(() => {
    if (heartbeatRef.current !== null) window.clearInterval(heartbeatRef.current);
    heartbeatRef.current = null;
    socketRef.current = null;
    setIntent(EMPTY_INTENT);
    setReport("idle", 0);
  }, [setIntent, setReport]);

  const connect = () => {
    if (socketRef.current) return;
    setSocket("connecting");

    let ws: WebSocket;
    try {
      ws = new WebSocket(WS_URL);
    } catch {
      // A page served over https may refuse to open ws:// at all.
      setSocket(
        "error",
        "This browser would not open a connection to the agent. Use the CropWatcher desktop app for manual control.",
      );
      return;
    }
    socketRef.current = ws;

    ws.addEventListener("open", () => {
      // Liveness only — carries no control data.
      heartbeatRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "heartbeat" }));
      }, HEARTBEAT_MS);
    });

    ws.addEventListener("message", (event) => {
      let data: { ready?: boolean; state?: string; thrust?: number; error?: string };
      try {
        data = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (data.error) {
        setSocket("error", data.error);
        return;
      }
      if (data.ready) setSocket("ready");
      if (data.state) setReport(data.state, data.thrust);
    });

    ws.addEventListener("close", (event) => {
      const wasReady = useManualStore.getState().socket === "ready";
      teardown();
      if (event.code === 1008) {
        setSocket("error", "The agent refused this page. Its allowed-origins list does not include this site.");
      } else if (useManualStore.getState().socket !== "error") {
        setSocket(
          "disconnected",
          wasReady ? "Control released. The agent lands the drone by itself if this page stops responding." : null,
        );
      }
    });

    ws.addEventListener("error", () => {
      setSocket(
        "error",
        "Could not reach the agent on this computer. Check that CropWatcher is running and the radio is plugged in — or use the desktop app, which some browsers require.",
      );
    });
  };

  const release = () => {
    send({ type: "land" });
    socketRef.current?.close();
  };

  /**
   * Cut motors. Never disabled.
   *
   * Over the socket when there is one, and also the agent's REST stop, so it
   * still works when the socket is the thing that has wedged. That POST carries
   * no body or custom headers, so the browser sends it without a CORS preflight.
   */
  const panic = useCallback(() => {
    send({ type: "panic" });
    void fetch(`${AGENT_URL}/flight/stop`, { method: "POST" }).catch(() => {
      setSocket("error", "Could not reach the agent to cut the motors. Unplug the battery if the drone is still flying.");
    });
    updateIntent(EMPTY_INTENT);
  }, [setSocket, updateIntent]);

  // ── keyboard: key *state*, not the OS repeat stream ─────────────────────
  useEffect(() => {
    const onDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      // Checked before anything else, so a panic is never queued behind a move.
      // P, not Space: Space is the key most easily hit by accident, and cutting
      // the motors in the air drops the drone. The operator chose deliberate
      // over reachable; the on-screen button stays for the reachable case.
      if (event.code === "KeyP") {
        event.preventDefault();
        panic();
        return;
      }
      // Space does nothing here — including scrolling the controls off screen.
      if (event.code === "Space") {
        event.preventDefault();
        return;
      }
      if (event.repeat) return;
      if (event.code === "KeyQ") {
        event.preventDefault();
        send({ type: "land" });
        return;
      }
      const field = KEY_MAP[event.code];
      const current = useManualStore.getState().intent;
      if (!field || current[field]) return;
      event.preventDefault();
      updateIntent({ ...current, [field]: true });
    };

    const onUp = (event: KeyboardEvent) => {
      // A focused button activates on Space *keyup* in WebKit. Blocking only
      // keydown would leave a focused Cut motors button one Space away.
      if (event.code === "Space") {
        event.preventDefault();
        return;
      }
      const field = KEY_MAP[event.code];
      if (!field) return;
      event.preventDefault();
      updateIntent({ ...useManualStore.getState().intent, [field]: false });
    };

    // A page that loses focus never sees keyup. Releasing everything is the
    // safe reading: thrust decays and the drone comes down.
    const onBlur = () => {
      if (Object.values(useManualStore.getState().intent).some(Boolean)) updateIntent(EMPTY_INTENT);
    };

    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
      window.removeEventListener("blur", onBlur);
    };
  }, [panic, updateIntent]);

  // Leaving the page closes the socket; the agent lands the drone.
  useEffect(() => () => socketRef.current?.close(), []);

  const connected = socket === "ready";
  const heldCode = (code: string) => {
    if (code === "KeyP" || code === "KeyQ") return false;
    const field = KEY_MAP[code];
    return field ? intent[field] : false;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
        <dl className="flex flex-wrap gap-8">
          <div>
            <dt className="text-xs uppercase tracking-wide text-[var(--muted)]">Connection</dt>
            <dd className="mt-1 flex items-center gap-2 font-semibold" role="status" aria-live="polite">
              <span
                aria-hidden="true"
                style={{
                  color: connected
                    ? "var(--status-good)"
                    : socket === "error"
                      ? "var(--status-critical)"
                      : "var(--muted)",
                }}
              >
                {connected ? "●" : socket === "error" ? "■" : "○"}
              </span>
              {{ ready: "In control", connecting: "Connecting…", error: "Not connected", disconnected: "Not connected" }[socket]}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-[var(--muted)]">Controller</dt>
            <dd className="tabular mt-1 font-semibold">{controlState}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-[var(--muted)]">Thrust</dt>
            <dd className="tabular mt-1 font-semibold">{thrust.toLocaleString()}</dd>
          </div>
        </dl>

        {/* Always enabled, whatever the connection state. */}
        <button
          type="button"
          onClick={panic}
          className="inline-flex min-h-12 items-center gap-2 rounded-lg border-2 border-[var(--status-critical)] bg-[var(--status-critical)] px-5 font-bold text-[var(--on-critical)]"
        >
          Cut motors
          <kbd className="rounded border border-[var(--on-critical)] px-1.5 text-xs font-medium">P</kbd>
        </button>
      </div>

      {message && (
        <p
          role={socket === "error" ? "alert" : "status"}
          className="rounded-lg border bg-[var(--surface)] p-3 text-sm"
          style={{ borderColor: socket === "error" ? "var(--status-critical)" : "var(--border)" }}
        >
          {socket === "error" && <span aria-hidden="true">⚠ </span>}
          {message}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {connected ? (
          <button
            type="button"
            onClick={release}
            className="inline-flex min-h-11 items-center rounded-lg border border-[var(--border)] px-5 font-medium"
          >
            Land and release control
          </button>
        ) : (
          <button
            type="button"
            onClick={connect}
            disabled={socket === "connecting"}
            className="inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-5 font-medium text-[var(--on-primary)] disabled:opacity-50"
          >
            {socket === "connecting" ? "Connecting…" : "Take control"}
          </button>
        )}
        <p className="text-sm text-[var(--muted)]">
          {connected
            ? "Hold the keys below. The drone descends whenever you are not asking it to climb."
            : "Connects to the agent on this computer. Stay in the room with the drone."}
        </p>
      </div>

      <section aria-labelledby="keys-heading" className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5">
        <h2 id="keys-heading" className="mb-4 text-lg font-semibold text-[var(--heading)]">
          Keys
        </h2>
        <dl className="grid gap-3 sm:grid-cols-2">
          {BINDINGS.map((binding) => (
            <div key={binding.action} className="flex items-center gap-4">
              <dt className="flex min-w-28 gap-1.5">
                {binding.keys.map((key) => {
                  const held = heldCode(key.code);
                  return (
                    <kbd
                      key={key.code}
                      data-held={held}
                      className={`inline-flex h-9 min-w-9 items-center justify-center rounded-md border border-b-2 px-2 text-sm ${
                        held
                          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--on-primary)]"
                          : "border-[var(--border)] bg-[var(--surface-2)]"
                      }`}
                    >
                      {key.label}
                    </kbd>
                  );
                })}
              </dt>
              <dd className={binding.danger ? "font-semibold" : "text-[var(--muted)]"}>{binding.action}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
