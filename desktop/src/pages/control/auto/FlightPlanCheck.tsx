/**
 * Steps ③ FLYABLE SPACE and ④ AUTO-CORRECT of the Auto flow (2026-10-05:
 * ① Plan → ② Position → ③ Flyable space → ④ Auto-correct → ⑤ Fly, in the
 * order the operator works). `mode` picks which half this renders.
 *
 *   ③ the plan as drawn over the green: where the drone can trust its
 *     position. "Use the predicted space" saves where the stored base station
 *     reaches (no walk); the survey (optional) walks it; Forget drops it.
 *   ④ YOUR PLAN, AND THE PLAN THAT WILL FLY (2026-10-01, Samuel), and the
 *     Auto-correct button that fits a copy of the plan into the green. The
 *     saved plan never changes.
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

export function FlightPlanCheck({ mission, run, mode, corrected = false, onCorrected, onContinue }: {
  mission: MissionView;
  run: Run;
  mode: "space" | "fit";
  /** ④ only: the operator pressed Auto-correct and the result is flyable. */
  corrected?: boolean;
  onCorrected?: (ok: boolean) => void;
  onContinue?: () => void;
}) {
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

  const flyable = !!plan?.position && errors.length === 0 && (plan?.unfitted.length ?? 0) === 0;
  // A corrected plan that stops being flyable (the drone was moved, the
  // plan edited) is no longer corrected.
  useEffect(() => { if (corrected && !flyable && plan) onCorrected?.(false); }, [corrected, flyable, plan, onCorrected]);

  return (
    <>
      <Panel
        title={mode === "space" ? "Flyable space — where the drone can trust its position" : "Your plan, and the plan that will fly"}
        action={!plan ? <Spinner label="Checking…" />
          : !plan.position ? <StatusDot tone="idle">No position yet</StatusDot>
          : errors.length ? <StatusDot tone="critical">{`${errors.length} to fix`}</StatusDot>
          : mode === "space" ? <StatusDot tone={coverage?.measured ? "good" : "idle"}>{coverage?.measured ? "Green space set" : "Default area"}</StatusDot>
          : <StatusDot tone="good">Safe to start here</StatusDot>}
        bodyClassName="grid gap-4 px-4 py-3"
      >
        <p className="text-xs leading-relaxed">
          {mode === "space"
            ? "The green space is where the drone can trust its position. Use the predicted space — where the measured base station reaches, no walking — or walk the survey. Your plan is never changed by it."
            : "Your plan stays exactly as you drew it. Auto-correct fits a copy into the green space: points outside it move to the nearest spot inside, points already inside never move. The flight starts from wherever the drone is (D)."}
        </p>
        {error && (
          <div className="grid gap-2">
            <Message tone="critical" text={error} />
            <div><Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button></div>
          </div>
        )}
        {plan && !plan.position && (
          <Message tone="warning" text="The drone does not know where it is yet. Measure it in ② Position, then come back." />
        )}
        {mode === "space" && !coverage?.measured && (
          <Message tone="warning" text="No green space is set for this room, so the agent's default area (4 m × 4 m) stands in. Use the predicted space below to fit the plan to where the base station reaches." />
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

        {mode === "space" && (
          <SurveyPanel room={room} survey={survey} run={run} positioned={!!plan?.position}
                       measured={!!coverage?.measured} predicted={!!coverage?.predicted?.everywhere}
                       onStarted={setSurvey}
                       onStopped={() => { setSurvey({ active: false }); setAttempt((n) => n + 1); }} />
        )}
        {mode === "space" && onContinue && (
          <div><Button variant="primary" onClick={onContinue}>Continue to Auto-correct →</Button></div>
        )}

        {mode === "fit" && (
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
          <div className="flex flex-wrap items-center gap-2">
            <Button variant={corrected ? "secondary" : "primary"} disabled={!plan}
                    onClick={() => {
                      setAttempt((n) => n + 1);
                      onCorrected?.(flyable);
                    }}>
              Auto-correct into the green space
            </Button>
            {corrected && onContinue && <Button variant="primary" onClick={onContinue}>Continue to Fly →</Button>}
          </div>
          {corrected
            ? <p className="text-xs"><StatusDot tone="good">{plan && plan.moves.length ? `Auto-corrected: ${plan.moves.length} point${plan.moves.length === 1 ? "" : "s"} moved into the green; your saved plan is unchanged.` : "Auto-corrected: every point is already inside the green."}</StatusDot></p>
            : plan && !flyable && <p className="text-xs"><StatusDot tone="warning">{!plan.position ? "Measure the drone's position first (② Position)." : "Fix what is listed above, then Auto-correct."}</StatusDot></p>}
        </section>
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

/** Measure the flyable space: carry the drone round the room's edge. Sits
 *  between the two maps, so the outline can be watched growing on both. */
function SurveyPanel({ room, survey, run, positioned, measured, predicted, onStarted, onStopped }: {
  room: RoomView | null;
  survey: SurveyStatus;
  run: Run;
  /** The drone trusts its position now: a survey can record something true. */
  positioned: boolean;
  /** The room already has a measured flyable space. */
  measured: boolean;
  /** The stored base station predicts a reach over this room. */
  predicted: boolean;
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
    <section className="grid gap-2 border border-[var(--border)] p-3" aria-labelledby="survey-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="survey-heading" className="eyebrow">Set the green space</h3>
        {survey.active && <StatusDot tone="warning">{`Surveying · ${survey.spots} spots`}</StatusDot>}
      </div>
      <p className="text-xs leading-relaxed">
        Where in this room the drone can trust its position. Motors off, drone in your hands: press Start, then walk it
        slowly round the edge of the space you want to fly in, at about the heights it will fly. Only spots where the
        drone knows where it is count. Not needed for a small flight — without it the agent&apos;s default area stands in.
      </p>
      {!positioned && !survey.active && (
        <p className="text-xs"><StatusDot tone="warning">Measure the base station first (Set up, step 4) — until the drone knows where it is, a survey records nothing true.</StatusDot></p>
      )}
      {survey.active && (
        <p className="mono text-xs">{survey.spots} spots counted · {survey.seen - survey.kept} readings left out (no trusted position) · the outline is drawn on both maps</p>
      )}
      <div className="flex flex-wrap gap-2">
        {!survey.active ? (
          <>
            <Button variant="primary" disabled={!room || !positioned || !predicted}
                    title={predicted ? undefined : "Measure the base station first (② Position)."}
                    onClick={() => room && act(() => api.usePredictedCoverage(room.id), "Use the predicted space", onStopped)}>
              Use the predicted space
            </Button>
            <Button disabled={!room || !positioned}
                    onClick={() => room && act(() => api.startSurvey(room.id).then(onStarted), "Start the survey", () => {})}>
              Walk a survey (optional)
            </Button>
            {measured && (
              <Button disabled={!room}
                      onClick={() => room && act(() => api.forgetCoverage(room.id), "Forget the measured space", onStopped)}>
                Forget the measured space
              </Button>
            )}
          </>
        ) : (
          <>
            <Button variant="primary" onClick={() => act(() => api.stopSurvey(true), "Save the flyable space", onStopped)}>
              Save as the flyable space
            </Button>
            <Button onClick={() => act(() => api.stopSurvey(false), "Discard the survey", onStopped)}>Discard</Button>
          </>
        )}
      </div>
    </section>
  );
}
