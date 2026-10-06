/**
 * Steps ③ FLYABLE SPACE and ④ AUTO-CORRECT of the Auto flow (2026-10-05:
 * ① Plan → ② Position → ③ Flyable space → ④ Auto-correct → ⑤ Fly, in the
 * order the operator works). `mode` picks which half this renders.
 *
 *   ③ THE GREEN: where the measured base station reaches, over the whole map
 *     (agent session._prediction) — computed, never walked, never a button.
 *     Your room, path and obstacles are drawn over it.
 *   ④ YOUR PLAN, AND THE AUTO-CORRECTED PLAN (2026-10-01, Samuel): the plan
 *     as drawn — editable here, the green on its map, points outside it
 *     ringed red — and below it the plan that will fly, corrected by the
 *     agent on its own: moved to start at the drone, points outside the green
 *     brought in, each move named. It is asked of the agent (GET …/from-drone
 *     every 2 s, POST /missions/fit for an unsaved edit) — the SAME function
 *     Start flies (backend mission/plan/fit.py). The saved plan never changes.
 *
 * Both maps in 2-D or 3-D (the map's own switch), each full screen.
 */

import { useCallback, useEffect, useState } from "react";
import type { Run } from "@/App";
import {
  api, AgentError, type FlyingPlan, type Mission, type MissionView, type PlanLimits, type Room,
  type RoomCoverage, type RoomView,
} from "@/lib/agent";
import { formatMetres } from "@/lib/format";
import { Button, Message, Panel, Spinner, StatusDot } from "@/components/ui";
import { FullScreenOverlay } from "@/components/FullScreenOverlay";
import { MissionEditor } from "./plan/MissionEditor";
import { RoomMap } from "./plan/RoomMap";
import { spaceOf, type SpaceLayer } from "./plan/space";

const FROM_DRONE_EVERY_MS = 2000;
const DRAFT_SETTLE_MS = 400;

type Full = "drawn" | "flying" | null;

/** The outline's extent, for the words beside the map. */
function extent(space: SpaceLayer): string {
  const xs = space.vertices.map((v) => v[0]);
  const ys = space.vertices.map((v) => v[1]);
  const w = Math.max(...xs) - Math.min(...xs);
  const d = Math.max(...ys) - Math.min(...ys);
  return `${formatMetres(w)} × ${formatMetres(d)}, from ${space.z_min.toFixed(2)} to ${space.z_max.toFixed(2)} m up`;
}

export function FlightPlanCheck({ mission, run, mode, onFlyable, onContinue }: {
  mission: MissionView;
  run: Run;
  mode: "space" | "fit";
  /** ④ only: whether the auto-corrected plan can fly, every time it is asked. */
  onFlyable?: (ok: boolean) => void;
  onContinue?: () => void;
}) {
  const [drawn, setDrawn] = useState<MissionView>(mission);
  const [room, setRoom] = useState<RoomView | null>(null);
  const [coverage, setCoverage] = useState<RoomCoverage | null>(null);
  const [plan, setPlan] = useState<FlyingPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [full, setFull] = useState<Full>(null);
  const [editing, setEditing] = useState<{ limits: PlanLimits; others: number } | null>(null);
  const [draft, setDraft] = useState<{ mission: Mission; room: Room } | null>(null);

  useEffect(() => { setDrawn(mission); }, [mission]);

  const loadRoom = useCallback(() => {
    api.room(drawn.room_id).then(setRoom).catch((e: unknown) => setError(e instanceof AgentError ? e.message : "The room could not be loaded."));
    api.roomCoverage(drawn.room_id).then(setCoverage).catch(() => setCoverage(null));
  }, [drawn.room_id]);
  useEffect(loadRoom, [loadRoom, attempt]);

  // The plan that will fly, for the SAVED plan: asked again every 2 s, so
  // moving the drone by hand updates it. Paused while an edit is open.
  useEffect(() => {
    if (draft) return;
    let live = true;
    const ask = () => api.missionFromDrone(drawn.id)
      .then((p) => { if (live) { setPlan(p); setError(null); } })
      .catch((e: unknown) => { if (live) setError(e instanceof AgentError ? e.message : "The plan could not be checked."); });
    void ask();
    const timer = window.setInterval(ask, FROM_DRONE_EVERY_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [drawn.id, draft, attempt]);

  // …and for an UNSAVED edit: asked once the edit settles.
  useEffect(() => {
    if (!draft) return;
    let live = true;
    const timer = window.setTimeout(() => {
      api.fitDraft(draft.mission, draft.room)
        .then((p) => { if (live) { setPlan(p); setError(null); } })
        .catch((e: unknown) => { if (live) setError(e instanceof AgentError ? e.message : "The edit could not be checked."); });
    }, DRAFT_SETTLE_MS);
    return () => { live = false; window.clearTimeout(timer); };
  }, [draft]);

  const startEditing = async () => {
    try {
      const [limits, all] = await Promise.all([api.planLimits(), api.missions()]);
      setEditing({ limits, others: all.filter((m) => m.room_id === drawn.room_id && m.id !== drawn.id).length });
    } catch (e) {
      setError(e instanceof AgentError ? e.message : "The editor could not open.");
    }
  };
  const stopEditing = () => { setEditing(null); setDraft(null); };

  const space = spaceOf(coverage);
  const errors = plan?.mission.problems.filter((p) => p.severity === "error") ?? [];
  const drone = plan?.position ?? null;
  const flyable = !!plan?.position && errors.length === 0 && (plan?.unfitted.length ?? 0) === 0;

  // ④ is done when the auto-corrected plan can fly — and undone the moment it
  // cannot (the drone moved, the plan was edited).
  useEffect(() => { if (mode === "fit" && plan) onFlyable?.(flyable); }, [mode, plan, flyable, onFlyable]);

  const drawnMap = (heightClass: string) => room && (
    <RoomMap outer={room.outer} fence={room.geofence} obstacles={room.obstacles} path={drawn}
             takeoffHeight={drawn.cruise_height_m} drone={drone} space={space} heightClass={heightClass}
             label={`${drawn.name} as drawn, over the flyable space`} />
  );
  const flyingMap = (heightClass: string) => room && plan && (
    <RoomMap outer={room.outer} fence={plan.mission.room_id === room.id ? room.geofence : null}
             obstacles={room.obstacles} path={plan.mission} takeoffHeight={plan.mission.cruise_height_m}
             problems={plan.mission.problems} drone={drone} space={space} heightClass={heightClass}
             label={`${drawn.name}: the auto-corrected plan, from where the drone is`} />
  );

  const status = !plan ? <Spinner label="Checking…" />
    : !plan.position ? <StatusDot tone="warning">No position yet</StatusDot>
    : mode === "space" ? <StatusDot tone={space ? "good" : "warning"}>{space ? "Station reach known" : "Default area"}</StatusDot>
    : flyable ? <StatusDot tone="good">Ready to fly</StatusDot>
    : <StatusDot tone="critical">{`${errors.length + (plan.unfitted.length ? 1 : 0)} to fix`}</StatusDot>;

  return (
    <>
      <Panel title={mode === "space" ? "Flyable space" : "Auto-correct"} action={status}
             bodyClassName="grid gap-4 px-4 py-3">
        {error && (
          <div className="grid gap-2">
            <Message tone="critical" text={error} />
            <div><Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button></div>
          </div>
        )}
        {plan && !plan.position && (
          <Message tone="warning" text="The drone does not know where it is yet. Measure it in ② Position, then come back." />
        )}

        {mode === "space" && (
          <section className="grid gap-2" aria-labelledby="space-heading">
            <h3 id="space-heading" className="eyebrow">Where the base station reaches</h3>
            <p className="text-sm">
              {space
                ? `Green is where the drone can trust its position: ${extent(space)}. Your room, path and obstacles are drawn over it. Points outside the green are ringed red — ④ brings them in for the flight; your plan itself is never changed.`
                : "The base station's reach is not known yet, so the agent's default area (4 m × 4 m) stands in. Measure the drone's position in ② Position and the green appears here."}
            </p>
            {room ? drawnMap("h-80") : <Spinner label="Loading the room…" />}
            {onContinue && <div><Button variant="primary" onClick={onContinue}>Continue to Auto-correct →</Button></div>}
          </section>
        )}

        {mode === "fit" && (
          <>
            <section className="grid gap-2" aria-labelledby="drawn-heading">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 id="drawn-heading" className="eyebrow">Your plan — as drawn, editable</h3>
                <div className="flex flex-wrap gap-2">
                  {!editing && <Button onClick={() => void startEditing()}>Edit the plan</Button>}
                  {!editing && <Button onClick={() => setFull("drawn")}>Full screen</Button>}
                </div>
              </div>
              {editing && room ? (
                <MissionEditor
                  draft={{ room, mission: drawn, roomIsNew: false, missionIsNew: false }}
                  limits={editing.limits} run={run} drone={drone} missionsInRoom={editing.others} space={space}
                  onDraft={(m, r) => setDraft({ mission: m, room: r })}
                  onCancel={stopEditing}
                  onSaved={(saved) => { setDrawn(saved); stopEditing(); setAttempt((n) => n + 1); }}
                />
              ) : room ? drawnMap("h-64") : <Spinner label="Loading the room…" />}
            </section>

            <section className="grid gap-2" aria-labelledby="flying-heading">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 id="flying-heading" className="eyebrow">
                  The plan that will fly — auto-corrected{draft ? ", following your unsaved edit" : ""}
                </h3>
                <Button onClick={() => setFull("flying")} disabled={!plan}>Full screen</Button>
              </div>
              <p className="text-xs">
                Starts where the drone is (D): the whole path moves with it. Points outside the green are brought inside;
                the walls and obstacles stay where they are.
              </p>
              {plan ? flyingMap("h-64") : <Spinner label="Working out the plan that will fly…" />}
              {plan && plan.moves.length > 0 && (
                <ul className="grid gap-1" aria-label="Points moved into the flyable space">
                  {plan.moves.map((m) => (
                    <li key={m.point_id} className="text-xs">
                      <StatusDot tone="warning">
                        <strong className="mono">{m.point_id}</strong> moved {formatMetres(m.distance_m)} into the green
                      </StatusDot>
                    </li>
                  ))}
                </ul>
              )}
              {plan && plan.unfitted.length > 0 && (
                <Message tone="critical" text={`${plan.unfitted.join(", ")} cannot be brought inside the green. Edit your plan above, or move the drone.`} />
              )}
              {plan?.position && errors.length > 0 && (
                <ul className="grid gap-1" aria-label="Why it cannot fly">
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
              {plan && flyable && (
                <p className="text-sm"><StatusDot tone="good">{plan.moves.length ? `Corrected: ${plan.moves.length} point${plan.moves.length === 1 ? "" : "s"} moved into the green. Your saved plan is unchanged.` : "Nothing to correct — every point is inside the green."}</StatusDot></p>
              )}
              {flyable && onContinue && <div><Button variant="primary" onClick={onContinue}>Continue to Fly →</Button></div>}
            </section>
          </>
        )}
      </Panel>

      {full && (
        <FullScreenOverlay label={full === "drawn" ? `${drawn.name} — your plan` : `${drawn.name} — the plan that will fly`}
                           onClose={() => setFull(null)}>
          <div className="h-full p-3">{full === "drawn" ? drawnMap("h-[calc(100vh-9rem)]") : flyingMap("h-[calc(100vh-9rem)]")}</div>
        </FullScreenOverlay>
      )}
    </>
  );
}
