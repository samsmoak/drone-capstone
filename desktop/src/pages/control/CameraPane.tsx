/**
 * What the drone sees — when there is anything to see.
 *
 * THE WHOLE PATH IS REAL NOW; only the camera is not. Frames come from the
 * agent's own `/camera/frame`, through the window's content policy, into this
 * tab. What the agent puts behind that route is a `FrameSource`: "there is no
 * camera", a generated test pattern (`DRONEDECK_CAMERA=test`), or the AI
 * deck's Wi-Fi streamer (`DRONEDECK_CAMERA=deck`, with this laptop joined to
 * the deck's access point). This pane does not know which.
 *
 * The frames cannot come over the radio: usable CRTP throughput is a few KB/s
 * and the same link carries the 50 Hz setpoint stream, which the drone falls
 * out of the air without. That is why the deck has its own Wi-Fi chip.
 *
 * `deck_fitted` is the drone's answer, not a sentence someone typed: the pane
 * distinguishes "the deck is fitted and the link is down" from "nothing has
 * asked yet", because those need different things done about them.
 *
 * TWO SOURCES (2026-09-24). Outside a session: the live feed, as it comes, even
 * when it is not smooth. INSIDE a session: the RECORDING — every frame is
 * written to disk first (camera/recording.py) and read back from there, so
 * what is watched is what was saved and what uploads. A scrubber walks back
 * through the session's frames; Live returns to the newest.
 *
 * THE FEED IS THE WINDOW'S, NOT THIS TAB'S (2026-10-24): lib/cameraFeed.ts
 * keeps it going whichever page or tab is showing, so coming back to the
 * camera finds a current picture instead of starting from nothing. This pane
 * only renders it, and owns what is particular to looking: scrubbing back.
 */

import { useEffect, useRef, useState } from "react";
import { api, recordedFrame, type CameraRate, type DeckTiming, type RecordedFrameInfo } from "@/lib/agent";
import { useCameraFeed } from "@/lib/cameraFeed";
import { showDroneWifi } from "@/lib/droneWifi";
import { Button, Message, Spinner, StatusDot } from "@/components/ui";

/** How long a frame can be stale before the overlay stops claiming "live". */
const STALE_MS = 2000;

/**
 * How long the LAST GOOD FRAME stays on screen through a drop-out, overlaid
 * with its age. The picture holding still and saying "3 s old" is the truth;
 * blanking to "no signal" for every stall was what made the feed feel broken
 * when the drone moved quickly (2026-09-24).
 */
const HOLD_MS = 30_000;

/** Seconds as m:ss, for a frame's place in the session. */
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function CameraPane({ active }: {
  /** Whether this pane can be seen right now. Behind a hidden tab the
   *  window's feed slows down; it never stops (lib/cameraFeed.ts). */
  active: boolean;
}) {
  const { load, shown: liveShown, recording, retry } = useCameraFeed(active);
  const [now, setNow] = useState(() => Date.now());
  // What is being looked at — "live" (the newest frame) or a frame number,
  // scrubbed back to — and that scrubbed frame, fetched once from disk.
  const [view, setView] = useState<"live" | number>("live");
  const [viewInfo, setViewInfo] = useState<RecordedFrameInfo | null>(null);
  const [scrubShown, setScrubShown] = useState<{ url: string; at: number } | null>(null);
  const recordingOn = recording?.recording === true;
  // The scrubber walks back through this session's saved frames. Hidden until
  // asked for: watching live does not need it (2026-09-24, "why the dial?").
  const [showBacklog, setShowBacklog] = useState(false);

  useEffect(() => {
    if (!recordingOn) setView("live");
  }, [recordingOn]);

  // A scrubbed-to frame: fetched once, from disk.
  useEffect(() => {
    if (view === "live") return;
    let stopped = false;
    void (async () => {
      const [blob, info] = await Promise.all([
        recordedFrame(view).catch(() => null),
        api.recordedFrames(view - 1, 1).then((r) => r.frames[0] ?? null).catch(() => null),
      ]);
      if (stopped) return;
      if (blob) {
        const url = URL.createObjectURL(blob);
        setScrubShown((previous) => {
          if (previous) URL.revokeObjectURL(previous.url);
          return { url, at: Date.now() };
        });
      }
      setViewInfo(info);
    })();
    return () => { stopped = true; };
  }, [view]);

  // Release the scrubbed frame's object URL when the pane goes away. The live
  // one is the feed's, and outlives this pane.
  const scrubRef = useRef(scrubShown);
  scrubRef.current = scrubShown;
  useEffect(() => () => { if (scrubRef.current) URL.revokeObjectURL(scrubRef.current.url); }, []);

  const live = load.kind === "ready" && load.status.live;
  const shown = view === "live" ? liveShown : scrubShown;

  // A clock for the frame's age, only while there is a frame to age.
  useEffect(() => {
    if (!active || shown === null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [active, shown]);

  const scrubbed = view !== "live";
  const age = shown === null ? null : Math.max(0, now - shown.at);
  // A scrubbed frame is old by design — never "stale", never "reconnecting".
  const fresh = scrubbed || (age !== null && age < STALE_MS);
  // The last frame stays up through a drop-out, for HOLD_MS.
  const holding = shown !== null && (scrubbed || (age !== null && age < HOLD_MS));

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
                <Button onClick={retry}>Try again</Button>
              </div>
            </div>
          )}

          {load.kind === "ready" && !load.status.live && !holding && load.status.connecting && (
            // Working towards a picture — say so, and why it takes a moment.
            <div className="absolute inset-0 grid content-center justify-items-center gap-3 px-6 text-center">
              <Spinner label="Connecting to the camera…" />
              {load.status.reason && (
                <p className="text-xs leading-relaxed text-[var(--console-dim)]">{load.status.reason}</p>
              )}
            </div>
          )}

          {load.kind === "ready" && !load.status.live && !holding && !load.status.connecting && (
            <div className="absolute inset-0 grid content-center gap-3 px-6 text-center">
              <p className="mono text-xs uppercase tracking-[0.1em] text-[var(--console-dim)]">
                No signal
              </p>
              <p className="text-sm leading-relaxed text-[var(--console-ink)]">
                {load.status.reason ?? "No camera is connected."}
              </p>
              <DeckLine fitted={load.status.deck_fitted} lost={load.status.decks_lost === true} />
              <DeckSays lines={load.status.deck?.lines ?? []} />

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
              {scrubbed && (
                <p className="mono absolute left-2 top-2 border border-[var(--console-line)] bg-[var(--console)] px-2 py-1 text-[10px] uppercase tracking-[0.08em] text-[var(--console-ink)]">
                  Recorded · frame {view}{viewInfo ? ` · ${clock(viewInfo.t_s)}` : ""}
                </p>
              )}
              {!fresh && age !== null && (
                <p
                  role="status"
                  className="mono absolute left-2 top-2 border border-[var(--console-line)] bg-[var(--console)] px-2 py-1 text-[10px] uppercase tracking-[0.08em] text-[var(--console-ink)]"
                >
                  {/* Said, never silent: a picture that just stops moving is
                      the freeze operators reported (2026-10-24). */}
                  {load.kind === "ready" && load.status.connecting ? "Reconnecting" : "Camera stalled"}
                  {" · no new frame for "}{(age / 1000).toFixed(1)} s
                </p>
              )}
            </>
          )}

          {!holding && !live && <Reticle dim />}
        </div>
      </div>

      {recording?.recording && recording.latest_seq > 0 && showBacklog && (
        <Backlog
          latest={recording.latest_seq}
          latestT={recording.latest_t_s}
          view={view}
          onView={setView}
        />
      )}

      <div className="mono flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-[var(--console-line)] bg-[var(--console)] px-3 py-1.5 text-[10px] uppercase tracking-[0.08em]">
        <span className="text-[var(--console-dim)]">
          {load.kind === "ready" && load.status.live
            ? [load.status.kind, load.status.width && load.status.height
                ? `${load.status.width}×${load.status.height}` : null]
                .filter(Boolean).join(" · ")
            : "AI deck · not connected"}
        </span>
        {recordingOn && (
          <button
            type="button"
            onClick={() => { setShowBacklog((v) => !v); if (showBacklog) setView("live"); }}
            aria-pressed={showBacklog}
            className="min-h-8 px-1 uppercase tracking-[0.08em] text-[var(--console-ink)] underline underline-offset-2"
          >
            {showBacklog ? "Hide history" : "History"}
          </button>
        )}
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
      {load.kind === "ready" && (load.status.rate?.frames || load.status.deck_timing) ? (
        <RateLine rate={load.status.rate ?? null} timing={load.status.deck_timing ?? null} />
      ) : null}
    </div>
  );
}

/**
 * How fast the feed really is, from both ends (agent camera/rate.py): what
 * arrives here, and what the GAP8 says each frame cost it. The line that
 * says whether the camera, the encoder or the Wi-Fi is the slow part.
 */
function RateLine({ rate, timing }: { rate: CameraRate | null; timing: DeckTiming | null }) {
  const arriving = rate && rate.frames > 0
    ? [`${rate.fps.toFixed(1)} fps`,
       rate.mean_bytes !== null ? `${Math.round(rate.mean_bytes / 1024)} KB ${rate.format ?? ""}`.trim() : null,
       rate.longest_gap_s !== null ? `longest gap ${rate.longest_gap_s.toFixed(1)} s` : null]
      .filter(Boolean).join(" · ")
    : "no frames in the last 10 s";
  const deck = timing
    ? `deck: capture ${Math.round(timing.capture_ms)} · encode ${Math.round(timing.encoding_ms)} · send ${Math.round(timing.transfer_ms)} ms`
      + (timing.deck_fps !== null ? ` (≤ ${timing.deck_fps.toFixed(1)} fps)` : "")
    : null;
  return (
    <p className="mono flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--console-line)] bg-[var(--console)] px-3 py-1.5 text-[10px] uppercase tracking-[0.08em] text-[var(--console-ink)]">
      <span>{arriving}</span>
      {deck && <span>{deck}</span>}
    </p>
  );
}

/**
 * The session's frames, as a scrubber: step back, drag, or return to Live.
 * The frames are on disk (camera/recording.py); this only chooses which one.
 */
function Backlog({ latest, latestT, view, onView }: {
  latest: number;
  latestT: number | null;
  view: "live" | number;
  onView: (view: "live" | number) => void;
}) {
  const at = view === "live" ? latest : view;
  const step = (delta: number) => {
    const next = Math.min(latest, Math.max(1, at + delta));
    onView(next >= latest && delta > 0 ? "live" : next);
  };
  const button = "mono min-h-8 min-w-8 border border-[var(--console-line)] px-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--console-ink)] disabled:opacity-40";
  return (
    <div className="flex items-center gap-2 border-t border-[var(--console-line)] bg-[var(--console)] px-3 py-1.5">
      <button type="button" className={button} onClick={() => step(-1)} disabled={at <= 1}
        aria-label="Previous frame">◀</button>
      <input
        type="range"
        min={1}
        max={latest}
        value={at}
        onChange={(e) => {
          const seq = Number(e.target.value);
          onView(seq >= latest ? "live" : seq);
        }}
        aria-label="Recorded frame"
        aria-valuetext={`Frame ${at} of ${latest}`}
        className="min-w-0 flex-1 accent-[var(--primary)]"
      />
      <button type="button" className={button} onClick={() => step(1)} disabled={view === "live"}
        aria-label="Next frame">▶</button>
      <span className="mono shrink-0 text-[10px] uppercase tracking-[0.08em] text-[var(--console-dim)]">
        {at}/{latest}{latestT !== null ? ` · ${clock(latestT)}` : ""}
      </span>
      <button
        type="button"
        onClick={() => onView("live")}
        aria-pressed={view === "live"}
        className={`${button} ${view === "live" ? "border-[var(--status-critical)]" : ""}`}
      >
        <span aria-hidden="true" style={{ color: "var(--status-critical)" }}>● </span>Live
      </button>
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
function DeckLine({ fitted, lost }: { fitted: boolean | null; lost: boolean }) {
  // One line. The long explanation of why frames need Wi-Fi lives in
  // camera.txt, not on an operator's screen every time the feed is down.
  // LOST is not "not fitted": the drone had it a moment ago (2026-10-24 — a
  // restart over the radio unpowered the decks and this read "no camera").
  const text = fitted === null ? "AI deck: not asked yet"
    : fitted ? "AI deck: fitted"
    : lost ? "AI deck: not detected now — unplug the battery for 10 seconds"
    : "AI deck: not fitted — no camera on this drone";
  return (
    <p className="mono text-[10px] uppercase tracking-[0.08em] text-[var(--console-dim)]">
      {text}
    </p>
  );
}

/**
 * The deck's own last words on the drone's console — what its Wi-Fi chip and
 * camera chip said (agent camera/diagnose.py). Shown only with no picture:
 * it is the evidence behind the reason above it.
 */
function DeckSays({ lines }: { lines: string[] }) {
  if (lines.length === 0) return null;
  return (
    <div className="grid gap-1 text-left">
      <p className="mono text-[10px] uppercase tracking-[0.08em] text-[var(--console-dim)]">The drone says</p>
      <ul className="mono max-h-24 overflow-y-auto text-[10px] leading-relaxed text-[var(--console-ink)]">
        {lines.slice(-5).map((line, i) => <li key={i} className="wrap-anywhere">{line}</li>)}
      </ul>
    </div>
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
