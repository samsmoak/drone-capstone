/**
 * CAPTURE — its own page, in the sidebar, with its OWN session (2026-10-24,
 * Samuel: "the capture page only cares about taking picture manually and not
 * the rest").
 *
 * Three things only: is the drone reachable (radio), is its camera on the
 * network (Wi-Fi), is the picture coming (camera) — then Capture, and this
 * session's pictures. No flight checklist, no auto-capture switch, nothing
 * about flying.
 *
 * ITS OWN SESSION. "Start capture session" starts a session whose purpose is
 * capture (agent session.py): it checks the radio and the camera's deck only
 * (checks.py run_capture_checks) — a drone that would not arm (sys.canfly=0)
 * used to keep this page from taking a single picture — keeps only what is
 * captured by hand, and the agent refuses every flight action in it. One
 * session at a time still: while it is open Control says so (CaptureLock).
 * A FLIGHT session started on Control can be captured into from here too;
 * it is ended on Control.
 *
 * NO KEYBOARD SHORTCUT for Capture. App.tsx's flight keys listen on every page
 * and are locked (CLAUDE.md, manual flight control), so capturing is a button.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { Run } from "@/App";
import { AgentError, api, recordedFrame, type CameraStatus, type CameraWifi, type Session } from "@/lib/agent";
import { useCameraFeed } from "@/lib/cameraFeed";
import { showDroneWifi } from "@/lib/droneWifi";
import { sessionOpen } from "@/lib/sessionMode";
import { Button, Message, PageHeader, Panel, Spinner, StatusDot, type Tone } from "@/components/ui";
import { CaptureGallery, type GalleryLoad } from "@/components/CaptureGallery";
import { CameraPane } from "@/pages/control/CameraPane";

/** How often the session's captures are re-read while the page shows. */
const CAPTURES_MS = 3000;

export function CapturePage({ session, run, onOpenControl }: {
  session: Session;
  run: Run;
  onOpenControl: () => void;
}) {
  const { load: camera } = useCameraFeed(true);
  const inSession = session.session_id !== null && sessionOpen(session);
  const [gallery, setGallery] = useState<GalleryLoad>({ kind: "loading" });
  const [capturing, setCapturing] = useState(false);
  const [captureMessage, setCaptureMessage] = useState<{ tone: "good" | "critical"; text: string } | null>(null);

  const readCaptures = useCallback(async () => {
    if (!inSession) {
      setGallery({ kind: "ready", frames: [] });
      return;
    }
    try {
      setGallery({ kind: "ready", frames: (await api.manualCaptures()).frames });
    } catch (e) {
      setGallery({ kind: "error", message: e instanceof AgentError ? e.message : "The captures could not be read." });
    }
  }, [inSession]);

  useEffect(() => {
    void readCaptures();
    if (!inSession) return;
    const timer = window.setInterval(() => void readCaptures(), CAPTURES_MS);
    return () => window.clearInterval(timer);
  }, [inSession, readCaptures, session.session_id]);

  const status = camera.kind === "ready" ? camera.status : null;
  const wifi = camera.kind === "ready" ? camera.wifi : null;
  const live = status?.live === true;
  const captureReason = session.state === "signed_out"
    ? "Sign in first — pictures are saved against a person."
    : !inSession
      ? "Start a capture session first: pictures are saved into a session."
      : !live
        ? "Waiting for the camera — there is no picture to capture yet."
        : null;

  const capture = async () => {
    setCapturing(true);
    setCaptureMessage(null);
    try {
      const frame = await api.captureFrame();
      setCaptureMessage({ tone: "good", text: `Captured · frame ${frame.seq}` });
      await readCaptures();
    } catch (e) {
      setCaptureMessage({ tone: "critical", text: e instanceof AgentError ? e.message : "The frame could not be captured." });
    } finally {
      setCapturing(false);
    }
  };

  const count = gallery.kind === "ready" ? gallery.frames.length : null;
  const sessionTile = sessionTileOf(session, run, onOpenControl, count);

  return (
    <div className="grid gap-4">
      <PageHeader eyebrow="Operate" title="Capture">
        Take pictures with the drone's camera by hand. Each one is saved on this computer, labelled as
        captured manually, and uploaded with its session. Nothing here flies the drone.
      </PageHeader>

      {/* ONE ROW OF FOUR, all the same (2026-10-24, Samuel: "more beautiful
          and uniform"): what a picture needs, and the session it goes into,
          each a tile with the same label, status and place for its action. */}
      <Tiles tiles={[...readinessTiles(session, wifi, status), sessionTile.tile]} />
      {sessionTile.detail}

      <div className="@container">
        <div className="grid items-start gap-4 @4xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          {/* Capture sits right above the picture it takes — one glance,
              never a scroll apart (the camera's own stats run below it) —
              and out of the header, so both panels' headers match. */}
          <Panel title="Camera" bodyClassName="flex min-h-[360px] flex-col">
            <div className="grid gap-2 border-b border-[var(--border)] px-4 py-3">
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" onClick={() => void capture()} disabled={capturing || captureReason !== null}
                        title={captureReason ?? undefined}>
                  {capturing ? "Capturing…" : "Capture"}
                </Button>
                {captureReason
                  ? <p role="status" className="text-sm">{captureReason}</p>
                  : captureMessage?.tone === "good"
                    ? <p role="status" className="text-sm"><StatusDot tone="good">{captureMessage.text}</StatusDot></p>
                    : <p className="text-sm">Saves the picture you see now.</p>}
              </div>
              {captureMessage?.tone === "critical" && <Message tone="critical" text={captureMessage.text} />}
            </div>
            <CameraPane active />
          </Panel>

          <Panel title="Captured manually"
                 action={count !== null ? <span className="mono text-sm font-semibold">{count}</span> : undefined}
                 note={inSession ? "This session's pictures, newest first." : undefined}>
            <CaptureGallery
              load={gallery}
              read={recordedFrame}
              onRetry={() => void readCaptures()}
              emptyText={inSession
                ? "Nothing captured yet this session. Press Capture to save the picture you see."
                : "Start a capture session to take pictures. Earlier sessions' pictures are in Sessions."}
            />
          </Panel>
        </div>
      </div>
    </div>
  );
}

type Tile = { label: string; tone: Tone; text: string; action?: ReactNode };

/** Tiles of equal weight in one bordered strip: one row of four when there is
 *  room, two by two, or one column. The hairlines are the strip's own colour
 *  showing through a 1 px gap, so every edge is the same at every width. */
function Tiles({ tiles }: { tiles: Tile[] }) {
  return (
    <section aria-label="Ready to capture" className="@container border border-[var(--border)] bg-[var(--border)]">
      <ul className="grid gap-px @2xl:grid-cols-2 @5xl:grid-cols-4">
        {tiles.map((t) => (
          <li key={t.label} className="flex min-w-0 flex-col justify-between gap-2 bg-[var(--surface)] px-4 py-3">
            <div className="grid min-w-0 gap-1">
              <p className="eyebrow">{t.label}</p>
              <p className="wrap-anywhere text-sm"><StatusDot tone={t.tone}>{t.text}</StatusDot></p>
            </div>
            {t.action && <div className="flex flex-wrap gap-2">{t.action}</div>}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The three things a picture needs, each as the agent reports it now: the
 * drone reachable over the radio, its camera on the network, the picture
 * coming. Each says what is wrong in its own words, and where to fix it.
 */
function readinessTiles(session: Session, wifi: CameraWifi | null, camera: CameraStatus | null): Tile[] {
  const radio = session.radio;
  const radioTile: Tile = radio?.state === "connected"
    ? { label: "Radio", tone: "good", text: `Connected${radio.hardware_id ? ` · ${radio.hardware_id}` : ""}` }
    : radio?.state === "searching" || radio?.state === "restarting"
      ? { label: "Radio", tone: "warning", text: radio.message ?? "Looking for the drone…" }
      : { label: "Radio", tone: "idle", text: radio?.message ?? "Not connected — switch the drone on." };

  const phase = wifi?.phase ?? "not-set";
  const wifiText: [Tone, string] = phase === "joined" && wifi?.ip
    ? ["good", [wifi.ssid, wifi.ip, wifi.rssi != null ? `${wifi.rssi} dBm` : null].filter(Boolean).join(" · ")]
    : phase === "failed"
      ? ["critical", wifi?.message ?? "The drone could not join its network."]
      : phase === "not-set"
        ? ["idle", "No network set for the drone's camera."]
        : ["warning", wifi?.message ?? "Joining…"];
  const wifiTile: Tile = {
    label: "Wi-Fi", tone: wifiText[0], text: wifiText[1],
    action: phase !== "joined" ? <Button onClick={showDroneWifi}>Drone Wi-Fi</Button> : undefined,
  };

  const fps = camera?.rate?.frames ? ` · ${camera.rate.fps.toFixed(1)} fps` : "";
  const cameraTile: Tile = camera?.live
    ? { label: "Camera", tone: "good", text: `Live${camera.width && camera.height ? ` · ${camera.width}×${camera.height}` : ""}${fps}` }
    : camera?.connecting
      ? { label: "Camera", tone: "warning", text: camera.reason ?? "Connecting to the camera…" }
      : { label: "Camera", tone: "idle", text: camera?.reason ?? "No picture yet." };

  return [radioTile, wifiTile, cameraTile];
}

/** The session tile — starting or ending a capture session, or, while
 *  Control's flight session is open, saying pictures go into it — and what
 *  needs more room than a tile (the checks while it starts, a failure). */
function sessionTileOf(session: Session, run: Run, onOpenControl: () => void,
                       count: number | null): { tile: Tile; detail: ReactNode } {
  const open = session.session_id !== null && sessionOpen(session);
  const capturing = session.purpose === "capture";
  const label = "Session";

  if (session.state === "signed_out") {
    return {
      tile: { label, tone: "idle", text: "Sign in to start a capture session.",
              action: <Button onClick={onOpenControl}>Sign in on Control</Button> },
      detail: null,
    };
  }
  if (session.state === "starting") {
    return {
      tile: { label, tone: "warning", text: capturing ? "Connecting to the drone and its camera…" : "Control is checking the drone…" },
      detail: session.checks.length > 0 ? (
        <ul className="grid gap-1 border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-xs">
          {session.checks.map((c) => (
            <li key={c.key}>
              <StatusDot tone={c.status === "passed" ? "good" : c.status === "failed" ? "critical" : c.status === "warning" ? "warning" : "idle"}>
                {c.label}{c.detail ? ` — ${c.detail}` : ""}
              </StatusDot>
            </li>
          ))}
        </ul>
      ) : <Spinner label="Starting…" />,
    };
  }
  if (session.state === "checks_failed" && capturing) {
    return {
      tile: {
        label, tone: "critical", text: "Could not start",
        action: session.session_id
          ? <Button variant="primary" onClick={() => void run(api.retry, "Retry")}>Try again</Button>
          : <Button variant="primary" onClick={() => void run(() => api.start("capture"), "Start capture session")}>Try again</Button>,
      },
      detail: <Message tone="critical" text={session.message ?? "The capture session could not start."} />,
    };
  }
  if (open && !capturing) {
    // Control's flight session: pictures go into it; it is ended on Control.
    return {
      tile: { label, tone: "good", text: `In Control's session${count !== null ? ` · ${count} by hand` : ""}`,
              action: <Button onClick={onOpenControl}>Open Control →</Button> },
      detail: null,
    };
  }
  if (open) {
    return {
      tile: {
        label, tone: "good", text: `Capture session open${count !== null ? ` · ${count} captured` : ""}`,
        action: (
          <Button variant="danger" onClick={() => void run(api.endSession, "End capture session")}
                  disabled={session.state === "ending"}>
            {session.state === "ending" ? "Ending…" : "End capture session"}
          </Button>
        ),
      },
      detail: null,
    };
  }
  return {
    tile: {
      label, tone: "idle", text: "No session — connects to the drone and its camera; nothing flies.",
      action: (
        <Button variant="primary" onClick={() => void run(() => api.start("capture"), "Start capture session")}
                disabled={session.state !== "idle" && session.state !== "checks_failed"}>
          Start capture session
        </Button>
      ),
    },
    detail: null,
  };
}
