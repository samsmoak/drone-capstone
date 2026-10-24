/**
 * The left half of the Control page: what the drone is telling us.
 *
 * Two views behind one tab strip, because they answer different questions and
 * only one is wanted at a time:
 *
 *   Vitals   how it is sitting (the attitude indicator), what we asked it to
 *            do (the command log), and what it is reporting (the vitals tail)
 *            — in Manual, the room in place of the tail (ManualMap.tsx)
 *   Camera   what it can see — see camera.txt for why that is a test pattern
 *
 * There was a third, Scene: the drone in a declared 4 m box. Manual's room
 * answers the same question from the base stations, so it was deleted
 * (2026-10-24, Samuel: "it's of no use"); Auto never showed it.
 *
 * The panels are hidden rather than unmounted on a tab switch, so the command
 * log keeps its scroll position and the room its trail.
 *
 * TWO THINGS THE OPERATOR OWNS. The Vitals tab carries a draggable divider
 * between the attitude indicator and the log — drag it up mid-flight to read
 * more of the log, down to watch the horizon — and the whole console opens full
 * screen, because a camera frame or a 3D scene in part of a split column is a
 * thumbnail.
 */

import { useState, type ReactNode } from "react";
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
import { VitalsTail } from "./VitalsTail";

export type ConsoleTab = "vitals" | "camera";

const TABS: readonly TabDef<ConsoleTab>[] = [
  { key: "vitals", label: "Vitals" },
  { key: "camera", label: "Camera" },
];

const TAB_LABEL: Record<ConsoleTab, string> = {
  vitals: "Vitals", camera: "Camera",
};

/**
 * Which tab to open on.
 *
 * Always "vitals" in the app — index.html is loaded with no query string. The
 * override exists for the harness, which has to be able to put the Camera tab
 * on screen to measure or screenshot it: it is behind a click that a headless
 * browser cannot easily make.
 */
function initialTab(views: readonly ConsoleTab[]): ConsoleTab {
  const wanted = new URLSearchParams(window.location.search).get("tab");
  const asked = wanted === "camera" ? wanted : "vitals";
  return views.includes(asked) ? asked : views[0];
}

const ALL_VIEWS: readonly ConsoleTab[] = ["vitals", "camera"];

export function ConsolePane({
  telemetry, history, logLines, onClearLog, fill = false, views = ALL_VIEWS, map,
}: {
  /** Manual: the room map, between the attitude indicator and the command
   *  log, in place of the vitals tail (ManualMap.tsx — 2026-10-24, Samuel:
   *  "remove that vitals, and the bottom should just be the command log …
   *  the 3D, 2D editor should sit right below the gyro display"). The vitals
   *  are in the strip on the right (VitalsNow), so nothing is lost. */
  map?: ReactNode;
  telemetry: Telemetry | null;
  history: History;
  logLines: LogLine[];
  onClearLog: () => void;
  /** Fill the height a parent gives it (the split) instead of setting its own.
   *  Stacked, there is no parent height to fill, so it sets one. */
  fill?: boolean;
  /** Which tabs to offer (both, unless a caller narrows it). */
  views?: readonly ConsoleTab[];
}) {
  const [tab, setTab] = useState<ConsoleTab>(() => initialTab(views));
  const tabs = TABS.filter((t) => views.includes(t.key));
  const [full, setFull] = useState(false);

  /** `fullScreen` suppresses the controls that would be meaningless inside the
   *  overlay — a second "full screen" button, and the log's own. */
  const body = (fullScreen: boolean) => (
    <>
      <TabPanel id="console" tabKey="vitals" active={tab === "vitals"} className="flex min-h-0 flex-1 flex-col">
        <SplitPane
          orientation="horizontal"
          // Enough for the attitude indicator AND its compass strip (N/E/S/W)
          // in a one-window console at 900 px; 0.34 cut the compass letters
          // once the console stopped growing (2026-09-24). A saved position
          // still wins. With Manual's room below it, a smaller share: the
          // room is what is flown from (its own key, so Auto's is kept).
          storageKey={map ? "cropwatcher.split.console.manual" : "cropwatcher.split.console"}
          defaultFraction={map ? 0.34 : 0.42}
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
          second={map ? (
            // Manual: the room, then the log — the room first and larger, it
            // is what the operator flies from.
            <SplitPane
              orientation="horizontal"
              storageKey="cropwatcher.split.maplog"
              defaultFraction={0.72}
              min={0.15}
              max={0.94}
              label="Room map and command log"
              className="min-h-0 flex-1"
              first={
                <div className="console-scroll flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
                  <PaneTitle>Room — from the base stations</PaneTitle>
                  {/* A flex column all the way down, so the map fills what the
                      dividers give it rather than scrolling at a fixed height. */}
                  <div className="flex min-h-0 flex-1 flex-col p-2">{map}</div>
                </div>
              }
              second={
                <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                  <PaneTitle>Command log</PaneTitle>
                  <CommandLog lines={logLines} onClear={onClearLog} canExpand={!fullScreen} />
                </div>
              }
            />
          ) : (
            // The log and the vitals tail, with the same kind of divider as
            // the one above: drag it up and the vitals tail folds over the log,
            // down and the log takes the room (2026-09-24).
            <SplitPane
              orientation="horizontal"
              storageKey="cropwatcher.split.logtail"
              defaultFraction={0.67}
              min={0.06}
              max={0.94}
              label="Command log and vitals"
              className="min-h-0 flex-1"
              // min-w-0 on both: each is a child of the split's row, and without
              // it the log's widest line set its width — 488 px in a 446 px pane
              // at the window's 720 px minimum (measured 2026-09-28).
              first={
                <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                  <PaneTitle>Command log</PaneTitle>
                  <CommandLog lines={logLines} onClear={onClearLog} canExpand={!fullScreen} />
                </div>
              }
              second={
                <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                  <PaneTitle>Vitals</PaneTitle>
                  <VitalsTail history={history} />
                </div>
              }
            />
          )}
        />
      </TabPanel>

      <TabPanel id="console" tabKey="camera" active={tab === "camera"} className="flex min-h-0 flex-1 flex-col">
        <CameraPane active={tab === "camera"} />
      </TabPanel>

    </>
  );

  const strip = (fullScreen: boolean) => (
    <Tabs
      id="console"
      label="Drone console view"
      tabs={tabs}
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
              aria-label="Show this view full screen"
              className="mono min-h-8 min-w-8 whitespace-nowrap px-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--muted)] hover:text-[var(--foreground)]"
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
