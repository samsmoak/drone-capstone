/**
 * The left half of the Control page: what the drone is telling us.
 *
 * Three views behind one tab strip, because they answer three different
 * questions and only one is wanted at a time:
 *
 *   Vitals   how it is sitting (the attitude indicator), what we asked it to
 *            do (the command log), and what it is reporting (the vitals tail)
 *   Camera   what it can see — see CameraPane for why that is empty today
 *   Scene    where it is in the room, drawn
 *
 * The panels are hidden rather than unmounted on a tab switch, so the command
 * log keeps its scroll position and the scene keeps its trail.
 */

import { useState } from "react";
import type { History } from "@/App";
import type { LogLine } from "@/lib/commandLog";
import type { Session, Telemetry } from "@/lib/agent";
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

/**
 * Which tab to open on.
 *
 * Always "vitals" in the app — index.html is loaded with no query string. The
 * override exists for the harness, which has to be able to put the Camera and
 * Scene tabs on screen to measure or screenshot them: they are behind a click
 * that a headless browser cannot easily make, and the Scene canvas does not
 * draw at all while its tab is inactive.
 *
 * Same spirit as `?agent=` and `?measure=` — see harness.tsx and measure.ts.
 */
function initialTab(): ConsoleTab {
  const wanted = new URLSearchParams(window.location.search).get("tab");
  return wanted === "camera" || wanted === "scene" ? wanted : "vitals";
}

export function ConsolePane({
  session, telemetry, history, logLines, onClearLog,
}: {
  session: Session | null;
  telemetry: Telemetry | null;
  history: History;
  logLines: LogLine[];
  onClearLog: () => void;
}) {
  const [tab, setTab] = useState<ConsoleTab>(initialTab);

  return (
    <section
      aria-label="Drone console"
      // A DEFINITE height, so the three scrolling panes inside can share it —
      // they are all min-h-0 flex children and would otherwise collapse to
      // their content.
      //
      // 46rem is a floor, not a preference: below about that, the command log
      // and the vitals tail each get fewer than four lines once their own
      // header and footer bars are subtracted, which is not a log. On a taller
      // window it grows to fill the viewport beside the controls instead.
      className="flex min-h-[46rem] flex-col border border-[var(--border)] bg-[var(--surface)] lg:h-[calc(100vh-13rem)]"
    >
      <Tabs
        id="console"
        label="Drone console view"
        tabs={TABS}
        active={tab}
        onSelect={setTab}
        action={
          <span className="mono text-[10px] uppercase tracking-[0.08em]">
            <StatusDot tone={telemetry ? "good" : "idle"}>
              {telemetry ? "10 Hz" : "no stream"}
            </StatusDot>
          </span>
        }
      />

      <TabPanel id="console" tabKey="vitals" active={tab === "vitals"} className="flex min-h-0 flex-1 flex-col">
        <div className="border-b border-[var(--border)]">
          <AttitudeIndicator telemetry={telemetry} />
        </div>
        {/* The command log first: when something has just been pressed, the
            question is what the agent did with it. It gets the larger share —
            its lines wrap and a refusal can run to three of them, while the
            vitals tail is one fixed-width line per second. */}
        <div className="flex min-h-0 flex-6 flex-col border-b border-[var(--border)]">
          <PaneTitle>Command log</PaneTitle>
          <CommandLog lines={logLines} onClear={onClearLog} />
        </div>
        <div className="flex min-h-0 flex-5 flex-col">
          <PaneTitle>Vitals</PaneTitle>
          <VitalsTail telemetry={telemetry} history={history} session={session} />
        </div>
      </TabPanel>

      <TabPanel id="console" tabKey="camera" active={tab === "camera"} className="flex min-h-0 flex-1 flex-col">
        <CameraPane />
      </TabPanel>

      <TabPanel id="console" tabKey="scene" active={tab === "scene"} className="flex min-h-0 flex-1 flex-col">
        {/* `active` stops the canvas repainting behind a hidden tab — the panel
            stays mounted so the trail survives, but the loop does not run. */}
        <SceneView telemetry={telemetry} history={history} active={tab === "scene"} />
      </TabPanel>
    </section>
  );
}

function PaneTitle({ children }: { children: string }) {
  return (
    <h3 className="mono shrink-0 border-b border-[var(--border)] bg-[var(--surface-2)] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-[var(--muted)]">
      {children}
    </h3>
  );
}
