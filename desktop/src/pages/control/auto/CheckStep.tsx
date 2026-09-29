/**
 * Step ② of the Auto flow: the session and its checks.
 *
 * The same flow Manual runs — start the session, the checks, confirm the area,
 * Retry after an abnormal end — moved here in Auto, because the right column is
 * now the monitor. The panels are the Control page's own (Checklist, RetryPanel,
 * HealthTestPanel), not copies, so the two modes cannot drift apart.
 *
 * The step is complete when the AGENT says so (state "ready", no retry owed),
 * never on this page's own judgement.
 */

import type { Run } from "@/App";
import { api, type MissionView, type Session } from "@/lib/agent";
import { Button, Message, Panel, Spinner, StatusDot } from "@/components/ui";
import { Checklist, HealthTestPanel, RetryPanel } from "../ControlPage";

export function checkComplete(session: Session): boolean {
  return session.state === "ready" && !session.retry_required;
}

export function CheckStep({ session, run, mission, onContinue }: {
  session: Session;
  run: Run;
  mission: MissionView | null;
  onContinue: () => void;
}) {
  const s = session.state;
  return (
    <div className="grid gap-3">
      {mission && (
        <p className="text-sm">
          Checking the drone for <strong>{mission.name}</strong> — {mission.points.length} inspection
          point{mission.points.length === 1 ? "" : "s"}. Place it on the home mark first.
        </p>
      )}

      {s === "idle" && (
        <Panel
          title="Start the session"
          note="Connects to the drone and runs every check: the radio, the battery, the positioning, a settled estimate. Nothing spins."
        >
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" onClick={() => void run(api.start, "Start session")}>Start session</Button>
            <span className="text-xs text-[var(--muted)]">Also in Actions, on the right.</span>
          </div>
        </Panel>
      )}

      {(s === "starting" || s === "checks_failed" || s === "awaiting_confirmation") && (
        <Checklist session={session} run={run} />
      )}

      {s === "ready" && session.retry_required && <RetryPanel run={run} />}

      {session.health_test && s === "ready" && <HealthTestPanel result={session.health_test} />}

      {checkComplete(session) && (
        <Panel title="Ready" action={<StatusDot tone="good">Checks passed · area confirmed</StatusDot>}>
          <div className="grid gap-3">
            {!session.assisted && (
              <Message tone="warning" text="The drone cannot see the base stations. A mission needs to know where it is, so the agent will refuse it — get the stations seen and start the session again." />
            )}
            <div>
              <Button variant="primary" onClick={onContinue}>Continue to Fly →</Button>
            </div>
          </div>
        </Panel>
      )}

      {(s === "busy" || s === "ending") && (
        <Panel title={s === "ending" ? "Ending the session" : "Busy"}>
          <Spinner label={s === "ending" ? "Landing if needed, saving the flight…" : `The drone is busy: ${session.activity ?? "working"}.`} />
        </Panel>
      )}
    </div>
  );
}
