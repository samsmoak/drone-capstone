/**
 * THE CAMERA FEED — one per window, shared by every view of it.
 *
 * WHY ONE. The Camera tab used to own the feed: it asked the agent about the
 * camera when it was shown, pulled frames only while it was the visible tab,
 * and threw everything away when it unmounted. Leaving the tab and coming back
 * therefore started from nothing — a spinner, "asking the agent", a reconnect —
 * and the camera looked as if it had switched off (2026-10-24, Samuel: "the
 * camera feed should always be on when its capturing image or not").
 *
 * It never was off: the agent keeps the deck's stream and the session's
 * recording going whatever the window shows. What stopped was the WINDOW
 * looking. Now the window keeps looking, for as long as it is open:
 *
 *   a view on screen   frames every FRAME_MS — the picture moves
 *   nothing on screen  frames every BACKGROUND_MS — so the picture a view
 *                      opens on is seconds old, not missing
 *   always             the agent's camera status every STATUS_MS, so `live`
 *                      and the reason for no picture are the agent's own,
 *                      current, answer
 *
 * In a session the newest frame comes from the RECORDING, read back from disk
 * (camera/recording.py): what is watched is what was saved. Not when the
 * session records nothing automatically (auto-capture off) — then the
 * recording only grows on a manual capture, and following it would freeze the
 * picture; the live feed is shown instead.
 */

import { useEffect, useSyncExternalStore } from "react";
import {
  api, cameraFrameUrl, recordedFrame,
  type CameraStatus, type CameraWifi, type Recording,
} from "@/lib/agent";

/** A frame every this often while a view of the camera is on screen. */
export const FRAME_MS = 200;
/** ...and this often while none is, so a view opens on a recent picture. */
export const BACKGROUND_MS = 2000;
/** How often the agent is asked about the camera itself. */
const STATUS_MS = 2000;
/** How often the session's recording is asked about, on screen and off. */
const RECORDING_MS = 1000;
const RECORDING_BACKGROUND_MS = 5000;

export type FeedLoad =
  | { kind: "probing" }
  | { kind: "error"; message: string }
  | { kind: "ready"; status: CameraStatus; wifi: CameraWifi | null };

export type FeedState = {
  load: FeedLoad;
  /** The last frame that arrived whole, as an object URL, and when (epoch ms). */
  shown: { url: string; at: number } | null;
  recording: Recording | null;
};

let state: FeedState = { load: { kind: "probing" }, shown: null, recording: null };
const listeners = new Set<() => void>();
let viewers = 0;
let started = false;
/** The recorded frame on screen: a recorded frame is NEW only when this rises.
 *  "latest" keeps answering with the last frame after the deck stalls, and
 *  taking that as fresh would present a frozen picture as live. */
let shownSeq = 0;
/** Wakes the frame loop at once: a view appeared, or the feed came back. */
let wake: (() => void) | null = null;

function set(patch: Partial<FeedState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

function show(blob: Blob) {
  const url = URL.createObjectURL(blob);
  if (state.shown) URL.revokeObjectURL(state.shown.url);
  set({ shown: { url, at: Date.now() } });
}

const pause = (ms: number) => new Promise<void>((resolve) => {
  const timer = window.setTimeout(done, ms);
  function done() { window.clearTimeout(timer); wake = null; resolve(); }
  wake = done;
});

/** Ask the agent about the camera now. `quiet` keeps the last answer on screen
 *  while asking, so the background poll never flashes a spinner. */
async function probe(quiet = true) {
  if (!quiet) set({ load: { kind: "probing" } });
  try {
    const [status, wifi] = await Promise.all([
      api.cameraStatus(),
      // Where the deck is in joining the operator's network. Optional: the
      // camera still works on the deck's own access point without it.
      api.cameraWifi().catch(() => null),
    ]);
    const wasLive = state.load.kind === "ready" && state.load.status.live;
    set({ load: { kind: "ready", status, wifi } });
    if (status.live && !wasLive) wake?.();
  } catch (e) {
    set({ load: { kind: "error", message: e instanceof Error ? e.message : "Could not ask the agent about the camera." } });
  }
}

/** Follow the recording, if any — from the frames on disk. False when the
 *  session's frames are not recorded automatically: then live is shown. */
function followsRecording(r: Recording | null): r is Extract<Recording, { recording: true }> {
  return r !== null && r.recording && r.auto !== false;
}

async function frameLoop() {
  for (;;) {
    const live = state.load.kind === "ready" && state.load.status.live;
    if (live) {
      try {
        let blob: Blob | null = null;
        if (followsRecording(state.recording)) {
          const now = await api.cameraRecording();
          set({ recording: now });
          if (followsRecording(now) && now.latest_seq > shownSeq) {
            blob = await recordedFrame(now.latest_seq);
            if (blob) shownSeq = now.latest_seq;
          }
        } else {
          const response = await fetch(cameraFrameUrl(Date.now()), { cache: "no-store" });
          if (response.status === 200) blob = await response.blob();
        }
        // A failed or empty request never replaces the picture: the last good
        // frame stays up and ages, which is the truth about a stalled feed.
        if (blob) show(blob);
      } catch {
        // The status poll says why, in the agent's words.
      }
    }
    await pause(live ? (viewers > 0 ? FRAME_MS : BACKGROUND_MS) : 500);
  }
}

async function statusLoop() {
  for (;;) {
    await probe(true);
    await new Promise((r) => window.setTimeout(r, STATUS_MS));
  }
}

async function recordingLoop() {
  for (;;) {
    try {
      const r = await api.cameraRecording();
      if (!(r.recording && state.recording?.recording && r.session_id === state.recording.session_id)) {
        shownSeq = 0;                 // a new session, or none: start from its newest frame
      }
      set({ recording: r });
    } catch {
      set({ recording: null });
    }
    await new Promise((r) => window.setTimeout(r, viewers > 0 ? RECORDING_MS : RECORDING_BACKGROUND_MS));
  }
}

function start() {
  if (started) return;
  started = true;
  void frameLoop();
  void statusLoop();
  void recordingLoop();
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  start();
  return () => listeners.delete(onChange);
}

/**
 * The window's camera feed. `onScreen`: whether this view can be seen right
 * now — a view behind a hidden tab says false, and the feed slows down rather
 * than stopping.
 */
export function useCameraFeed(onScreen: boolean): FeedState & { retry: () => void } {
  const snapshot = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    if (!onScreen) return;
    viewers += 1;
    wake?.();
    return () => { viewers -= 1; };
  }, [onScreen]);
  return { ...snapshot, retry: () => void probe(false) };
}
