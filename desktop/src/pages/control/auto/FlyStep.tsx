/**
 * Step ③ of the Auto flow: fly the mission.
 *
 * START MISSION IS AT THE TOP, disabled with its reason until it can act. The
 * agent refuses a mission in words for everything the page cannot see (the
 * drone off its home mark, a battery too low for the plan, a controller not
 * built yet), and those words land in the page's message — this button never
 * pretends to know more than the agent.
 *
 * Below it: the scene with the mission loaded — the room's geofence and
 * obstacles on the floor, the path at its heights, each point done, current or
 * ahead — and the mission controller's progress. While the mission flies, the
 * flow is locked here: a plan cannot be edited in the air. Land and Emergency
 * stop stay in the strip at the top, as always.
 */

import { useEffect, useState } from "react";
import type { History, Run } from "@/App";
import {
  api, AgentError, type MissionProgress, type MissionView, type RoomView, type Session,
  type Telemetry,
} from "@/lib/agent";
import { formatDuration } from "@/lib/format";
import { Button, Message, Panel, Spinner, StatusDot, type Tone } from "@/components/ui";
import { Field } from "../ControlPage";
import { SceneView, type ScenePlan } from "../SceneView";
import { checkComplete } from "./CheckStep";

const TERMINAL: MissionProgress["state"][] = ["done", "aborted", "interrupted", "failed"];

const OUTCOME: Record<string, { tone: Tone; text: string }> = {
  done: { tone: "good", text: "Mission complete — every inspection point was held and recorded." },
  aborted: { tone: "warning", text: "The mission ended early and the drone landed. The last event says why." },
  interrupted: { tone: "warning", text: "You took the drone back with the keys. It is in your hands, as in Manual." },
  failed: { tone: "critical", text: "The mission controller hit an error and the flight was ended. The agent's log has the details." },
};

export function planFor(mission: MissionView, room: RoomView, progress: MissionProgress | null): ScenePlan {
  const done = new Set(progress?.id === mission.id ? progress.completed_point_ids : []);
  const current = progress?.id === mission.id ? progress.current_point_id : null;
  return {
    fence: room.geofence.vertices,
    obstacles: room.obstacles.map((o) => ({ kind: o.kind, points: o.points, radius: o.radius })),
    home: mission.home,
    points: mission.points.map((p) => ({
      id: p.id, x: p.x_m, y: p.y_m, z: p.z_m,
      state: done.has(p.id) ? "done" : p.id === current ? "current" : "pending",
    })),
  };
}

export function FlyStep({ session, run, telemetry, history, mission, ambient, setAmbient, onPlanAnother }: {
  session: Session;
  run: Run;
  telemetry: Telemetry | null;
  history: History;
  mission: MissionView;
  ambient: string;
  setAmbient: (value: string) => void;
  onPlanAnother: () => void;
}) {
  const [room, setRoom] = useState<RoomView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setError(null);
    api.room(mission.room_id)
      .then((r) => { if (live) setRoom(r); })
      .catch((e: unknown) => { if (live) setError(e instanceof AgentError ? e.message : "The room could not be read."); });
    return () => { live = false; };
  }, [mission.room_id, attempt]);

  const progress = session.mission?.id === mission.id ? session.mission : null;
  const flying = session.activity === "mission";
  const finished = progress !== null && TERMINAL.includes(progress.state) && !flying;

  const reason = (): string | null => {
    if (flying) return "The mission is flying.";
    if (!mission.valid) return "This mission has problems to fix first (step ①).";
    if (session.state === "idle" || session.state === "signed_out") return "Start the session first (step ②).";
    if (session.state === "starting") return "The checks are still running.";
    if (session.state === "checks_failed") return "The checks did not pass (step ②).";
    if (session.state === "awaiting_confirmation") return "Confirm the area is clear first (step ②).";
    if (session.retry_required) return "Retry the checks — the last flight ended early (step ②).";
    if (session.state === "busy") return "The drone is busy. Wait for it to finish.";
    if (!checkComplete(session)) return "The session is not ready.";
    if (!session.assisted) return "The drone cannot see the base stations, so it cannot fly a mission.";
    return null;
  };
  const why = reason();

  return (
    <div className="grid gap-3">
      <section aria-label="Start the mission" className="flex flex-wrap items-end justify-between gap-3 border border-[var(--border)] bg-[var(--surface)] p-3">
        <div className="min-w-0">
          <p className="eyebrow">Mission · revision {mission.revision}</p>
          <h2 className="wrap-anywhere text-lg font-bold text-[var(--heading)]">{mission.name}</h2>
          <p className="mono text-xs text-[var(--muted)]">
            {mission.points.length} point{mission.points.length === 1 ? "" : "s"} · about {formatDuration(mission.estimated_duration_s)} · {mission.return_to_start ? "returns home" : "lands at the last point"}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-28">
            <Field label="Room temp" value={ambient} onChange={setAmbient} hint="74F or 22C" />
          </div>
          <div className="grid gap-1">
            <Button
              variant="primary"
              disabled={why !== null}
              title={why ?? undefined}
              onClick={() => void run(() => api.runMission(mission.id, ambient), `Start mission ${mission.name}`)}
            >
              {flying ? "Flying…" : "Start mission"}
            </Button>
          </div>
        </div>
        {why && !flying && <p className="w-full text-xs text-[var(--muted)]">{why}</p>}
        {flying && (
          <p className="w-full text-xs">
            Use <strong>Land</strong> at the top (or <kbd>L</kbd>) to bring it down now. Any movement key takes the drone back from the mission.
          </p>
        )}
      </section>

      {finished && progress && (
        <div className="grid gap-2">
          <Message tone={OUTCOME[progress.state]?.tone ?? "idle"} text={OUTCOME[progress.state]?.text ?? progress.state} />
          <div><Button onClick={onPlanAnother}>Plan or pick another mission</Button></div>
        </div>
      )}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.6fr)_minmax(14rem,1fr)]">
        <div className="flex h-[26rem] min-w-0 flex-col border border-[var(--border)]">
          {error ? (
            <div className="grid gap-3 p-4">
              <Message tone="critical" text={error} />
              <div><Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button></div>
            </div>
          ) : room ? (
            <SceneView telemetry={telemetry} history={history} active plan={planFor(mission, room, progress)} />
          ) : (
            <div className="p-4"><Spinner label="Loading the room…" /></div>
          )}
        </div>

        <Panel
          title="Progress"
          action={progress
            ? <StatusDot tone={progress.state === "done" ? "good" : TERMINAL.includes(progress.state) ? "warning" : "idle"}>{progress.state.replace("_", " ")}</StatusDot>
            : <StatusDot tone="idle">not started</StatusDot>}
          bodyClassName="grid gap-2 px-4 py-3"
        >
          <ol className="grid gap-1">
            {mission.points.map((p) => {
              const done = progress?.completed_point_ids.includes(p.id) ?? false;
              const current = progress?.current_point_id === p.id;
              return (
                <li key={p.id} className="mono flex items-baseline gap-2 text-xs">
                  <span aria-hidden="true" className="w-4 text-center"
                        style={{ color: done || current ? "var(--primary)" : "var(--muted)" }}>
                    {done ? "✓" : current ? "●" : "○"}
                  </span>
                  <span className="font-semibold">{p.id}</span>
                  <span className="min-w-0 wrap-anywhere text-[var(--muted)]">{p.label ?? ""}</span>
                  <span className="sr-only">{done ? " — done" : current ? " — holding here now" : " — ahead"}</span>
                </li>
              );
            })}
          </ol>
          {progress?.last_event && (
            <p className="border-t border-[var(--border)] pt-2 text-xs">{progress.last_event.detail}</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
