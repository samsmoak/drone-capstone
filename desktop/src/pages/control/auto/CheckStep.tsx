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
 *
 * YOUR PLAN, AND THE PLAN THAT WILL FLY (FlightPlanCheck.tsx, 2026-10-01):
 * the plan as drawn over the flyable space, editable here; below it the plan
 * Start will fly — from the drone, points outside the space moved in — asked
 * of the agent (the same function Start uses). And the survey that measures
 * the space.
 *
 * The DPP switch sits here too, before the session starts (on by default in
 * Auto).
 */

import type { Run } from "@/App";
import { api, type MissionView, type Session } from "@/lib/agent";
import { Button, Message, Panel, Spinner, StatusDot } from "@/components/ui";
import { Checklist, HealthTestPanel, RetryPanel } from "../ControlPage";
import { ProcessingSwitch } from "../DataPipeline";
import { FlightPlanCheck } from "./FlightPlanCheck";

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
          point{mission.points.length === 1 ? "" : "s"}. Set it down anywhere clear in the room: the flight starts from where it is.
        </p>
      )}

      {s === "idle" && (
        <Panel
          title="Start the session"
          note="Connects to the drone and runs every check: the radio, the battery, the positioning, a settled estimate. Nothing spins."
        >
          <div className="grid gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" onClick={() => void run(api.start, "Start session")}>Start session</Button>
              <span className="text-xs text-[var(--muted)]">Also in Actions, on the right.</span>
            </div>
            <ProcessingSwitch session={session} run={run} />
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
              <div className="grid gap-2">
                {/* The agent's own reason names the stage that is missing
                    (flight_guard.py problems) — "cannot see" was said on
                    2026-10-05 while the station was seen and decoded. */}
                <Message tone="warning" text={`A mission needs the drone to know where it is, so the agent will refuse it. ${session.unassisted_reason ?? "The position is not usable."} After fixing it in Set up, check again.`} />
                <div><Button onClick={() => void run(api.retry, "Check the drone again")}>Check again</Button></div>
              </div>
            )}
            <ProcessingSwitch session={session} run={run} />
            <div>
              <Button variant="primary" onClick={onContinue}>Continue to Fly →</Button>
            </div>
          </div>
        </Panel>
      )}

      {mission && s !== "signed_out" && <FlightPlanCheck mission={mission} run={run} />}

      {(s === "busy" || s === "ending") && (
        <Panel title={s === "ending" ? "Ending the session" : "Busy"}>
          <Spinner label={s === "ending" ? "Landing if needed, saving the flight…" : `The drone is busy: ${session.activity ?? "working"}.`} />
        </Panel>
      )}
    </div>
  );
}
