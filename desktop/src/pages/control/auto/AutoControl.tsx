/**
 * The Control page in Auto: the mission on the left, the monitor on the right.
 *
 *   left    the Mission flow — ① Mission → ② Check → ③ Fly. In Auto this is
 *           where the operator works, so it takes the larger share.
 *   right   the monitor: FlightDeck (the vitals, the keys and the action rail —
 *           never behind a tab, pages-and-windows.txt) above the console's
 *           Vitals and Camera tabs. The Scene moved into ③ Fly, where the
 *           mission it now draws lives.
 *
 * The divider is the same draggable, keyboard-operable window splitter as
 * Manual's, with ITS OWN saved position (cropwatcher.split.control.auto):
 * dragging in one mode must not move the other.
 *
 * Below `lg` the columns stack — the vitals and actions first, then the flow,
 * then the console — for the same reason Manual puts its controls first.
 *
 * Manual is untouched by this file.
 */

import type { History, Run } from "@/App";
import type { Intent, Session, Telemetry } from "@/lib/agent";
import type { LogLine } from "@/lib/commandLog";
import { SplitPane } from "@/components/SplitPane";
import { ConsolePane } from "../ConsolePane";
import { FlightDeck } from "../ControlPage";
import { MissionFlow, type FlowStart } from "./MissionFlow";

const MONITOR_VIEWS = ["vitals", "camera"] as const;

export function AutoControl({
  session, telemetry, history, intent, run, logLines, onClearLog, wide,
  height, hold, ambient, setAmbient, start,
}: {
  session: Session;
  telemetry: Telemetry | null;
  history: History;
  intent: Intent;
  run: Run;
  logLines: LogLine[];
  onClearLog: () => void;
  wide: boolean;
  height: string;
  hold: string;
  ambient: string;
  setAmbient: (value: string) => void;
  /** Harness only: open on a given step. Never set by the app. */
  start?: FlowStart;
}) {
  const ready = session.state === "ready" && !session.retry_required;
  const deck = (
    <FlightDeck intent={intent} mode={session.mode} telemetry={telemetry} session={session}
                run={run} ready={ready} height={height} hold={hold} ambient={ambient} />
  );
  const flow = (
    <MissionFlow session={session} run={run} telemetry={telemetry} history={history}
                 ambient={ambient} setAmbient={setAmbient} start={start} />
  );

  if (!wide) {
    return (
      <div className="grid items-start gap-5">
        {deck}
        {flow}
        <ConsolePane telemetry={telemetry} history={history} logLines={logLines}
                     onClearLog={onClearLog} views={MONITOR_VIEWS} />
      </div>
    );
  }

  return (
    <SplitPane
      orientation="vertical"
      storageKey="cropwatcher.split.control.auto"
      defaultFraction={0.58}
      label="Mission and monitor"
      className="min-h-[calc(100vh-9.5rem)] gap-0"
      first={<div className="flex min-w-0 flex-1 flex-col pr-3">{flow}</div>}
      second={
        // A fixed window height, like Manual's console, so the console's own
        // dividers keep their range and the log scrolls inside it.
        <div className="flex h-[calc(100vh-9.5rem)] min-w-0 flex-1 flex-col gap-3 self-start pl-3">
          {deck}
          <ConsolePane telemetry={telemetry} history={history} logLines={logLines}
                       onClearLog={onClearLog} views={MONITOR_VIEWS} fill />
        </div>
      }
    />
  );
}
