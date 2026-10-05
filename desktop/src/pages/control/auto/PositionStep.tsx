/**
 * ② Position — the drone learns where it is, from where it sits.
 *
 * The drone decodes the base station's sweeps into angles by itself; to turn
 * them into a position it needs to know where the station STANDS. One press
 * measures that from where the drone sits (agent Session.measure_station →
 * geometry.estimate_quick, the mirror settled by the station standing
 * upright) and stores it on the drone; that spot becomes (0, 0, 0). No
 * walking the drone about (2026-10-05, Samuel).
 *
 * Done when the drone says its position has settled — read, never assumed.
 */

import { useState } from "react";
import type { Run } from "@/App";
import { AgentError, api, type Session } from "@/lib/agent";
import { StationStages, useStation } from "@/components/StationStages";
import { Button, Message, Panel, Spinner, StatusDot, type Tone } from "@/components/ui";

export function PositionStep({ session, run, onContinue }: {
  session: Session;
  run: Run;
  onContinue: () => void;
}) {
  const station = useStation(session.radio?.state === "connected" || session.session_id != null);
  const [outcome, setOutcome] = useState<{ tone: Tone; text: string } | null>(null);
  const working = station?.measuring === true;
  const flying = session.state === "busy";

  const measure = () => {
    setOutcome(null);
    void run(async () => {
      try {
        const r = await api.measureStation();
        setOutcome({ tone: "good", text: r.message });
      } catch (e) {
        setOutcome({ tone: "critical", text: e instanceof AgentError ? e.message : "The measurement did not work." });
        throw e;
      }
    }, "Measure the base station");
  };

  return (
    <Panel title="Position — the drone learns where it is"
           action={station?.connected && station.ready
             ? <StatusDot tone="good">Position settled</StatusDot>
             : <StatusDot tone="warning">Not yet</StatusDot>}
           bodyClassName="grid gap-3 px-4 py-3">
      <p className="text-sm">
        Put the drone flat on the floor where the mission will start, in view of the base station. Press Measure. The
        drone works out where the station stands and from then on knows its own position — that spot becomes (0, 0, 0).
        Motors stay off; nothing needs to be moved.
      </p>
      {station === null && <Spinner label="Waiting for the drone…" />}
      {station !== null && !station.connected && (
        <Message tone="warning" text="The drone is not connected. Plug in the Crazyradio and switch the drone on." />
      )}
      {station?.connected && <StationStages station={station} />}
      {working && <Spinner label="Measuring — keep the drone still…" />}
      {outcome && !working && <Message tone={outcome.tone} text={outcome.text} />}
      {session.session_id != null && station?.connected && station.ready && !session.assisted && (
        <div className="grid gap-2">
          <Message tone="warning" text="This session's checks ran before the drone knew where it was. Check again so the session uses the position." />
          <div><Button onClick={() => void run(api.retry, "Check the drone again")}>Check again</Button></div>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant={station?.connected && station.ready ? "secondary" : "primary"}
                disabled={!station?.connected || working || flying || station.received.length === 0}
                onClick={measure}>
          {station?.connected && station.measured.length ? "Measure again" : "Measure from where the drone sits"}
        </Button>
        <Button variant={station?.connected && station.ready ? "primary" : "secondary"}
                disabled={!(station?.connected && station.ready)} onClick={onContinue}>
          Continue to the flyable space →
        </Button>
      </div>
      {station?.connected && station.received.length === 0 && (
        <p className="text-xs"><StatusDot tone="warning">The drone is not decoding a base station here. Check the station&apos;s light is solid green and it can see the top of the drone; if the light reaches the sensors but sweeps are not decoded, set the channels in Set up (step 3).</StatusDot></p>
      )}
    </Panel>
  );
}
