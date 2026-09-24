/**
 * What the drone sees — when there is anything to see.
 *
 * THE WHOLE PATH IS REAL NOW; only the camera is not. Frames come from the
 * agent's own `/camera/frame`, through the window's content policy, into this
 * tab. What the agent puts behind that route is a `FrameSource`: "there is no
 * camera", a generated test pattern (`CROPWATCHER_CAMERA=test`), or the AI
 * deck's Wi-Fi streamer (`CROPWATCHER_CAMERA=deck`, with this laptop joined to
 * the deck's access point). This pane does not know which.
 *
 * The frames cannot come over the radio: usable CRTP throughput is a few KB/s
 * and the same link carries the 50 Hz setpoint stream, which the drone falls
 * out of the air without. That is why the deck has its own Wi-Fi chip.
 *
 * `deck_fitted` is the drone's answer, not a sentence someone typed: the pane
 * distinguishes "the deck is fitted and the link is down" from "nothing has
 * asked yet", because those need different things done about them.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, cameraFrameUrl, type CameraStatus } from "@/lib/agent";
import { Button, Message, Spinner, StatusDot } from "@/components/ui";

/** How often a new frame is pulled while the feed is live. */
const FRAME_MS = 200;

/** How long a frame can be stale before the overlay stops claiming "live". */
const STALE_MS = 2000;

type Load =
  | { kind: "probing" }
  | { kind: "error"; message: string }
  | { kind: "ready"; status: CameraStatus };

export function CameraPane({ active }: {
  /** Whether the Camera tab is the one showing. Frames are not pulled behind a
   *  hidden tab — that is a request every 200 ms for an image nobody sees. */
  active: boolean;
}) {
  const [load, setLoad] = useState<Load>({ kind: "probing" });
  const [stamp, setStamp] = useState(() => Date.now());
  const [frameAt, setFrameAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const failures = useRef(0);

  const probe = useCallback(async () => {
    setLoad({ kind: "probing" });
    setFrameAt(null);
    failures.current = 0;
    try {
      setLoad({ kind: "ready", status: await api.cameraStatus() });
    } catch (e) {
      setLoad({
        kind: "error",
        message: e instanceof Error ? e.message : "Could not ask the agent about the camera.",
      });
    }
  }, []);

  useEffect(() => {
    if (active) void probe();
  }, [active, probe]);

  const live = load.kind === "ready" && load.status.live;

  // Pull frames only while the tab is showing AND something is producing them.
  useEffect(() => {
    if (!active || !live) return;
    const timer = window.setInterval(() => {
      setStamp(Date.now());
      setNow(Date.now());
    }, FRAME_MS);
    return () => window.clearInterval(timer);
  }, [active, live]);

  const age = frameAt === null ? null : now - frameAt;
  const fresh = age !== null && age < STALE_MS;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative flex min-h-0 flex-1 items-center justify-center bg-[var(--console)] p-4">
        {/* A fixed box, so the empty state and a live feed occupy the same
            space. The deck's frames are 324x244 (measured), so the image is
            contained — letterboxed — never cropped to fit. */}
        <div className="relative aspect-square w-full max-w-[420px] border border-[var(--console-line)]">
          {load.kind === "probing" && (
            <div className="absolute inset-0 flex items-center justify-center px-6">
              <Spinner label="Asking the agent about the camera…" />
            </div>
          )}

          {load.kind === "error" && (
            <div className="absolute inset-0 grid content-center gap-3 px-6">
              <Message tone="critical" text={load.message} />
              <div className="flex justify-center">
                <Button onClick={() => void probe()}>Try again</Button>
              </div>
            </div>
          )}

          {load.kind === "ready" && !load.status.live && (
            <div className="absolute inset-0 grid content-center gap-3 px-6 text-center">
              <p className="mono text-xs uppercase tracking-[0.1em] text-[var(--console-dim)]">
                No signal
              </p>
              <p className="text-sm leading-relaxed text-[var(--console-ink)]">
                {load.status.reason ?? "No camera is connected."}
              </p>
              <DeckLine fitted={load.status.deck_fitted} />
            </div>
          )}

          {load.kind === "ready" && load.status.live && (
            <>
              <img
                // `stamp` in the URL is what makes this a feed rather than one
                // cached image; the agent also sends no-store.
                src={cameraFrameUrl(stamp)}
                alt="The drone's camera view"
                className="h-full w-full object-contain"
                onLoad={() => { failures.current = 0; setFrameAt(Date.now()); }}
                onError={() => {
                  // One dropped frame is a hiccup; several in a row is a feed
                  // that has stopped, and saying so at the first is noise.
                  failures.current += 1;
                  if (failures.current >= 5) {
                    setLoad({
                      kind: "error",
                      message:
                        "The camera stream stopped. The drone may have moved out of range " +
                        "of its datalink, or the relay on the flight agent may have ended.",
                    });
                  }
                }}
              />
              <Reticle />
            </>
          )}

          {!live && <Reticle dim />}
        </div>
      </div>

      <div className="mono flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-[var(--console-line)] bg-[var(--console)] px-3 py-1.5 text-[10px] uppercase tracking-[0.08em]">
        <span className="text-[var(--console-dim)]">
          {load.kind === "ready" && load.status.live
            ? [load.status.kind, load.status.width && load.status.height
                ? `${load.status.width}×${load.status.height}` : null]
                .filter(Boolean).join(" · ")
            : "AI deck · not connected"}
        </span>
        <span>
          {live ? (
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

/**
 * What the drone said about the deck, and what that means.
 *
 * Three states and they are genuinely different: fitted with no link is a lab
 * problem, not fitted is a hardware one, and "nothing has asked" is neither —
 * it just means no session has run the checks yet.
 */
function DeckLine({ fitted }: { fitted: boolean | null }) {
  if (fitted === null) {
    return (
      <p className="text-xs leading-relaxed text-[var(--console-dim)]">
        The drone has not been asked whether the AI deck is fitted — that happens
        during the checks. Start a session to find out.
      </p>
    );
  }
  if (!fitted) {
    return (
      <p className="text-xs leading-relaxed text-[var(--console-dim)]">
        The drone reports <strong>no AI deck</strong> (deck.bcAI = 0). There is no
        camera on this airframe to connect to.
      </p>
    );
  }
  return (
    <p className="text-xs leading-relaxed text-[var(--console-dim)]">
      The drone reports the <strong>AI deck is fitted</strong> (deck.bcAI = 1), so the
      camera is there — what is missing is the link to it. Frames cannot come over
      the radio: that link carries the 50 Hz setpoint stream the drone stays in the
      air on. The deck's own Wi-Fi is the route, and getting it working is a lab
      job.
    </p>
  );
}

/** Corner brackets and a centre cross — camera furniture, not data. */
function Reticle({ dim = false }: { dim?: boolean }) {
  const stroke = dim ? "var(--console-line)" : "var(--adi-ink)";
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 400 400"
      className="pointer-events-none absolute inset-0 h-full w-full"
      fill="none"
      stroke={stroke}
      strokeWidth="2"
      opacity={dim ? 1 : 0.8}
    >
      <path d="M16 40 V16 H40" />
      <path d="M360 16 H384 V40" />
      <path d="M384 360 V384 H360" />
      <path d="M40 384 H16 V360" />
      <path d="M186 200 H196 M204 200 H214 M200 186 V196 M200 204 V214" />
    </svg>
  );
}
