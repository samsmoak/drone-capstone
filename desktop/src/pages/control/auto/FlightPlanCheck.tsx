/**
 * Step ② — YOUR PLAN, AND THE PLAN THAT WILL FLY (2026-10-01, Samuel).
 *
 *   top     the plan as drawn, over the FLYABLE SPACE (where the drone's
 *           position can be trusted — plan/space.ts). Editable here: "Edit
 *           the plan" opens the same editor as step ①.
 *   bottom  THE PLAN THAT WILL FLY, read-only: from where the drone is,
 *           every point outside the space moved to the nearest fine spot,
 *           each move named. It is asked of the agent — GET …/from-drone for
 *           the saved plan every 2 s, POST /missions/fit for an unsaved edit —
 *           the SAME function Start flies (backend mission/plan/fit.py), so
 *           what this shows is what flies.
 *
 * Both in 2-D or 3-D (the map's own switch), each full screen.
 *
 * THE SURVEY measures the space: carry the drone round the room's edge with
 * the base stations in view; its outline grows on the map; save it and it is
 * the room's coverage. Until then the agent's default area stands in, and a
 * prediction from the stations' poses (if `cropwatcher geometry` has stored
 * them) shows where to walk.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Run } from "@/App";
import {
  api, AgentError, type FlyingPlan, type Mission, type MissionView, type PlanLimits, type Room,
  type RoomCoverage, type RoomView, type SurveyStatus,
} from "@/lib/agent";
import { formatMetres } from "@/lib/format";
import { Button, Message, Panel, Spinner, StatusDot } from "@/components/ui";
import { FullScreenOverlay } from "@/components/FullScreenOverlay";
import { MissionEditor } from "./plan/MissionEditor";
import { RoomMap } from "./plan/RoomMap";
import type { SpaceLayer } from "./plan/space";

const FROM_DRONE_EVERY_MS = 2000;
const SURVEY_EVERY_MS = 1000;
const DRAFT_SETTLE_MS = 400;

type Full = "drawn" | "flying" | null;

/** What the maps draw as the flyable space: the survey while it runs, then the
 *  measured coverage, else the prediction. */
export function spaceOf(cov: RoomCoverage | null, survey: SurveyStatus, room: Room): SpaceLayer | null {
  const band = { z_min: room.geofence.z_min, z_max: room.geofence.z_max };
  if (survey.active && survey.outline.length >= 3) return { kind: "survey", vertices: survey.outline, ...band };
  if (cov?.measured) return { kind: "measured", vertices: cov.measured.vertices, z_min: cov.measured.z_min, z_max: cov.measured.z_max };
  const ever = cov?.predicted?.everywhere;
  if (ever) return { kind: "predicted", vertices: ever.vertices, z_min: ever.z_min, z_max: ever.z_max, slices: cov?.predicted?.slices };
  return null;
}

export function FlightPlanCheck({ mission, run }: { mission: MissionView; run: Run }) {
  const [drawn, setDrawn] = useState<MissionView>(mission);
  const [room, setRoom] = useState<RoomView | null>(null);
  const [coverage, setCoverage] = useState<RoomCoverage | null>(null);
  const [survey, setSurvey] = useState<SurveyStatus>({ active: false });
  const [plan, setPlan] = useState<FlyingPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [full, setFull] = useState<Full>(null);
  const [editing, setEditing] = useState<{ limits: PlanLimits; others: number } | null>(null);
  const [draft, setDraft] = useState<{ mission: Mission; room: Room } | null>(null);

  useEffect(() => { setDrawn(mission); }, [mission]);

  const loadRoom = useCallback(() => {
    api.room(drawn.room_id).then(setRoom).catch(() => {});
    api.roomCoverage(drawn.room_id).then((c) => { setCoverage(c); setSurvey(c.survey); }).catch(() => {});
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

  // The survey's outline, while it runs.
  useEffect(() => {
    if (!survey.active) return;
    const timer = window.setInterval(() => { api.surveyStatus().then(setSurvey).catch(() => {}); }, SURVEY_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [survey.active]);

  const startEditing = async () => {
    const [limits, all] = await Promise.all([api.planLimits(), api.missions()]);
    setEditing({ limits, others: all.filter((m) => m.room_id === drawn.room_id && m.id !== drawn.id).length });
  };
  const stopEditing = () => { setEditing(null); setDraft(null); };

  const space = room ? spaceOf(coverage, survey, room) : null;
  const flySpace: SpaceLayer | null = plan && coverage?.measured
    ? { kind: "measured", vertices: plan.space.vertices, z_min: plan.space.z_min, z_max: plan.space.z_max }
    : null;
  const errors = plan?.mission.problems.filter((p) => p.severity === "error") ?? [];
  const drone = plan?.position ?? null;

  const drawnMap = (heightClass: string) => room && (
    <RoomMap outer={room.outer} fence={room.geofence} obstacles={room.obstacles} path={drawn}
             takeoffHeight={drawn.cruise_height_m} drone={drone} space={space} heightClass={heightClass}
             label={`${drawn.name} as drawn, over the flyable space`} />
  );
  const flyingMap = (heightClass: string) => room && plan && (
    <RoomMap outer={room.outer} fence={plan.mission.room_id === room.id ? room.geofence : null}
             obstacles={room.obstacles} path={plan.mission} takeoffHeight={plan.mission.cruise_height_m}
             problems={plan.mission.problems} drone={drone} space={flySpace} heightClass={heightClass}
             label={`${drawn.name}: the plan that will fly, from where the drone is`} />
  );

  return (
    <>
      <Panel
        title="Your plan, and the plan that will fly"
        action={!plan ? <Spinner label="Checking…" />
          : !plan.position ? <StatusDot tone="idle">No position yet</StatusDot>
          : errors.length ? <StatusDot tone="critical">{`${errors.length} to fix`}</StatusDot>
          : <StatusDot tone="good">Safe to start here</StatusDot>}
        bodyClassName="grid gap-4 px-4 py-3"
      >
        <p className="text-xs leading-relaxed">
          The green space is where the drone knows where it is. Points outside it are ringed red, and the plan that will
          fly moves each one to the nearest spot inside — the points already inside never move. The flight starts from
          wherever the drone is (D).
        </p>
        {error && (
          <div className="grid gap-2">
            <Message tone="critical" text={error} />
            <div><Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button></div>
          </div>
        )}
        {!coverage?.measured && (
          <Message tone="warning" text={coverage?.predicted?.everywhere
            ? "The flyable space shown is PREDICTED from the base stations. Measure it with the survey below before trusting its edges — until then the agent's default area is what flies."
            : "This room's flyable space has not been measured. Until it is, the agent's default area stands in. Measure it with the survey below."} />
        )}

        <section className="grid gap-2" aria-labelledby="drawn-heading">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="drawn-heading" className="eyebrow">Your plan</h3>
            <div className="flex flex-wrap gap-2">
              {!editing && <Button onClick={() => void startEditing()}>Edit the plan here</Button>}
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
          ) : room ? drawnMap("h-72") : <Spinner label="Loading the room…" />}
        </section>

        <section className="grid gap-2" aria-labelledby="flying-heading">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="flying-heading" className="eyebrow">
              The plan that will fly{draft ? " — following your unsaved edit" : ""}
            </h3>
            <Button onClick={() => setFull("flying")} disabled={!plan}>Full screen</Button>
          </div>
          {plan ? flyingMap("h-72") : <Spinner label="Working out the plan that will fly…" />}
          {plan && plan.moves.length > 0 && (
            <ul className="grid gap-1" aria-label="Points moved into the flyable space">
              {plan.moves.map((m) => (
                <li key={m.point_id} className="text-xs">
                  <StatusDot tone="warning">
                    <strong className="mono">{m.point_id}</strong> moved {formatMetres(m.distance_m)} into the flyable space
                  </StatusDot>
                </li>
              ))}
            </ul>
          )}
          {plan && plan.unfitted.length > 0 && (
            <Message tone="critical" text={`${plan.unfitted.join(", ")} cannot be brought inside the flyable space. Move ${plan.unfitted.length === 1 ? "it" : "them"} in your plan.`} />
          )}
          {plan?.position && errors.length > 0 && (
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
        </section>
      </Panel>

      <SurveyPanel room={room} survey={survey} run={run}
                   onStarted={setSurvey}
                   onStopped={() => { setSurvey({ active: false }); setAttempt((n) => n + 1); }} />

      {full && (
        <FullScreenOverlay label={full === "drawn" ? `${drawn.name} — your plan` : `${drawn.name} — the plan that will fly`}
                           onClose={() => setFull(null)}>
          <div className="h-full p-3">{full === "drawn" ? drawnMap("h-[calc(100vh-9rem)]") : flyingMap("h-[calc(100vh-9rem)]")}</div>
        </FullScreenOverlay>
      )}
    </>
  );
}

/** Measure the flyable space: carry the drone round the room's edge. */
function SurveyPanel({ room, survey, run, onStarted, onStopped }: {
  room: RoomView | null;
  survey: SurveyStatus;
  run: Run;
  onStarted: (s: SurveyStatus) => void;
  onStopped: () => void;
}) {
  const busy = useRef(false);
  const act = (action: () => Promise<unknown>, label: string, after: () => void) => {
    if (busy.current) return;
    busy.current = true;
    void run(action, label).finally(() => { busy.current = false; after(); });
  };
  return (
    <Panel title="Measure the flyable space"
           action={survey.active ? <StatusDot tone="warning">{`Surveying · ${survey.kept} positions`}</StatusDot> : undefined}
           bodyClassName="grid gap-3 px-4 py-3">
      <p className="text-xs leading-relaxed">
        Motors off, drone in your hands: press Start, then walk it slowly round the edge of the space you want to fly
        in, at about the heights it will fly, with the base stations in view. Only positions where the drone receives
        enough stations count (one by default; two where the room insists). Save when the outline covers the room.
      </p>
      {survey.active && (
        <p className="mono text-xs">{survey.kept} of {survey.seen} positions counted · the outline is drawn on the maps above</p>
      )}
      <div className="flex flex-wrap gap-2">
        {!survey.active ? (
          <Button variant="primary" disabled={!room}
                  onClick={() => room && act(() => api.startSurvey(room.id).then(onStarted), "Start the survey", () => {})}>
            Start the survey
          </Button>
        ) : (
          <>
            <Button variant="primary" onClick={() => act(() => api.stopSurvey(true), "Save the flyable space", onStopped)}>
              Save as the flyable space
            </Button>
            <Button onClick={() => act(() => api.stopSurvey(false), "Discard the survey", onStopped)}>Discard</Button>
          </>
        )}
      </div>
    </Panel>
  );
}
