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
import { api, cameraFrameUrl, type CameraStatus, type CameraWifi } from "@/lib/agent";
import { showDroneWifi } from "@/lib/droneWifi";
import { Button, Message, Spinner, StatusDot } from "@/components/ui";

/** How often a new frame is pulled while the feed is live. */
const FRAME_MS = 200;

/** How long a frame can be stale before the overlay stops claiming "live". */
const STALE_MS = 2000;

/** How often the agent is asked again while there is no feed. The agent
 *  reconnects to the deck on its own; without this the tab would not notice
 *  until someone pressed Try again — which is how a feed that recovered in
 *  seconds looked dead for good. */
const RETRY_MS = 2000;

/** Missed frames in a row before the tab treats the feed as dropped and goes
 *  back to asking the agent. At FRAME_MS that is ten seconds: a drone swung
 *  through a weak spot drops out for a few seconds and comes back. */
const DROP_AFTER = 50;

/**
 * How long the LAST GOOD FRAME stays on screen through a drop-out, overlaid
 * with its age. The picture holding still and saying "3 s old" is the truth;
 * blanking to "no signal" for every stall was what made the feed feel broken
 * when the drone moved quickly (2026-09-24).
 */
const HOLD_MS = 30_000;

type Load =
  | { kind: "probing" }
  | { kind: "error"; message: string }
  | { kind: "ready"; status: CameraStatus; wifi?: CameraWifi | null };

export function CameraPane({ active }: {
  /** Whether the Camera tab is the one showing. Frames are not pulled behind a
   *  hidden tab — that is a request every 200 ms for an image nobody sees. */
  active: boolean;
}) {
  const [load, setLoad] = useState<Load>({ kind: "probing" });
  // The last frame that arrived whole, as an object URL, and when. Kept across
  // drop-outs on purpose — see HOLD_MS.
  const [shown, setShown] = useState<{ url: string; at: number } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const failures = useRef(0);

  /** `quiet` re-asks without the spinner, so a background retry does not
   *  flash the pane every two seconds. */
  const probe = useCallback(async (quiet = false) => {
    if (!quiet) setLoad({ kind: "probing" });
    failures.current = 0;
    try {
      const [status, wifi] = await Promise.all([
        api.cameraStatus(),
        // Where the deck is in joining the operator's network. Optional: the
        // camera can still work on the deck's own access point without it.
        api.cameraWifi().catch(() => null),
      ]);
      setLoad({ kind: "ready", status, wifi });
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

  // No feed — not yet, or it dropped: keep asking while the tab is showing.
  // Joining the deck's Wi-Fi or the deck coming back then needs no click.
  useEffect(() => {
    if (!active || live || load.kind === "probing") return;
    const timer = window.setTimeout(() => void probe(true), RETRY_MS);
    return () => window.clearTimeout(timer);
  }, [active, live, load, probe]);

  // Pull frames only while the tab is showing AND something is producing them.
  // One request at a time (no pile-up behind a slow one), fetched as a blob so
  // a failed request never replaces the picture — an <img> pointed at a URL
  // that 204s shows nothing at all.
  useEffect(() => {
    if (!active || !live) return;
    let stopped = false;
    let timer = 0;
    const tick = async () => {
      try {
        const response = await fetch(cameraFrameUrl(Date.now()), { cache: "no-store" });
        if (response.status === 200) {
          const url = URL.createObjectURL(await response.blob());
          if (stopped) { URL.revokeObjectURL(url); return; }
          failures.current = 0;
          setShown((previous) => {
            if (previous) URL.revokeObjectURL(previous.url);
            return { url, at: Date.now() };
          });
        } else {
          failures.current += 1;
        }
      } catch {
        failures.current += 1;
      }
      if (stopped) return;
      if (failures.current >= DROP_AFTER) {
        // Long enough to stop pulling and go back to asking the agent, which
        // is reconnecting to the deck on its own. The last frame stays up.
        setLoad((current) => current.kind === "ready"
          ? { ...current, status: { ...current.status, live: false,
              reason: "The camera stream stopped — reconnecting." } }
          : current);
        return;
      }
      timer = window.setTimeout(() => void tick(), FRAME_MS);
    };
    void tick();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [active, live]);

  // A clock for the frame's age, only while there is a frame to age.
  useEffect(() => {
    if (!active || shown === null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [active, shown]);

  // Release the last object URL when the pane goes away.
  const shownRef = useRef(shown);
  shownRef.current = shown;
  useEffect(() => () => { if (shownRef.current) URL.revokeObjectURL(shownRef.current.url); }, []);

  const age = shown === null ? null : Math.max(0, now - shown.at);
  const fresh = age !== null && age < STALE_MS;
  // The last frame stays up through a drop-out, for HOLD_MS.
  const holding = shown !== null && age !== null && age < HOLD_MS;

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

          {load.kind === "ready" && !load.status.live && !holding && (
            <div className="absolute inset-0 grid content-center gap-3 px-6 text-center">
              <p className="mono text-xs uppercase tracking-[0.1em] text-[var(--console-dim)]">
                No signal
              </p>
              <p className="text-sm leading-relaxed text-[var(--console-ink)]">
                {load.status.reason ?? "No camera is connected."}
              </p>
              <DeckLine fitted={load.status.deck_fitted} />

              <div className="flex justify-center">
                <Button onClick={showDroneWifi}>Change Wi-Fi</Button>
              </div>
            </div>
          )}

          {holding && shown && (
            <>
              <img
                src={shown.url}
                alt="The drone's camera view"
                className={`h-full w-full object-contain ${fresh ? "" : "opacity-70"}`}
              />
              <Reticle />
              {!fresh && age !== null && (
                <p
                  role="status"
                  className="mono absolute left-2 top-2 border border-[var(--console-line)] bg-[var(--console)] px-2 py-1 text-[10px] uppercase tracking-[0.08em] text-[var(--console-ink)]"
                >
                  Reconnecting · last frame {(age / 1000).toFixed(1)} s ago
                </p>
              )}
            </>
          )}

          {!holding && !live && <Reticle dim />}
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
        <button
          type="button"
          onClick={showDroneWifi}
          className="min-h-8 px-1 uppercase tracking-[0.08em] text-[var(--console-ink)] underline underline-offset-2"
        >
          Wi-Fi
        </button>
        <span>
          {live || holding ? (
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
  // One line. The long explanation of why frames need Wi-Fi lives in
  // camera.txt, not on an operator's screen every time the feed is down.
  const text = fitted === null ? "AI deck: not asked yet"
    : fitted ? "AI deck: fitted" : "AI deck: not fitted — no camera on this drone";
  return (
    <p className="mono text-[10px] uppercase tracking-[0.08em] text-[var(--console-dim)]">
      {text}
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
