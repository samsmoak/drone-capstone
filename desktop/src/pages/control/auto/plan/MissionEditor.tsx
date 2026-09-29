/**
 * Editing a mission: its ROOM (geofence, obstacles) and its PATH (home, the
 * inspection points), on one canvas with a form beside it.
 *
 * EVERY SHAPE HAS ITS DIMENSIONS AS NUMBERS. Drag it on the plan, or type the
 * width, the radius, the corner — the drawing follows the numbers exactly, and
 * the numbers follow the drawing. Every value is held inside the room's map
 * (the measured coverage, or the default area until it is measured): nothing
 * can be made bigger than the space the drone can actually fly in.
 *
 * THE AGENT CHECKS THE PLAN, NOT THIS FILE. A moment after every change the
 * draft goes to POST /missions/validate and the agent's own answer — every
 * point, every leg, every obstacle — is what turns a dot red. There is no second
 * copy of the rules here to disagree with it.
 *
 * Order matters and the tabs say so: the room first (geofence, then obstacles),
 * then the path inside it.
 */

import { useEffect, useState } from "react";
import type { Run } from "@/App";
import {
  api, AgentError,
  type Geofence, type InspectionPoint, type Mission, type MissionView, type Obstacle,
  type OuterBound, type PlanLimits, type Problem, type Room, type XY,
} from "@/lib/agent";
import { formatDuration, formatMetres } from "@/lib/format";
import { Button, Message, Panel, Spinner, StatusDot } from "@/components/ui";
import { TabPanel, Tabs } from "@/components/Tabs";
import { NumberField, SmallButton, TextField } from "./fields";
import {
  circleFence, circleOf, clamp, clampXY, cm, defaultFence, dimensionsOf, fitFence, lengthOf,
  mapBox, MIN_SIZE_M, moveObstacle, newId, newObstacle, nextPointId, obstacleFrom, rectangleFence,
  rectangleOf, type Box, type ObstacleDimensions,
} from "./geometry";
import { PlanCanvas, sameHandle, type Handle } from "./PlanCanvas";

export type Draft = { room: Room; mission: Mission; roomIsNew: boolean; missionIsNew: boolean };

type Placing = null | "point" | "vertex" | Obstacle["kind"];
type EditorTab = "room" | "path";

export function outerOf(room: Room, limits: PlanLimits): OuterBound {
  return room.coverage ? { vertices: room.coverage.vertices, measured: true } : limits.outer;
}

/** A new room: the map, less a margin, as a rectangle. */
export function blankRoom(limits: PlanLimits): Room {
  const now = new Date().toISOString();
  return {
    format: 1, id: newId(), name: "New room",
    geofence: defaultFence(limits.outer, { z_min: limits.z_min_m, z_max: limits.z_max_m }),
    obstacles: [], coverage: null, clearance_m: limits.default_clearance_m,
    revision: 1, created_at: now, updated_at: now,
  };
}

/** A new mission in a room: home near the fence's lower-left, no points yet. */
export function blankMission(room: Room, limits: PlanLimits): Mission {
  const now = new Date().toISOString();
  const b = mapBox({ vertices: room.geofence.vertices, measured: false });
  const inset = Math.min(0.4, (b.xMax - b.xMin) / 4, (b.yMax - b.yMin) / 4);
  return {
    format: 1, id: newId(), name: "New mission", room_id: room.id,
    home: [cm(b.xMin + inset), cm(b.yMin + inset)], points: [],
    cruise_height_m: clamp(0.4, limits.z_min_m, limits.z_max_m), return_to_start: true,
    revision: 1, flown_revision: null, created_at: now, updated_at: now,
  };
}

export function MissionEditor({ draft, limits, run, drone, missionsInRoom, onSaved, onCancel }: {
  draft: Draft;
  limits: PlanLimits;
  run: Run;
  drone: XY | null;
  /** How many OTHER saved missions share this room — edits reach them too. */
  missionsInRoom: number;
  onSaved: (mission: MissionView) => void;
  onCancel: () => void;
}) {
  const [room, setRoom] = useState<Room>(draft.room);
  const [mission, setMission] = useState<Mission>(draft.mission);
  const [tab, setTab] = useState<EditorTab>(draft.roomIsNew ? "room" : "path");
  const [selected, setSelected] = useState<Handle | null>(null);
  const [placing, setPlacing] = useState<Placing>(null);
  const [check, setCheck] = useState<MissionView | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [leaving, setLeaving] = useState(false);

  const dirty = room !== draft.room || mission !== draft.mission;
  const outer = outerOf(room, limits);
  const box = mapBox(outer);
  const band = { lo: room.geofence.z_min, hi: room.geofence.z_max };

  // The agent's own verdict on the draft, a moment after the last change.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.validateMission(mission, room)
        .then((result) => { setCheck(result); setCheckError(null); })
        .catch((e: unknown) => setCheckError(
          e instanceof AgentError ? e.message : "The plan could not be checked."));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [mission, room]);

  const problems: Problem[] = check?.problems ?? [];

  // ── edits ──────────────────────────────────────────────────────────────
  const setFence = (fence: Geofence) => setRoom((r) => ({ ...r, geofence: fitFence(fence, box) }));
  const setObstacle = (id: string, next: Obstacle) =>
    setRoom((r) => ({ ...r, obstacles: r.obstacles.map((o) => (o.id === id ? next : o)) }));
  const setPoint = (id: string, change: Partial<InspectionPoint>) =>
    setMission((m) => ({ ...m, points: m.points.map((p) => (p.id === id ? { ...p, ...change } : p)) }));

  const onDrag = (handle: Handle, to: XY, by: XY) => {
    const [x, y] = clampXY(to, box).map(cm) as XY;
    if (handle.kind === "home") setMission((m) => ({ ...m, home: [x, y] }));
    else if (handle.kind === "point") setPoint(handle.id, { x_m: x, y_m: y });
    else if (handle.kind === "vertex") {
      setRoom((r) => ({ ...r, geofence: { ...r.geofence, vertices: r.geofence.vertices.map(
        (v, i) => (i === handle.index ? [x, y] as XY : v)) } }));
    } else {
      const o = room.obstacles.find((item) => item.id === handle.id);
      if (o) setObstacle(o.id, moveObstacle(o, by[0], by[1], box));
    }
  };

  const onPlace = (at: XY) => {
    const [x, y] = clampXY(at, box).map(cm) as XY;
    if (placing === "point") {
      const id = nextPointId(mission.points);
      setMission((m) => ({ ...m, points: [...m.points, {
        id, label: null, x_m: x, y_m: y, z_m: m.cruise_height_m, hold_s: limits.min_hold_s,
      }] }));
      setSelected({ kind: "point", id });
    } else if (placing === "vertex") {
      setRoom((r) => ({ ...r, geofence: { ...r.geofence, vertices: [...r.geofence.vertices, [x, y]] } }));
    } else if (placing) {
      const o = newObstacle(placing, [x, y], box, newId());
      setRoom((r) => ({ ...r, obstacles: [...r.obstacles, o] }));
      setSelected({ kind: "obstacle", id: o.id });
      setPlacing(null);
    }
  };

  const save = async () => {
    setSaving(true);
    await run(async () => {
      const savedRoom = await api.saveRoom(room);
      const saved = await api.saveMission({ ...mission, room_id: savedRoom.id });
      onSaved(saved);
    }, `Save mission ${mission.name}`);
    setSaving(false);
  };

  const errors = problems.filter((p) => p.severity === "error");
  const warnings = problems.filter((p) => p.severity === "warning");

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">{draft.missionIsNew ? "New mission" : `Editing · revision ${mission.revision}`}</p>
          <h2 className="wrap-anywhere text-lg font-bold text-[var(--heading)]">{mission.name || "Untitled"}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {leaving ? (
            <>
              <span className="text-xs">Leave without saving?</span>
              <SmallButton tone="danger" onClick={onCancel}>Discard changes</SmallButton>
              <SmallButton onClick={() => setLeaving(false)}>Keep editing</SmallButton>
            </>
          ) : (
            <SmallButton onClick={() => (dirty ? setLeaving(true) : onCancel())}>Cancel</SmallButton>
          )}
          <Button variant="primary" onClick={() => void save()} disabled={saving}>
            {saving ? "Saving…" : "Save mission"}
          </Button>
        </div>
      </div>

      {mission.flown_revision !== null && mission.flown_revision >= mission.revision && dirty && (
        <Message tone="idle" text={`Revision ${mission.revision} has flown, so saving makes revision ${mission.revision + 1}. The flight keeps the plan it actually flew.`} />
      )}
      {missionsInRoom > 0 && tab === "room" && (
        <Message tone="warning" text={`${missionsInRoom} other mission${missionsInRoom === 1 ? " uses" : "s use"} this room. Changing its geofence or obstacles changes ${missionsInRoom === 1 ? "that mission" : "those missions"} too — they are checked again when you save.`} />
      )}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.3fr)_minmax(18rem,1fr)]">
        <div className="grid content-start gap-2">
          <div className="border border-[var(--border)]">
            <PlanCanvas
              outer={outer} fence={room.geofence} obstacles={room.obstacles}
              home={mission.home} points={mission.points} returnToStart={mission.return_to_start}
              problems={problems} drone={drone}
              label={`Floor plan of ${room.name}: the geofence, ${room.obstacles.length} obstacles, home and ${mission.points.length} inspection points`}
              editing={{ selected, onSelect: setSelected, onDrag, onPlace, placing }}
            />
          </div>
          <p className="text-xs leading-relaxed text-[var(--muted)]">
            {placing === "point" ? "Click the plan to place inspection points, in flying order. Press Done when finished."
              : placing === "vertex" ? "Click the plan to add geofence corners, in order around the room."
              : placing ? `Click the plan to place the ${placing}.`
              : "Drag any handle, or focus it and use the arrow keys (5 cm a press). The dashed outline is the room's map — nothing can go beyond it."}
          </p>
          <ProblemList problems={problems} error={checkError} checking={check === null && !checkError}
                       summary={check} />
        </div>

        <div className="grid content-start">
          <Tabs<EditorTab>
            id="mission-editor"
            label="What to edit"
            tabs={[
              { key: "room", label: "1 · Room", badge: room.obstacles.length ? <span className="mono text-[10px]">{room.obstacles.length}</span> : undefined },
              { key: "path", label: "2 · Path", badge: mission.points.length ? <span className="mono text-[10px]">{mission.points.length}</span> : undefined },
            ]}
            active={tab}
            onSelect={(next) => { setTab(next); setPlacing(null); }}
          />
          <TabPanel id="mission-editor" tabKey="room" active={tab === "room"} className="grid gap-4 border border-t-0 border-[var(--border)] p-3">
            <RoomForm room={room} setRoom={setRoom} setFence={setFence} box={box} limits={limits}
                      placing={placing} setPlacing={setPlacing}
                      selected={selected} setSelected={setSelected} setObstacle={setObstacle} />
          </TabPanel>
          <TabPanel id="mission-editor" tabKey="path" active={tab === "path"} className="grid gap-4 border border-t-0 border-[var(--border)] p-3">
            <PathForm mission={mission} setMission={setMission} setPoint={setPoint} box={box} band={band}
                      limits={limits} placing={placing} setPlacing={setPlacing}
                      selected={selected} setSelected={setSelected} problems={problems} />
          </TabPanel>
        </div>
      </div>

      {errors.length === 0 && warnings.length === 0 && check && (
        <p className="sr-only" role="status">The agent found no problems with this plan.</p>
      )}
    </div>
  );
}

// ── the room ─────────────────────────────────────────────────────────────

function RoomForm({ room, setRoom, setFence, box, limits, placing, setPlacing, selected, setSelected, setObstacle }: {
  room: Room;
  setRoom: (update: (r: Room) => Room) => void;
  setFence: (fence: Geofence) => void;
  box: Box;
  limits: PlanLimits;
  placing: Placing;
  setPlacing: (p: Placing) => void;
  selected: Handle | null;
  setSelected: (h: Handle | null) => void;
  setObstacle: (id: string, next: Obstacle) => void;
}) {
  const fence = room.geofence;
  const bandOf = { z_min: fence.z_min, z_max: fence.z_max };
  const mapW = cm(box.xMax - box.xMin);
  const mapD = cm(box.yMax - box.yMin);

  const setShape = (shape: Geofence["shape"]) => {
    const b = mapBox({ vertices: fence.vertices, measured: false });
    if (shape === "rectangle") setFence(rectangleFence(b.xMin, b.yMin, b.xMax - b.xMin, b.yMax - b.yMin, bandOf));
    else if (shape === "circle") {
      setFence(circleFence((b.xMin + b.xMax) / 2, (b.yMin + b.yMax) / 2,
                           Math.min(b.xMax - b.xMin, b.yMax - b.yMin) / 2, bandOf));
    } else {
      setFence({ ...fence, shape: "polygon", vertices: fence.shape === "polygon" ? fence.vertices
        : [[b.xMin, b.yMin], [b.xMax, b.yMin], [b.xMax, b.yMax], [b.xMin, b.yMax]] });
    }
    setPlacing(null);
  };

  const rect = rectangleOf(fence);
  const circle = circleOf(fence);

  return (
    <>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-3">
        <TextField label="Room name" value={room.name} onChange={(name) => setRoom((r) => ({ ...r, name }))} />
        <NumberField label="Clearance" value={room.clearance_m} step={0.05} min={0.05} max={1}
                     hint="From every obstacle and the fence edge"
                     onCommit={(v) => setRoom((r) => ({ ...r, clearance_m: cm(v) }))} />
      </div>

      <section className="grid gap-2" aria-labelledby="fence-heading">
        <h3 id="fence-heading" className="eyebrow">Geofence — always closed</h3>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Geofence shape">
          {(["rectangle", "circle", "polygon"] as const).map((shape) => (
            <SmallButton key={shape} pressed={fence.shape === shape} onClick={() => setShape(shape)}>
              {shape === "polygon" ? "Corners" : shape[0].toUpperCase() + shape.slice(1)}
            </SmallButton>
          ))}
        </div>
        <p className="text-xs text-[var(--muted)]">
          Room map: {formatMetres(mapW)} × {formatMetres(mapD)}. Every size below is held inside it.
        </p>

        {fence.shape === "rectangle" && (
          <div className="flex flex-wrap gap-3">
            <NumberField label="Left edge (x)" value={rect.xMin} min={box.xMin} max={box.xMax - MIN_SIZE_M}
                         onCommit={(v) => setFence(rectangleFence(v, rect.yMin, Math.min(rect.width, box.xMax - v), rect.depth, bandOf))} />
            <NumberField label="Bottom edge (y)" value={rect.yMin} min={box.yMin} max={box.yMax - MIN_SIZE_M}
                         onCommit={(v) => setFence(rectangleFence(rect.xMin, v, rect.width, Math.min(rect.depth, box.yMax - v), bandOf))} />
            <NumberField label="Width" value={rect.width} min={MIN_SIZE_M} max={cm(box.xMax - rect.xMin)}
                         onCommit={(v) => setFence(rectangleFence(rect.xMin, rect.yMin, v, rect.depth, bandOf))} />
            <NumberField label="Depth" value={rect.depth} min={MIN_SIZE_M} max={cm(box.yMax - rect.yMin)}
                         onCommit={(v) => setFence(rectangleFence(rect.xMin, rect.yMin, rect.width, v, bandOf))} />
          </div>
        )}

        {fence.shape === "circle" && (
          <div className="flex flex-wrap gap-3">
            <NumberField label="Centre x" value={circle.cx} min={box.xMin + circle.radius} max={box.xMax - circle.radius}
                         onCommit={(v) => setFence(circleFence(v, circle.cy, circle.radius, bandOf))} />
            <NumberField label="Centre y" value={circle.cy} min={box.yMin + circle.radius} max={box.yMax - circle.radius}
                         onCommit={(v) => setFence(circleFence(circle.cx, v, circle.radius, bandOf))} />
            <NumberField label="Radius" value={circle.radius} min={MIN_SIZE_M}
                         max={cm(Math.min(circle.cx - box.xMin, box.xMax - circle.cx, circle.cy - box.yMin, box.yMax - circle.cy))}
                         onCommit={(v) => setFence(circleFence(circle.cx, circle.cy, v, bandOf))} />
          </div>
        )}

        {fence.shape === "polygon" && (
          <div className="grid gap-2">
            <ol className="grid gap-1.5">
              {fence.vertices.map(([x, y], index) => (
                <li key={index} className={`flex flex-wrap items-end gap-2 border-l-2 pl-2 ${
                  sameHandle(selected, { kind: "vertex", index }) ? "border-[var(--primary)]" : "border-transparent"}`}>
                  <span className="mono w-6 pb-2 text-xs">{index + 1}</span>
                  <NumberField label="x" value={x} min={box.xMin} max={box.xMax} hint=""
                               onCommit={(v) => setFence({ ...fence, vertices: fence.vertices.map((p, i) => (i === index ? [cm(v), p[1]] as XY : p)) })} />
                  <NumberField label="y" value={y} min={box.yMin} max={box.yMax} hint=""
                               onCommit={(v) => setFence({ ...fence, vertices: fence.vertices.map((p, i) => (i === index ? [p[0], cm(v)] as XY : p)) })} />
                  <SmallButton tone="danger" disabled={fence.vertices.length <= 3}
                               title={fence.vertices.length <= 3 ? "A geofence needs at least 3 corners to enclose anything." : undefined}
                               onClick={() => setFence({ ...fence, vertices: fence.vertices.filter((_, i) => i !== index) })}>
                    Remove
                  </SmallButton>
                </li>
              ))}
            </ol>
            <div>
              <SmallButton pressed={placing === "vertex"} onClick={() => setPlacing(placing === "vertex" ? null : "vertex")}>
                {placing === "vertex" ? "Done adding corners" : "Add corners on the plan"}
              </SmallButton>
            </div>
            <p className="text-xs text-[var(--muted)]">
              At least 3 corners; the last joins the first. Edges may not cross.
            </p>
          </div>
        )}

        <div className="flex flex-wrap gap-3">
          <NumberField label="Lowest height" value={fence.z_min} min={0.05} max={fence.z_max - 0.05}
                       onCommit={(v) => setFence({ ...fence, z_min: cm(v) })} />
          <NumberField label="Highest height" value={fence.z_max} min={fence.z_min + 0.05} max={limits.z_max_m}
                       hint={`At most ${limits.z_max_m.toFixed(2)} m — the flight system's ceiling`}
                       onCommit={(v) => setFence({ ...fence, z_max: cm(v) })} />
        </div>
      </section>

      <section className="grid gap-2" aria-labelledby="obstacles-heading">
        <h3 id="obstacles-heading" className="eyebrow">Obstacles</h3>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Add an obstacle">
          {(["line", "rectangle", "circle"] as const).map((kind) => (
            <SmallButton key={kind} pressed={placing === kind} onClick={() => setPlacing(placing === kind ? null : kind)}>
              + {kind[0].toUpperCase() + kind.slice(1)}
            </SmallButton>
          ))}
        </div>
        {room.obstacles.length === 0 && (
          <p className="text-xs text-[var(--muted)]">None. Add the benches, tables and pillars the drone must keep clear of.</p>
        )}
        <ul className="grid gap-2">
          {room.obstacles.map((o) => (
            <ObstacleRow key={o.id} obstacle={o} box={box}
                         selected={sameHandle(selected, { kind: "obstacle", id: o.id })}
                         onSelect={() => setSelected({ kind: "obstacle", id: o.id })}
                         onChange={(next) => setObstacle(o.id, next)}
                         onRemove={() => { setRoom((r) => ({ ...r, obstacles: r.obstacles.filter((x) => x.id !== o.id) })); setSelected(null); }} />
          ))}
        </ul>
      </section>
    </>
  );
}

function ObstacleRow({ obstacle, box, selected, onSelect, onChange, onRemove }: {
  obstacle: Obstacle;
  box: Box;
  selected: boolean;
  onSelect: () => void;
  onChange: (next: Obstacle) => void;
  onRemove: () => void;
}) {
  const d = dimensionsOf(obstacle);
  const set = (change: Partial<ObstacleDimensions>) =>
    onChange(obstacleFrom(obstacle, { ...d, ...change } as ObstacleDimensions, box));
  return (
    <li onFocus={onSelect} className={`grid gap-2 border-l-2 bg-[var(--surface-2)] p-2 ${selected ? "border-[var(--status-warning)]" : "border-transparent"}`}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <TextField label={obstacle.kind} value={obstacle.label ?? ""} placeholder="e.g. Bench"
                   onChange={(label) => onChange({ ...obstacle, label: label || null })} width="w-40" />
        <SmallButton tone="danger" onClick={onRemove}>Remove</SmallButton>
      </div>
      <div className="flex flex-wrap gap-2">
        {d.kind === "line" && (
          <>
            <NumberField label="From x" value={d.x1} min={box.xMin} max={box.xMax} hint="" onCommit={(v) => set({ x1: v })} />
            <NumberField label="From y" value={d.y1} min={box.yMin} max={box.yMax} hint="" onCommit={(v) => set({ y1: v })} />
            <NumberField label="To x" value={d.x2} min={box.xMin} max={box.xMax} hint="" onCommit={(v) => set({ x2: v })} />
            <NumberField label="To y" value={d.y2} min={box.yMin} max={box.yMax} hint="" onCommit={(v) => set({ y2: v })} />
            <p className="self-end pb-2 text-xs text-[var(--muted)]">
              Length {formatMetres(lengthOf([d.x1, d.y1], [d.x2, d.y2]))}
            </p>
          </>
        )}
        {d.kind === "rectangle" && (
          <>
            <NumberField label="Centre x" value={d.cx} min={box.xMin} max={box.xMax} hint="" onCommit={(v) => set({ cx: v })} />
            <NumberField label="Centre y" value={d.cy} min={box.yMin} max={box.yMax} hint="" onCommit={(v) => set({ cy: v })} />
            <NumberField label="Width" value={d.width} min={MIN_SIZE_M} max={cm(box.xMax - box.xMin)} onCommit={(v) => set({ width: v })} />
            <NumberField label="Depth" value={d.depth} min={MIN_SIZE_M} max={cm(box.yMax - box.yMin)} onCommit={(v) => set({ depth: v })} />
          </>
        )}
        {d.kind === "circle" && (
          <>
            <NumberField label="Centre x" value={d.cx} min={box.xMin} max={box.xMax} hint="" onCommit={(v) => set({ cx: v })} />
            <NumberField label="Centre y" value={d.cy} min={box.yMin} max={box.yMax} hint="" onCommit={(v) => set({ cy: v })} />
            <NumberField label="Radius" value={d.radius} min={MIN_SIZE_M / 2}
                         max={cm(Math.min(box.xMax - box.xMin, box.yMax - box.yMin) / 2)} onCommit={(v) => set({ radius: v })} />
          </>
        )}
      </div>
    </li>
  );
}

// ── the path ─────────────────────────────────────────────────────────────

function PathForm({ mission, setMission, setPoint, box, band, limits, placing, setPlacing, selected, setSelected, problems }: {
  mission: Mission;
  setMission: (update: (m: Mission) => Mission) => void;
  setPoint: (id: string, change: Partial<InspectionPoint>) => void;
  box: Box;
  band: { lo: number; hi: number };
  limits: PlanLimits;
  placing: Placing;
  setPlacing: (p: Placing) => void;
  selected: Handle | null;
  setSelected: (h: Handle | null) => void;
  problems: Problem[];
}) {
  const move = (index: number, by: -1 | 1) => setMission((m) => {
    const points = [...m.points];
    const [p] = points.splice(index, 1);
    points.splice(index + by, 0, p);
    return { ...m, points };
  });
  const flagged = new Set(problems.filter((p) => p.severity === "error").map((p) => p.where));

  return (
    <>
      <TextField label="Mission name" value={mission.name} onChange={(name) => setMission((m) => ({ ...m, name }))} />

      <section className="grid gap-2" aria-labelledby="home-heading">
        <h3 id="home-heading" className="eyebrow">Home — where the drone sits before takeoff</h3>
        <div className="flex flex-wrap gap-3">
          <NumberField label="Home x" value={mission.home[0]} min={box.xMin} max={box.xMax} hint=""
                       onCommit={(v) => setMission((m) => ({ ...m, home: [cm(v), m.home[1]] }))} />
          <NumberField label="Home y" value={mission.home[1]} min={box.yMin} max={box.yMax} hint=""
                       onCommit={(v) => setMission((m) => ({ ...m, home: [m.home[0], cm(v)] }))} />
          <NumberField label="Cruise height" value={mission.cruise_height_m} min={band.lo} max={band.hi}
                       hint="The height it takes off to"
                       onCommit={(v) => setMission((m) => ({ ...m, cruise_height_m: cm(v) }))} />
        </div>
        <label className="flex min-h-8 items-center gap-2 text-sm">
          <input type="checkbox" checked={mission.return_to_start} className="h-4 w-4"
                 onChange={(e) => setMission((m) => ({ ...m, return_to_start: e.target.checked }))} />
          Fly back over home before landing
        </label>
      </section>

      <section className="grid gap-2" aria-labelledby="points-heading">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="points-heading" className="eyebrow">Inspection points, in flying order</h3>
          <SmallButton pressed={placing === "point"} onClick={() => setPlacing(placing === "point" ? null : "point")}>
            {placing === "point" ? "Done" : "+ Add on the plan"}
          </SmallButton>
        </div>
        {mission.points.length === 0 && (
          <p className="text-xs text-[var(--muted)]">
            None yet. Press “Add on the plan”, then click where the drone should hold and record.
          </p>
        )}
        <ol className="grid gap-2">
          {mission.points.map((p, index) => (
            <li key={p.id} onFocus={() => setSelected({ kind: "point", id: p.id })}
                className={`grid gap-2 border-l-2 bg-[var(--surface-2)] p-2 ${
                  flagged.has(p.id) ? "border-[var(--status-critical)]"
                  : sameHandle(selected, { kind: "point", id: p.id }) ? "border-[var(--primary)]" : "border-transparent"}`}>
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div className="flex items-end gap-2">
                  <span className="mono pb-2 text-sm font-bold">{p.id}{flagged.has(p.id) && <span className="sr-only"> — has a problem</span>}</span>
                  <TextField label="Label" value={p.label ?? ""} placeholder="e.g. Pump 2" width="w-32"
                             onChange={(label) => setPoint(p.id, { label: label || null })} />
                </div>
                <div className="flex gap-1">
                  <SmallButton disabled={index === 0} onClick={() => move(index, -1)} title="Fly this one earlier">↑</SmallButton>
                  <SmallButton disabled={index === mission.points.length - 1} onClick={() => move(index, 1)} title="Fly this one later">↓</SmallButton>
                  <SmallButton tone="danger" onClick={() => { setMission((m) => ({ ...m, points: m.points.filter((x) => x.id !== p.id) })); setSelected(null); }}>
                    Remove
                  </SmallButton>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <NumberField label="x" value={p.x_m} min={box.xMin} max={box.xMax} hint="" onCommit={(v) => setPoint(p.id, { x_m: cm(v) })} />
                <NumberField label="y" value={p.y_m} min={box.yMin} max={box.yMax} hint="" onCommit={(v) => setPoint(p.id, { y_m: cm(v) })} />
                <NumberField label="Height" value={p.z_m} min={band.lo} max={band.hi} hint="" onCommit={(v) => setPoint(p.id, { z_m: cm(v) })} />
                <NumberField label="Hold" unit="s" step={1} value={p.hold_s} min={limits.min_hold_s} max={300}
                             hint={`At least ${limits.min_hold_s} s`} onCommit={(v) => setPoint(p.id, { hold_s: Math.round(v * 10) / 10 })} />
              </div>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

// ── what the agent said ──────────────────────────────────────────────────

export function ProblemList({ problems, error, checking, summary }: {
  problems: Problem[];
  error: string | null;
  checking: boolean;
  summary: MissionView | null;
}) {
  const errors = problems.filter((p) => p.severity === "error");
  const warnings = problems.filter((p) => p.severity === "warning");
  const shown = [...errors, ...warnings];
  return (
    <Panel
      title="The agent's check"
      action={checking ? <Spinner label="Checking…" />
        : error ? <StatusDot tone="critical">Not checked</StatusDot>
        : errors.length ? <StatusDot tone="critical">{`${errors.length} to fix`}</StatusDot>
        : <StatusDot tone="good">Safe to fly</StatusDot>}
      bodyClassName="grid gap-2 px-4 py-3"
    >
      {error && <Message tone="critical" text={error} />}
      {summary && (
        <p className="mono text-xs text-[var(--muted)]">
          {summary.points.length} point{summary.points.length === 1 ? "" : "s"} · path {formatMetres(summary.path_length_m, 1)} · about {formatDuration(summary.estimated_duration_s)}
        </p>
      )}
      {shown.length === 0 && !error && !checking && (
        <p className="text-sm">Every point and every leg is inside the geofence and clear of every obstacle.</p>
      )}
      <ul className="grid gap-1.5">
        {shown.map((p, i) => (
          <li key={`${p.code}-${p.where}-${i}`} className="text-xs leading-relaxed">
            <StatusDot tone={p.severity === "error" ? "critical" : "warning"}>
              {p.where ? <strong className="mono">{p.where}: </strong> : null}{p.message}
            </StatusDot>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
