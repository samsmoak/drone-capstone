/**
 * What the drone sees — when there is anything to see.
 *
 * READ THIS BEFORE WIRING A STREAM IN. As of 2026-09-22 this project has no
 * camera pipeline at all, and that is not an oversight:
 *
 *   1. The AI deck IS fitted — `deck.bcAI` reads 1 on the lab drone — but its
 *      Wi-Fi datalink never worked in the original capstone and was cut from
 *      final scope. CLAUDE.md lists it under "Out of scope".
 *   2. The agent serves no image or video route. Its live WebSocket carries
 *      telemetry, session and sync frames only.
 *   3. The window's CSP (desktop/src-tauri/tauri.conf.json) declares
 *      `default-src 'self'` and no `img-src`, so images fall back to 'self'.
 *      The deck serves from its own access point, which is neither 'self' nor
 *      127.0.0.1:8765 — THE WINDOW CANNOT RENDER A FRAME FROM IT TODAY.
 *
 * So this pane is the finished UI for a stream that does not exist yet: all
 * four states are real code paths, and the empty state says plainly what is
 * missing rather than showing a grey box. Turning it on later is three things:
 * a datalink, an agent route that relays frames, and a CSP entry — after which
 * only CAMERA_URL below needs to change.
 */

import { useCallback, useEffect, useState } from "react";
import { Button, Message, Spinner, StatusDot } from "@/components/ui";

/**
 * Where frames would come from. `null` while no relay exists.
 *
 * It must be a URL the window's CSP permits — i.e. served by the agent on
 * 127.0.0.1:8765, not fetched from the deck directly. The agent is the only
 * process allowed to talk to the drone's hardware, and that rule holds for the
 * camera exactly as it holds for the radio.
 */
const CAMERA_URL: string | null = null;

type CameraState =
  | { kind: "probing" }
  | { kind: "unavailable"; reason: string }
  | { kind: "error"; message: string }
  | { kind: "live"; url: string };

/** How long a frame can be stale before the overlay stops claiming "live". */
const STALE_MS = 2000;

export function CameraPane() {
  const [state, setState] = useState<CameraState>({ kind: "probing" });
  const [frameAt, setFrameAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const probe = useCallback(() => {
    setState({ kind: "probing" });
    setFrameAt(null);
    if (CAMERA_URL === null) {
      setState({
        kind: "unavailable",
        reason:
          "No camera datalink. The AI deck is fitted on this drone, but its Wi-Fi " +
          "link is not connected and the flight agent serves no video, so there is " +
          "nothing for this window to show.",
      });
      return;
    }
    setState({ kind: "live", url: CAMERA_URL });
  }, []);

  useEffect(probe, [probe]);

  // Only tick while a stream is actually up: a clock running behind an empty
  // pane is a re-render ten times a minute for nothing.
  useEffect(() => {
    if (state.kind !== "live") return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [state.kind]);

  const age = frameAt === null ? null : now - frameAt;
  const fresh = age !== null && age < STALE_MS;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative flex min-h-0 flex-1 items-center justify-center bg-[var(--console)] p-4">
        {/* The frame keeps 4:3 whatever the pane does, so the empty state and a
            real stream occupy exactly the same box. */}
        <div className="relative aspect-[4/3] w-full max-w-[520px] border border-[var(--console-line)]">
          {state.kind === "probing" && (
            <div className="absolute inset-0 flex items-center justify-center px-6">
              <Spinner label="Looking for a camera on this drone…" />
            </div>
          )}

          {state.kind === "unavailable" && (
            <div className="absolute inset-0 grid content-center gap-3 px-6 text-center">
              <p className="mono text-xs uppercase tracking-[0.1em] text-[var(--console-dim)]">
                No signal
              </p>
              <p className="text-sm leading-relaxed text-[var(--console-ink)]">{state.reason}</p>
              <p className="text-xs leading-relaxed text-[var(--console-dim)]">
                Turning this on needs three things: a working datalink from the deck, a
                route on the flight agent that relays its frames, and an <code>img-src</code>{" "}
                entry in the window's content policy. The agent stays the only process
                that talks to the drone's hardware.
              </p>
            </div>
          )}

          {state.kind === "error" && (
            <div className="absolute inset-0 grid content-center gap-3 px-6">
              <Message tone="critical" text={state.message} />
              <div className="flex justify-center">
                <Button onClick={probe}>Try again</Button>
              </div>
            </div>
          )}

          {state.kind === "live" && (
            <>
              <img
                src={state.url}
                alt="The drone's camera view"
                className="h-full w-full object-cover"
                onLoad={() => setFrameAt(Date.now())}
                onError={() =>
                  setState({
                    kind: "error",
                    message:
                      "The camera stream stopped. The drone may have moved out of range of " +
                      "its datalink, or the relay on the flight agent may have ended.",
                  })
                }
              />
              <Reticle />
            </>
          )}

          {/* Drawn on every state: the pane should read as a camera view even
              when it is empty, and an empty frame with no furniture reads as a
              rendering bug instead. */}
          {state.kind !== "live" && <Reticle dim />}
        </div>
      </div>

      <div className="mono flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-[var(--console-line)] bg-[var(--console)] px-3 py-1.5 text-[10px] uppercase tracking-[0.08em]">
        <span className="text-[var(--console-dim)]">
          {state.kind === "live" ? "AI deck · 4:3" : "AI deck · not connected"}
        </span>
        <span>
          {state.kind === "live" ? (
            <StatusDot tone={fresh ? "good" : "warning"}>
              {age === null ? "Waiting for a frame" : fresh ? `Live · ${age} ms` : `Stale · ${(age / 1000).toFixed(1)} s`}
            </StatusDot>
          ) : (
            <StatusDot tone="idle">No frames</StatusDot>
          )}
        </span>
      </div>
    </div>
  );
}

/** Corner brackets and a centre cross — camera furniture, not data. */
function Reticle({ dim = false }: { dim?: boolean }) {
  const stroke = dim ? "var(--console-line)" : "var(--adi-ink)";
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 400 300"
      className="pointer-events-none absolute inset-0 h-full w-full"
      fill="none"
      stroke={stroke}
      strokeWidth="2"
      opacity={dim ? 1 : 0.8}
    >
      <path d="M16 40 V16 H40" />
      <path d="M360 16 H384 V40" />
      <path d="M384 260 V284 H360" />
      <path d="M40 284 H16 V260" />
      <path d="M186 150 H196 M204 150 H214 M200 136 V146 M200 154 V164" />
    </svg>
  );
}
