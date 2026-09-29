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
 * FROM WHERE THE DRONE IS. A saved mission may be flown long after it was
 * planned, from wherever the drone has been set down. This step asks the
 * agent to check the mission from the drone's own position
 * (GET /missions/{id}/from-drone — the same Mission.from_start that Start
 * applies): the drone inside the room and clear of obstacles, the leg from it
 * to the first point and back, the battery. The points never move with the
 * drone; they mark equipment. It asks again every two seconds, so moving the
 * drone by hand updates the answer.
 *
 * The DPP switch sits here too, before the session starts (on by default in
 * Auto).
 */

import { useEffect, useState } from "react";
import type { Run } from "@/App";
import { api, AgentError, type MissionView, type RoomView, type Session, type XY } from "@/lib/agent";
import { formatMetres } from "@/lib/format";
import { Button, Message, Panel, Spinner, StatusDot } from "@/components/ui";
import { Checklist, HealthTestPanel, RetryPanel } from "../ControlPage";
import { ProcessingSwitch } from "../DataPipeline";
import { mapBox, placeOf } from "./plan/geometry";
import { RoomMap } from "./plan/RoomMap";

const FROM_DRONE_EVERY_MS = 2000;

/** The mission checked from the drone's position, and the map of it. */
function StartCheck({ mission }: { mission: MissionView }) {
  const [answer, setAnswer] = useState<{ position: XY | null; mission: MissionView } | null>(null);
  const [room, setRoom] = useState<RoomView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    api.room(mission.room_id).then((r) => { if (live) setRoom(r); }).catch(() => {});
    const ask = () => api.missionFromDrone(mission.id)
      .then((a) => { if (live) { setAnswer(a); setError(null); } })
      .catch((e: unknown) => { if (live) setError(e instanceof AgentError ? e.message : "The start could not be checked."); });
    void ask();
    const timer = window.setInterval(ask, FROM_DRONE_EVERY_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [mission.id, mission.room_id, attempt]);

  const checked = answer?.mission ?? null;
  const errors = checked?.problems.filter((p) => p.severity === "error") ?? [];
  const box = room ? mapBox(room.outer) : null;
  const where = answer?.position && box ? placeOf(answer.position, box) : null;

  return (
    <Panel
      title="From where the drone is"
      action={!answer ? <Spinner label="Checking…" />
        : !answer.position ? <StatusDot tone="idle">No position yet</StatusDot>
        : errors.length ? <StatusDot tone="critical">{`${errors.length} to fix`}</StatusDot>
        : <StatusDot tone="good">Safe to start here</StatusDot>}
      bodyClassName="grid gap-3 px-4 py-3"
    >
      <p className="text-xs leading-relaxed">
        The flight starts from wherever the drone is. The agent checks the path from its spot to the first point
        (and back, if it returns) against the room — the points stay where they were planned.
      </p>
      {error && (
        <div className="grid gap-2">
          <Message tone="critical" text={error} />
          <div><Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button></div>
        </div>
      )}
      {answer && !answer.position && (
        <Message tone="idle" text="The drone is not reporting a position yet. Once it is connected and sees the base stations, this checks the path from its spot — and Start checks it again." />
      )}
      {answer?.position && where && (
        <p className="mono text-xs">
          D at {formatMetres(where[0])} from left, {formatMetres(where[1])} from front · path {formatMetres(checked?.path_length_m ?? 0, 1)}
        </p>
      )}
      {answer?.position && errors.length > 0 && (
        <ul className="grid gap-1">
          {errors.map((p, i) => (
            <li key={`${p.code}-${i}`} className="text-xs">
              <StatusDot tone="critical">
                {p.where ? <strong className="mono">{p.where.replace(/^home/, "D").replace(/→ home$/, "→ D")}: </strong> : null}
                {p.message.replace(/^The start/, "The drone's spot")}
              </StatusDot>
            </li>
          ))}
        </ul>
      )}
      {answer?.position && errors.length > 0 && (
        <p className="text-xs">Move the drone somewhere clear, or edit the mission (step ①).</p>
      )}
      {room && checked && (
        <RoomMap outer={room.outer} fence={room.geofence} obstacles={room.obstacles}
                 path={checked} takeoffHeight={checked.cruise_height_m} problems={checked.problems}
                 drone={answer?.position ?? null} heightClass="h-64"
                 label={`${mission.name} from where the drone is`} />
      )}
    </Panel>
  );
}

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
              <Message tone="warning" text="The drone cannot see the base stations. A mission needs to know where it is, so the agent will refuse it — get the stations seen and start the session again." />
            )}
            <ProcessingSwitch session={session} run={run} />
            <div>
              <Button variant="primary" onClick={onContinue}>Continue to Fly →</Button>
            </div>
          </div>
        </Panel>
      )}

      {mission && s !== "signed_out" && <StartCheck mission={mission} />}

      {(s === "busy" || s === "ending") && (
        <Panel title={s === "ending" ? "Ending the session" : "Busy"}>
          <Spinner label={s === "ending" ? "Landing if needed, saving the flight…" : `The drone is busy: ${session.activity ?? "working"}.`} />
        </Panel>
      )}
    </div>
  );
}
