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

import { useCallback, useEffect, useState } from "react";
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

  return (
    <div className="grid gap-4">
      <PageHeader eyebrow="Operate" title="Capture">
        Take pictures with the drone's camera by hand. Start a capture session, capture what you
        need, then end it — each picture is saved on this computer, labelled as captured manually,
        and uploaded with the session. Nothing here flies the drone.
      </PageHeader>

      <Readiness session={session} wifi={wifi} camera={status} />

      <SessionStrip session={session} run={run} onOpenControl={onOpenControl} count={count} />

      <div className="@container">
        <div className="grid gap-4 @4xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          {/* Capture is in the camera's own header: the button and the
              picture it takes are seen together, never a scroll apart. */}
          <Panel
            title="Camera"
            bodyClassName="flex min-h-[360px] flex-col"
            action={
              <Button variant="primary" onClick={() => void capture()} disabled={capturing || captureReason !== null}
                      title={captureReason ?? undefined}>
                {capturing ? "Capturing…" : "Capture"}
              </Button>
            }
          >
            {(captureReason || captureMessage) && (
              <div className="grid gap-2 border-b border-[var(--border)] px-4 py-2">
                {captureReason && <p role="status" className="text-xs">{captureReason}</p>}
                {captureMessage && <Message tone={captureMessage.tone} text={captureMessage.text} />}
              </div>
            )}
            <CameraPane active />
          </Panel>

          <Panel title={count ? `Captured manually · ${count}` : "Captured manually"}
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

/**
 * The three things a picture needs, each as the agent reports it now: the
 * drone reachable over the radio, its camera on the network, the picture
 * coming. Each says what is wrong in its own words, and where to fix it.
 */
function Readiness({ session, wifi, camera }: {
  session: Session;
  wifi: CameraWifi | null;
  camera: CameraStatus | null;
}) {
  const radio = session.radio;
  const radioRow: [Tone, string] = radio?.state === "connected"
    ? ["good", `Connected${radio.hardware_id ? ` · ${radio.hardware_id}` : ""}`]
    : radio?.state === "searching" || radio?.state === "restarting"
      ? ["warning", radio.message ?? "Looking for the drone…"]
      : ["idle", radio?.message ?? "Not connected — switch the drone on."];

  const phase = wifi?.phase ?? "not-set";
  const wifiRow: [Tone, string] = phase === "joined" && wifi?.ip
    ? ["good", [wifi.ssid, wifi.ip, wifi.rssi != null ? `${wifi.rssi} dBm` : null].filter(Boolean).join(" · ")]
    : phase === "failed"
      ? ["critical", wifi?.message ?? "The drone could not join its network."]
      : phase === "not-set"
        ? ["idle", "No network set for the drone's camera."]
        : ["warning", wifi?.message ?? "Joining…"];

  const fps = camera?.rate?.frames ? ` · ${camera.rate.fps.toFixed(1)} fps` : "";
  const cameraRow: [Tone, string] = camera?.live
    ? ["good", `Live${camera.width && camera.height ? ` · ${camera.width}×${camera.height}` : ""}${fps}`]
    : camera?.connecting
      ? ["warning", camera.reason ?? "Connecting to the camera…"]
      : ["idle", camera?.reason ?? "No picture yet."];

  const rows: [string, [Tone, string], React.ReactNode?][] = [
    ["Radio", radioRow],
    ["Wi-Fi", wifiRow, phase !== "joined" ? <Button onClick={showDroneWifi}>Drone Wi-Fi</Button> : null],
    ["Camera", cameraRow],
  ];
  return (
    <Panel title="Ready to capture" bodyClassName="grid">
      <ul className="divide-y divide-[var(--border)]" aria-label="What a picture needs">
        {rows.map(([label, [tone, text], action]) => (
          <li key={label} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-2.5">
            <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="w-16 shrink-0 text-sm font-semibold">{label}</span>
              <span className="min-w-0 text-sm"><StatusDot tone={tone}>{text}</StatusDot></span>
            </span>
            {action}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** Starting or ending a capture session — or, while Control's flight
 *  session is open, saying that pictures go into it. */
function SessionStrip({ session, run, onOpenControl, count }: {
  session: Session;
  run: Run;
  onOpenControl: () => void;
  count: number | null;
}) {
  const open = session.session_id !== null && sessionOpen(session);
  const capturing = session.purpose === "capture";

  if (session.state === "signed_out") {
    return (
      <Panel title="Session">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm">Sign in to start a capture session. Pictures are recorded against the person who took them.</p>
          <Button onClick={onOpenControl}>Sign in on Control</Button>
        </div>
      </Panel>
    );
  }

  if (session.state === "starting") {
    return (
      <Panel title="Session">
        <div className="grid gap-2">
          <Spinner label={capturing ? "Connecting to the drone and its camera…" : "Control is checking the drone…"} />
          {session.checks.length > 0 && (
            <ul className="grid gap-1 text-xs">
              {session.checks.map((c) => (
                <li key={c.key}>
                  <StatusDot tone={c.status === "passed" ? "good" : c.status === "failed" ? "critical" : c.status === "warning" ? "warning" : "idle"}>
                    {c.label}{c.detail ? ` — ${c.detail}` : ""}
                  </StatusDot>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>
    );
  }

  if (session.state === "checks_failed" && capturing) {
    return (
      <Panel title="Session">
        <div className="grid gap-2">
          <Message tone="critical" text={session.message ?? "The capture session could not start."} />
          <div className="flex flex-wrap gap-2">
            {session.session_id
              ? <Button variant="primary" onClick={() => void run(api.retry, "Retry")}>Try again</Button>
              : <Button variant="primary" onClick={() => void run(() => api.start("capture"), "Start capture session")}>Try again</Button>}
          </div>
        </div>
      </Panel>
    );
  }

  if (open && !capturing) {
    // Control's flight session: pictures go into it; it is ended on Control.
    return (
      <Panel title="Session">
        <div className="flex flex-wrap items-center gap-3">
          <StatusDot tone="good">
            In Control's session{count !== null ? ` · ${count} captured by hand` : ""}
          </StatusDot>
          <span className="text-xs text-[var(--muted)]">Pictures are saved into it. End it on Control.</span>
          <Button onClick={onOpenControl}>Open Control →</Button>
        </div>
      </Panel>
    );
  }

  if (open) {
    return (
      <Panel title="Session">
        <div className="flex flex-wrap items-center gap-3">
          <StatusDot tone="good">Capture session open{count !== null ? ` · ${count} captured` : ""}</StatusDot>
          <Button variant="danger" onClick={() => void run(api.endSession, "End capture session")}
                  disabled={session.state === "ending"}>
            {session.state === "ending" ? "Ending…" : "End capture session"}
          </Button>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="Session">
      <div className="flex flex-wrap items-center gap-3">
        <StatusDot tone="idle">No session</StatusDot>
        <Button variant="primary" onClick={() => void run(() => api.start("capture"), "Start capture session")}
                disabled={session.state !== "idle" && session.state !== "checks_failed"}>
          Start capture session
        </Button>
        <span className="text-xs text-[var(--muted)]">
          Connects to the drone and its camera — no flight checks, nothing flies.
        </span>
      </div>
    </Panel>
  );
}
