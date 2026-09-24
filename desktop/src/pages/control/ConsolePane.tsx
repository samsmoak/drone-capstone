/**
 * The left half of the Control page: what the drone is telling us.
 *
 * Three views behind one tab strip, because they answer three different
 * questions and only one is wanted at a time:
 *
 *   Vitals   how it is sitting (the attitude indicator), what we asked it to
 *            do (the command log), and what it is reporting (the vitals tail)
 *   Camera   what it can see — see camera.txt for why that is a test pattern
 *   Scene    where it is in the room, drawn
 *
 * The panels are hidden rather than unmounted on a tab switch, so the command
 * log keeps its scroll position and the scene keeps its trail.
 *
 * TWO THINGS THE OPERATOR OWNS. The Vitals tab carries a draggable divider
 * between the attitude indicator and the log — drag it up mid-flight to read
 * more of the log, down to watch the horizon — and the whole console opens full
 * screen, because a camera frame or a 3D scene in part of a split column is a
 * thumbnail.
 */

import { useState } from "react";
import type { History } from "@/App";
import type { LogLine } from "@/lib/commandLog";
import type { Telemetry } from "@/lib/agent";
import { FullScreenOverlay } from "@/components/FullScreenOverlay";
import { SplitPane } from "@/components/SplitPane";
import { TabPanel, Tabs, type TabDef } from "@/components/Tabs";
import { StatusDot } from "@/components/ui";
import { AttitudeIndicator } from "./AttitudeIndicator";
import { CameraPane } from "./CameraPane";
import { CommandLog } from "./CommandLog";
import { SceneView } from "./SceneView";
import { VitalsTail } from "./VitalsTail";

type ConsoleTab = "vitals" | "camera" | "scene";

const TABS: readonly TabDef<ConsoleTab>[] = [
  { key: "vitals", label: "Vitals" },
  { key: "camera", label: "Camera" },
  { key: "scene", label: "Scene" },
];

const TAB_LABEL: Record<ConsoleTab, string> = {
  vitals: "Vitals", camera: "Camera", scene: "Scene",
};

/**
 * Which tab to open on.
 *
 * Always "vitals" in the app — index.html is loaded with no query string. The
 * override exists for the harness, which has to be able to put the Camera and
 * Scene tabs on screen to measure or screenshot them: they are behind a click
 * that a headless browser cannot easily make, and the Scene canvas does not
 * draw at all while its tab is inactive.
 */
function initialTab(): ConsoleTab {
  const wanted = new URLSearchParams(window.location.search).get("tab");
  return wanted === "camera" || wanted === "scene" ? wanted : "vitals";
}

export function ConsolePane({
  telemetry, history, logLines, onClearLog, fill = false,
}: {
  telemetry: Telemetry | null;
  history: History;
  logLines: LogLine[];
  onClearLog: () => void;
  /** Fill the height a parent gives it (the split) instead of setting its own.
   *  Stacked, there is no parent height to fill, so it sets one. */
  fill?: boolean;
}) {
  const [tab, setTab] = useState<ConsoleTab>(initialTab);
  const [full, setFull] = useState(false);

  /** `fullScreen` suppresses the controls that would be meaningless inside the
   *  overlay — a second "full screen" button, and the log's own. */
  const body = (fullScreen: boolean) => (
    <>
      <TabPanel id="console" tabKey="vitals" active={tab === "vitals"} className="flex min-h-0 flex-1 flex-col">
        <SplitPane
          orientation="horizontal"
          storageKey="cropwatcher.split.console"
          defaultFraction={0.34}
          // Folds almost away: dragging this up to read the log is the point,
          // and the shared 20 % floor made it stop a fifth of the way down with
          // nothing to explain why. Never 0 — the divider would reach the frame
          // edge and leave no handle to bring it back.
          min={0.06}
          max={0.85}
          label="Attitude indicator and the log"
          className="min-h-0 flex-1"
          first={
            <div className="console-scroll min-h-0 flex-1 overflow-y-auto">
              <AttitudeIndicator telemetry={telemetry} />
            </div>
          }
          second={
            <div className="flex min-h-0 flex-1 flex-col">
              {/* The log takes most of what is below the divider; the tail is
                  one fixed-width line per second and needs less. */}
              <div className="flex min-h-0 flex-8 flex-col border-b border-[var(--border)]">
                <PaneTitle>Command log</PaneTitle>
                <CommandLog lines={logLines} onClear={onClearLog} canExpand={!fullScreen} />
              </div>
              <div className="flex min-h-0 flex-4 flex-col">
                <PaneTitle>Vitals</PaneTitle>
                <VitalsTail history={history} />
              </div>
            </div>
          }
        />
      </TabPanel>

      <TabPanel id="console" tabKey="camera" active={tab === "camera"} className="flex min-h-0 flex-1 flex-col">
        <CameraPane active={tab === "camera"} />
      </TabPanel>

      <TabPanel id="console" tabKey="scene" active={tab === "scene"} className="flex min-h-0 flex-1 flex-col">
        {/* `active` stops the canvas repainting behind a hidden tab — the panel
            stays mounted so the trail survives, but the loop does not run. */}
        <SceneView telemetry={telemetry} history={history} active={tab === "scene"} />
      </TabPanel>
    </>
  );

  const strip = (fullScreen: boolean) => (
    <Tabs
      id="console"
      label="Drone console view"
      tabs={TABS}
      active={tab}
      onSelect={setTab}
      action={
        <>
          <span className="mono text-[10px] uppercase tracking-[0.08em]">
            <StatusDot tone={telemetry ? "good" : "idle"}>
              {telemetry ? "10 Hz" : "no stream"}
            </StatusDot>
          </span>
          {!fullScreen && (
            <button
              type="button"
              onClick={() => setFull(true)}
              title="Show this view full screen"
              className="mono min-h-8 px-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--muted)] hover:text-[var(--foreground)]"
            >
              Full screen ⤢
            </button>
          )}
        </>
      }
    />
  );

  return (
    <>
      <section
        aria-label="Drone console"
        // Filled by the split when there is one. Stacked it sets its own: 46rem
        // is a floor, not a preference — below about that the command log and
        // the vitals tail each get fewer than four lines once their own header
        // and footer bars are subtracted, which is not a log.
        className={`flex min-w-0 flex-col overflow-hidden border border-[var(--border)] bg-[var(--surface)] ${
          fill ? "min-h-0 flex-1" : "min-h-[46rem]"
        }`}
      >
        {strip(false)}
        {body(false)}
      </section>

      {full && (
        <FullScreenOverlay label={`Console · ${TAB_LABEL[tab]}`} onClose={() => setFull(false)}>
          <div className="flex min-h-0 flex-1 flex-col bg-[var(--surface)]">
            {strip(true)}
            {body(true)}
          </div>
        </FullScreenOverlay>
      )}
    </>
  );
}

function PaneTitle({ children }: { children: string }) {
  return (
    <h3 className="mono shrink-0 border-b border-[var(--border)] bg-[var(--surface-2)] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--muted)]">
      {children}
    </h3>
  );
}
