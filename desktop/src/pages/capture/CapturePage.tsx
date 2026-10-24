/**
 * CAPTURE — its own page, in the sidebar (2026-10-24, Samuel: "someone can
 * click start a session and start capturing images in it … if they just want
 * to manually capture images, they can just start a session in the manual
 * capture image page and capture the images and end the session there and
 * move out").
 *
 * The live camera, a Capture button, and this session's captures — with the
 * session itself started and ended here. It is the same session Control runs:
 * one at a time on the agent, so a session started on Control is joined here,
 * and one started here can be flown from Control. Capturing needs a session —
 * standby records nothing, by hand or otherwise — and the button says so.
 *
 * A session's recording opens once the checks pass (agent session.py), before
 * the area is confirmed: confirming is for flying, so it is not asked here.
 *
 * NO KEYBOARD SHORTCUT for Capture. App.tsx's flight keys listen on every page
 * and are locked (CLAUDE.md, manual flight control), so capturing is a button.
 * The flight keys still work here — L lands.
 */

import { useCallback, useEffect, useState } from "react";
import type { Run } from "@/App";
import { AgentError, api, recordedFrame, type Session } from "@/lib/agent";
import { useCameraFeed } from "@/lib/cameraFeed";
import { sessionOpen } from "@/lib/sessionMode";
import { Button, Message, PageHeader, Panel, Spinner, StatusDot } from "@/components/ui";
import { CaptureGallery, type GalleryLoad } from "@/components/CaptureGallery";
import { CameraPane } from "@/pages/control/CameraPane";
import { CaptureSwitch } from "@/pages/control/DataPipeline";

/** How often the session's captures are re-read while the page shows. */
const CAPTURES_MS = 3000;

export function CapturePage({ session, run, onOpenControl }: {
  session: Session;
  run: Run;
  onOpenControl: () => void;
}) {
  const { load: camera } = useCameraFeed(true);
  const inSession = session.session_id !== null;
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

  const live = camera.kind === "ready" && camera.status.live;
  const captureReason = session.state === "signed_out"
    ? "Sign in first — captures are saved against a person."
    : !inSession
      ? "Start a session first: captures are saved into a session."
      : !live
        ? "Waiting for the camera — there is no picture to capture."
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
        Take pictures with the drone's camera by hand. Start a session here, capture what you need,
        then end it — each picture is saved on this computer, labelled as captured manually, and
        uploaded with the session.
      </PageHeader>

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
            <div className="border-t border-[var(--border)] px-4 py-3">
              <CaptureSwitch session={session} run={run} />
            </div>
          </Panel>

          <Panel title={count ? `Captured manually · ${count}` : "Captured manually"}
                 note={inSession ? "This session's captures, newest first." : undefined}>
            <CaptureGallery
              load={gallery}
              read={recordedFrame}
              onRetry={() => void readCaptures()}
              emptyText={inSession
                ? "Nothing captured yet this session. Press Capture to save the picture you see."
                : "Start a session to capture. Captures from earlier sessions are in Sessions."}
            />
          </Panel>
        </div>
      </div>
    </div>
  );
}

/** Where the session is, and starting or ending it — from this page. */
function SessionStrip({ session, run, onOpenControl, count }: {
  session: Session;
  run: Run;
  onOpenControl: () => void;
  count: number | null;
}) {
  const inSession = session.session_id !== null;
  const busy = session.state === "busy";
  const mode = session.mode === "auto" ? "Auto" : "Manual";

  if (session.state === "signed_out") {
    return (
      <Panel title="Session">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm">Sign in to start a session. Captures are recorded against the person who took them.</p>
          <Button onClick={onOpenControl}>Sign in on Control</Button>
        </div>
      </Panel>
    );
  }

  if (session.state === "starting") {
    return <Panel title="Session"><Spinner label="Checking the drone — keep it still…" /></Panel>;
  }

  if (session.state === "checks_failed") {
    return (
      <Panel title="Session">
        <div className="grid gap-2">
          <Message tone="critical" text={session.message ?? "The checks did not pass."} />
          <div className="flex flex-wrap gap-2">
            {session.session_id
              ? <Button variant="primary" onClick={() => void run(api.retry, "Retry the checks")}>Retry</Button>
              : <Button variant="primary" onClick={() => void run(api.start, "Start session")}>Try again</Button>}
            <Button onClick={onOpenControl}>Open Control</Button>
          </div>
        </div>
      </Panel>
    );
  }

  if (!inSession || !sessionOpen(session)) {
    return (
      <Panel title="Session">
        <div className="flex flex-wrap items-center gap-3">
          <StatusDot tone="idle">No session</StatusDot>
          <Button variant="primary" onClick={() => void run(api.start, "Start session")}
                  disabled={session.state !== "idle"}>
            Start session
          </Button>
          <span className="text-xs text-[var(--muted)]">
            Runs the drone's checks, then records. Starts a {mode} session — change the mode in the sidebar first.
          </span>
        </div>
      </Panel>
    );
  }

  return (
    <Panel title="Session">
      <div className="flex flex-wrap items-center gap-3">
        <StatusDot tone="good">In a {mode} session{count !== null ? ` · ${count} captured by hand` : ""}</StatusDot>
        <Button variant="danger" onClick={() => void run(api.endSession, "End session")}
                disabled={busy || session.state === "ending"}
                title={busy ? "Land the drone first (L)." : undefined}>
          {session.state === "ending" ? "Ending…" : "End session"}
        </Button>
        <Button onClick={onOpenControl}>Fly it on Control →</Button>
        {busy && <span role="status" className="text-xs">Flying — land the drone (L) before ending the session.</span>}
        {session.state === "awaiting_confirmation" && (
          <span className="text-xs text-[var(--muted)]">Recording. To fly, confirm the area on Control.</span>
        )}
      </div>
    </Panel>
  );
}
