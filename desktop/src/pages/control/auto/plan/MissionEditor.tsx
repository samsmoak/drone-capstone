/**
 * Editing a mission: its ROOM (geofence, obstacles) and its PATH (the start,
 * the inspection points, how it ends), on one map with a form beside it.
 *
 * ONE MAP, TWO VIEWS (RoomMap): the plan from above, or the room in 3-D. The
 * selection is the page's: click the room's walls or an obstacle — on the map,
 * or its panel in the form — and that one thing is highlighted in both views,
 * its numbers appear over the map, and everything else fades.
 *
 * EVERY SHAPE HAS ITS DIMENSIONS AS NUMBERS, in plain words: LENGTH (left to
 * right), WIDTH (front to back), HEIGHT (up), and where it is FROM LEFT and
 * FROM FRONT (geometry.ts). Drag it, or type it — the drawing follows the
 * numbers exactly, and the numbers follow the drawing. Every value is held
 * inside the room's map (the measured coverage, or the default area until it
 * is measured): nothing can be made bigger than the space the drone can fly.
 *
 * THE PATH: the planned start (S), the points in flying order with an arrow on
 * every leg, and an END POINT — right-click a point (or its menu key, or "End
 * here" in its row) and the flight lands there, whatever comes after it.
 * Reverse direction flies the points the other way round. The drone (D) is
 * the real start of every flight: a new mission starts where it is, and
 * ② Check tests the path from wherever it has been put since.
 *
 * THE AGENT CHECKS THE PLAN, NOT THIS FILE. A moment after every change the
 * draft goes to POST /missions/validate and the agent's own answer — every
 * point, every leg, every obstacle — is what turns a dot red. There is no second
 * copy of the rules here to disagree with it.
 *
 * Order matters and the tabs say so: the room first (geofence, then obstacles),
 * then the path inside it.
 */

import { useEffect, useRef, useState } from "react";
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
  circleFence, clamp, clampXY, cm, defaultFence, fitFence, mapBox, moveObstacle, newId, newObstacle,
  nextPointId, placeOf, fromPlace, rectangleFence, type Box,
} from "./geometry";
import { clearEnd, distance, endAt, flownPoints, landsAt, reversed, returnsHome, unflownIds } from "./path";
import { isRoomObject, sameHandle, type Handle } from "./PlanCanvas";
import { RoomMap } from "./RoomMap";
import { SplitPane } from "@/components/SplitPane";
import { CardState, CARD_ATTR, ObjectCard } from "./ObjectCard";
import { FenceFields, ObstacleFields, PointFields } from "./shapeFields";

/** Side by side, with a divider, from this editor width; stacked below it. */
const SPLIT_AT_PX = 600;
const MAP_MIN_PX = 300;
const FORM_MIN_PX = 280;

/** The element's own width, following it as it is resized — the split
 *  decides by the editor's width, which full screen and the page's own
 *  divider both change. */
function useWidth(ref: React.RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

export type Draft = { room: Room; mission: Mission; roomIsNew: boolean; missionIsNew: boolean };

type Placing = null | "point" | "vertex" | Obstacle["kind"];
type EditorTab = "room" | "path";


/** The travel speeds a mission may choose — the agent's SPEED_PRESETS_M_S
 *  (mission.py), which also refuses anything else. */
const SPEEDS: { m_s: number; name: string }[] = [
  { m_s: 0.10, name: "Steady" },
  { m_s: 0.15, name: "Normal" },
  { m_s: 0.20, name: "Brisk" },
];

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

/** A new mission in a room, no points yet. It starts WHERE THE DRONE IS when
 *  a drone is reporting a position inside the room's outline; otherwise near
 *  the fence's front-left corner. */
export function blankMission(room: Room, limits: PlanLimits, drone: XY | null = null): Mission {
  const now = new Date().toISOString();
  const b = mapBox({ vertices: room.geofence.vertices, measured: false });
  const inset = Math.min(0.4, (b.xMax - b.xMin) / 4, (b.yMax - b.yMin) / 4);
  const inRoom = drone !== null && drone[0] > b.xMin && drone[0] < b.xMax && drone[1] > b.yMin && drone[1] < b.yMax;
  return {
    format: 1, id: newId(), name: "New mission", room_id: room.id,
    home: inRoom ? [cm(drone[0]), cm(drone[1])] : [cm(b.xMin + inset), cm(b.yMin + inset)], points: [],
    cruise_height_m: clamp(0.4, limits.z_min_m, limits.z_max_m), return_to_start: true, end_point_id: null,
    revision: 1, flown_revision: null, created_at: now, updated_at: now,
  };
}

export function MissionEditor({ draft, limits, run, drone, missionsInRoom, onSaved, onCancel, heightClass }: {
  draft: Draft;
  limits: PlanLimits;
  run: Run;
  drone: XY | null;
  /** How many OTHER saved missions share this room — edits reach them too. */
  missionsInRoom: number;
  onSaved: (mission: MissionView) => void;
  onCancel: () => void;
  /** The map's height (taller in full screen). */
  heightClass?: string;
}) {
  const [room, setRoom] = useState<Room>(draft.room);
  const [mission, setMission] = useState<Mission>(draft.mission);
  const [tab, setTab] = useState<EditorTab>(draft.roomIsNew ? "room" : "path");
  const [selected, setSelectedRaw] = useState<Handle | null>(null);
  const [placing, setPlacing] = useState<Placing>(null);
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const [check, setCheck] = useState<MissionView | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [leaving, setLeaving] = useState(false);

  const dirty = room !== draft.room || mission !== draft.mission;
  /** Close / ← All missions: straight back to the list, or ask first when
   *  there are unsaved changes. */
  const leave = () => (dirty ? setLeaving(true) : onCancel());
  const layout = useRef<HTMLDivElement>(null);
  const width = useWidth(layout);
  const sideBySide = width >= SPLIT_AT_PX;
  const outer = outerOf(room, limits);
  const box = mapBox(outer);
  const band = { lo: room.geofence.z_min, hi: room.geofence.z_max };

  // Selecting a room object shows the Room tab, a path handle the Path tab —
  // the form then shows the numbers of what was clicked.
  const setSelected = (h: Handle | null) => {
    setSelectedRaw(h);
    if (isRoomObject(h)) setTab("room");
    else if (h) setTab("path");
  };

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
  const removeObstacle = (id: string) => {
    setRoom((r) => ({ ...r, obstacles: r.obstacles.filter((x) => x.id !== id) }));
    setSelectedRaw(null);
  };
  const setPoint = (id: string, change: Partial<InspectionPoint>) =>
    setMission((m) => ({ ...m, points: m.points.map((p) => (p.id === id ? { ...p, ...change } : p)) }));
  const removePoint = (id: string) => {
    setMission((m) => ({ ...m, end_point_id: m.end_point_id === id ? null : m.end_point_id,
                         points: m.points.filter((x) => x.id !== id) }));
    setSelectedRaw(null);
  };
  const setHome = (at: XY) => setMission((m) => ({ ...m, home: clampXY(at, box).map(cm) as XY }));

  const onDrag = (handle: Handle, to: XY, by: XY) => {
    const [x, y] = clampXY(to, box).map(cm) as XY;
    if (handle.kind === "home") setMission((m) => ({ ...m, home: [x, y] }));
    else if (handle.kind === "point") setPoint(handle.id, { x_m: x, y_m: y });
    else if (handle.kind === "vertex") {
      setRoom((r) => ({ ...r, geofence: { ...r.geofence, vertices: r.geofence.vertices.map(
        (v, i) => (i === handle.index ? [x, y] as XY : v)) } }));
    } else if (handle.kind === "obstacle") {
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
      setSelectedRaw({ kind: "point", id });
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
  const ready = readiness(room, mission, problems, checkError);
  const complete = ready.every((item) => item.done);

  // What is selected, with its numbers — under the map, never over it.
  const below = (() => {
    if (selected?.kind === "fence" || selected?.kind === "vertex") {
      return (
        <Inspector title={`The room · ${room.geofence.shape === "polygon" ? "corners" : room.geofence.shape}`} onClose={() => setSelectedRaw(null)}>
          <FenceFields fence={room.geofence} box={box} limits={limits} setFence={setFence} compact />
        </Inspector>
      );
    }
    if (selected?.kind === "obstacle") {
      const o = room.obstacles.find((item) => item.id === selected.id);
      if (!o) return null;
      return (
        <Inspector title={`${o.label ?? "Obstacle"} · ${o.kind}`} onClose={() => setSelectedRaw(null)}>
          <ObstacleFields obstacle={o} box={box} onChange={(next) => setObstacle(o.id, next)} />
        </Inspector>
      );
    }
    if (selected?.kind === "point") {
      const p = mission.points.find((item) => item.id === selected.id);
      if (!p) return null;
      return (
        <Inspector title={`Point ${p.id}${p.label ? ` · ${p.label}` : ""}`} onClose={() => setSelectedRaw(null)}>
          <PointFields point={p} box={box} band={band} minHold={limits.min_hold_s} setPoint={(c) => setPoint(p.id, c)} />
        </Inspector>
      );
    }
    return (
      <p className="px-3 py-2 text-xs leading-relaxed">
        <strong>Nothing selected</strong> — every object is shown equally. Click the room, an obstacle, a point or
        the start (on the map, or its card at the right) to change its size and place.
      </p>
    );
  })();

  // Click anywhere in the form that is not an object's card, and nothing is
  // selected: every object equal, none of them changeable until one is picked.
  const deselectOutsideCards = (event: React.PointerEvent) => {
    if (!(event.target as Element).closest(`[${CARD_ATTR}]`)) setSelectedRaw(null);
  };

  const mapColumn = (
    <div className="grid min-w-0 flex-1 content-start gap-2">
      <RoomMap
        outer={outer} fence={room.geofence} obstacles={room.obstacles} path={mission}
        takeoffHeight={mission.cruise_height_m} problems={problems} drone={drone}
        label={`Room map of ${room.name}: the geofence, ${room.obstacles.length} obstacles, the start and ${mission.points.length} inspection points`}
        heightClass={heightClass}
        below={below}
        editing={{
          selected, onSelect: setSelected, onDrag, onPlace, placing,
          onPointMenu: (id, at) => setMenu({ id, ...at }),
          onFence: setFence, onObstacle: setObstacle,
          onPoint: (id, change) => setPoint(id, change), onHome: setHome,
          zMax: limits.z_max_m,
        }}
      />
      <p className="text-xs leading-relaxed text-[var(--muted)]">
        {placing === "point" ? "Click the map to place inspection points, in flying order. Press Done when finished."
          : placing === "vertex" ? "Click the map to add geofence corners, in order around the room."
          : placing ? `Click the map to place the ${placing}.`
          : "Drag any handle, or focus it and use the arrow keys (5 cm a press). Right-click a point to make it the end point. Click empty floor to select nothing. The dashed outline is the room's map — nothing can go beyond it."}
      </p>
      <ProblemList problems={problems} error={checkError} checking={check === null && !checkError}
                   summary={check} />
    </div>
  );

  const formColumn = (
    <div className="grid min-w-0 flex-1 content-start" onPointerDown={deselectOutsideCards}>
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
                  selected={selected} setSelected={setSelected} setObstacle={setObstacle}
                  removeObstacle={removeObstacle} />
      </TabPanel>
      <TabPanel id="mission-editor" tabKey="path" active={tab === "path"} className="grid gap-4 border border-t-0 border-[var(--border)] p-3">
        <PathForm mission={mission} setMission={setMission} setPoint={setPoint} removePoint={removePoint}
                  box={box} band={band} limits={limits} placing={placing} setPlacing={setPlacing}
                  selected={selected} setSelected={setSelected} problems={problems} drone={drone}
                  setHome={setHome} />
      </TabPanel>
    </div>
  );

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          {/* Back to the saved missions, and New mission — the same guarded
              leave as Close: unsaved changes are asked about first. */}
          <SmallButton onClick={leave} title="Back to the list of saved missions">← All missions</SmallButton>
          <p className="eyebrow pt-2">{draft.missionIsNew ? "New mission" : `Editing · revision ${mission.revision}`}</p>
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
            <SmallButton onClick={leave} title="Close the editor and go back to the saved missions">
              Close
            </SmallButton>
          )}
          <Button variant="primary" onClick={() => void save()} disabled={saving || !complete}
                  title={complete ? undefined : "Set up the room and the path first — see the list below."}>
            {saving ? "Saving…" : "Save mission"}
          </Button>
        </div>
      </div>

      {/* SAVE NEEDS A COMPLETE MISSION, NOT A SAFE ONE. A half-finished plan
          with a problem can be saved and fixed later; the agent's check
          gates "Use this mission" and Start. The agent refuses a mission
          with no points too (store.save_mission) — this list is the why. */}
      <ul aria-label="Before this mission can be saved" className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {ready.map((item) => (
          <li key={item.key} className="flex items-baseline gap-1.5">
            <span aria-hidden="true" style={{ color: item.done ? "var(--status-good)" : "var(--status-critical)" }}>
              {item.done ? "✓" : "✗"}
            </span>
            {item.done ? (
              <span>{item.label}</span>
            ) : (
              <button type="button" className="underline decoration-dotted underline-offset-2"
                      onClick={() => { setTab(item.key); setPlacing(null); }}>
                {item.label} — {item.missing}
              </button>
            )}
            <span className="sr-only">{item.done ? " — done" : " — not yet"}</span>
          </li>
        ))}
      </ul>

      {mission.flown_revision !== null && mission.flown_revision >= mission.revision && dirty && (
        <Message tone="idle" text={`Revision ${mission.revision} has flown, so saving makes revision ${mission.revision + 1}. The flight keeps the plan it actually flew.`} />
      )}
      {missionsInRoom > 0 && tab === "room" && (
        <Message tone="warning" text={`${missionsInRoom} other mission${missionsInRoom === 1 ? " uses" : "s use"} this room. Changing its geofence or obstacles changes ${missionsInRoom === 1 ? "that mission" : "those missions"} too — they are checked again when you save.`} />
      )}

      {/* THE MAP AND THE FORM, WITH A DIVIDER YOU DRAG between them once
          there is room for both (the editor's own width, not the window's —
          design/layout.txt), inline and in full screen alike; stacked below
          that. The bounds are pixels (the map never under 300 px, the form
          never under 280 px) turned into fractions of the current width.
          The panes stretch: an `items-start` row collapsed the divider itself
          to 0 px tall, and nothing could grab it (2026-09-29). */}
      <div ref={layout} className="min-w-0">
        {sideBySide ? (
          <SplitPane
            orientation="vertical"
            storageKey="cropwatcher.split.editor"
            defaultFraction={0.6}
            min={Math.max(0.3, MAP_MIN_PX / width)}
            max={Math.min(0.78, 1 - FORM_MIN_PX / width)}
            label="Room map and the room and path form"
            first={<div className="flex min-w-0 flex-1 pr-2">{mapColumn}</div>}
            second={<div className="flex min-w-0 flex-1 pl-2">{formColumn}</div>}
          />
        ) : (
          <div className="grid gap-3">
            {mapColumn}
            {formColumn}
          </div>
        )}
      </div>

      {menu && (
        <PointMenu
          at={menu}
          point={menu.id}
          mission={mission}
          onClose={() => setMenu(null)}
          onEnd={() => setMission((m) => endAt(m, menu.id))}
          onClearEnd={() => setMission((m) => clearEnd(m))}
          onRemove={() => removePoint(menu.id)}
        />
      )}

      {errors.length === 0 && warnings.length === 0 && check && (
        <p className="sr-only" role="status">The agent found no problems with this plan.</p>
      )}
    </div>
  );
}

/**
 * What Save needs: the room and the path SET UP — complete, not yet safe.
 *
 *   room   a name, and an outline the agent accepts: at least 3 corners, no
 *          crossing edges (the agent refuses to read one), inside the map
 *   path   a name, and at least one inspection point
 */
function readiness(room: Room, mission: Mission, problems: Problem[], checkError: string | null):
  { key: EditorTab; label: string; done: boolean; missing: string }[] {
  const outsideMap = problems.some((p) => p.code === "fence_outside_coverage");
  const roomMissing = !room.name.trim() ? "give it a name"
    : room.geofence.vertices.length < 3 ? "its outline needs at least 3 corners"
    : checkError ? checkError
    : outsideMap ? "pull its outline inside the room map"
    : "";
  const pathMissing = !mission.name.trim() ? "give the mission a name"
    : mission.points.length === 0 ? "add at least one inspection point"
    : "";
  return [
    { key: "room", label: "Room", done: roomMissing === "", missing: roomMissing },
    { key: "path", label: "Path", done: pathMissing === "", missing: pathMissing },
  ];
}

/** The selected thing's numbers, over the map. */
function Inspector({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <section aria-label={`Selected: ${title}`} className="grid gap-2 p-2.5">
      <div className="flex items-center justify-between gap-3">
        <p className="eyebrow wrap-anywhere">Selected · {title}</p>
        <SmallButton onClick={onClose} title="Deselect">Done</SmallButton>
      </div>
      {children}
    </section>
  );
}

/**
 * A point's menu: right-click on the map (or the context-menu key / Shift+F10
 * on a focused point). A real menu — focus moves in, arrow keys move within,
 * Escape and a click elsewhere close it.
 */
function PointMenu({ at, point, mission, onClose, onEnd, onClearEnd, onRemove }: {
  at: { x: number; y: number };
  point: string;
  mission: Mission;
  onClose: () => void;
  onEnd: () => void;
  onClearEnd: () => void;
  onRemove: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const ends = landsAt(mission) === point;
  const explicit = mission.end_point_id === point;
  useEffect(() => {
    const first = ref.current?.querySelector<HTMLButtonElement>("[role=menuitem]");
    first?.focus();
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [onClose]);
  const items: { label: string; act: () => void; danger?: boolean }[] = [
    ...(ends
      ? explicit ? [{ label: `Clear the end point — fly every point`, act: onClearEnd }] : []
      : [{ label: `End the flight at ${point}`, act: onEnd }]),
    { label: `Remove ${point}`, act: onRemove, danger: true },
  ];
  // Kept on screen: a menu opened near the window's edge opens inwards.
  const left = Math.min(at.x, window.innerWidth - 260);
  const top = Math.min(at.y, window.innerHeight - 20 - items.length * 40);
  return (
    <div ref={ref} role="menu" aria-label={`Point ${point}`}
         className="fixed z-50 grid min-w-56 border border-[var(--border)] bg-[var(--surface)] py-1 shadow-lg"
         style={{ left, top }}
         onKeyDown={(e) => {
           const all = [...(ref.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? [])];
           const i = all.indexOf(document.activeElement as HTMLButtonElement);
           if (e.key === "ArrowDown") { e.preventDefault(); all[(i + 1) % all.length]?.focus(); }
           if (e.key === "ArrowUp") { e.preventDefault(); all[(i - 1 + all.length) % all.length]?.focus(); }
         }}>
      <p className="eyebrow px-3 py-1">Point {point}{ends ? " · the end point" : ""}</p>
      {items.map((item) => (
        <button key={item.label} type="button" role="menuitem"
                className={`min-h-10 px-3 text-left text-sm hover:bg-[var(--surface-2)] focus-visible:bg-[var(--surface-2)] ${item.danger ? "border-l-2 border-[var(--status-critical)]" : ""}`}
                onClick={() => { item.act(); onClose(); }}>
          {item.label}
        </button>
      ))}
    </div>
  );
}

// ── the room ─────────────────────────────────────────────────────────────

function RoomForm({ room, setRoom, setFence, box, limits, placing, setPlacing, selected, setSelected, setObstacle, removeObstacle }: {
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
  removeObstacle: (id: string) => void;
}) {
  const fence = room.geofence;
  const bandOf = { z_min: fence.z_min, z_max: fence.z_max };
  const mapL = cm(box.xMax - box.xMin);
  const mapW = cm(box.yMax - box.yMin);
  const fenceSelected = selected?.kind === "fence" || selected?.kind === "vertex";

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

  return (
    <>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-3">
        <TextField label="Room name" value={room.name} onChange={(name) => setRoom((r) => ({ ...r, name }))} />
        <NumberField label="Clearance" value={room.clearance_m} step={0.05} min={0.05} max={1}
                     hint="From every obstacle and the walls"
                     onCommit={(v) => setRoom((r) => ({ ...r, clearance_m: cm(v) }))} />
      </div>

      {/* The room is an object like the others: its card selects it, which
          highlights it alone on the map; only then do its numbers change. */}
      <ObjectCard as="section" label="The room" selected={fenceSelected} onSelect={() => setSelected({ kind: "fence" })}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="eyebrow">The room — its geofence, always closed</h3>
          <CardState selected={fenceSelected} />
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Room shape">
          {(["rectangle", "circle", "polygon"] as const).map((shape) => (
            <SmallButton key={shape} pressed={fence.shape === shape} onClick={() => setShape(shape)}>
              {shape === "polygon" ? "Corners" : shape[0].toUpperCase() + shape.slice(1)}
            </SmallButton>
          ))}
        </div>
        <p className="text-xs text-[var(--muted)]">
          Room map: {formatMetres(mapL)} long × {formatMetres(mapW)} wide. Every size here is held inside it; "from left" and "from front" are measured from its front-left corner.
        </p>
        <FenceFields fence={fence} box={box} limits={limits} setFence={setFence} locked={!fenceSelected} />
        {fence.shape === "polygon" && (
          <div className="grid gap-1">
            <div>
              <SmallButton pressed={placing === "vertex"} onClick={() => setPlacing(placing === "vertex" ? null : "vertex")}>
                {placing === "vertex" ? "Done adding corners" : "Add corners on the map"}
              </SmallButton>
            </div>
            <p className="text-xs text-[var(--muted)]">At least 3 corners; the last joins the first. Edges may not cross.</p>
          </div>
        )}
      </ObjectCard>

      <section className="grid gap-2" aria-labelledby="obstacles-heading">
        <h3 id="obstacles-heading" className="eyebrow">Obstacles</h3>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Add an obstacle">
          {(["line", "rectangle", "circle"] as const).map((kind) => (
            <SmallButton key={kind} pressed={placing === kind} onClick={() => setPlacing(placing === kind ? null : kind)}>
              + {kind === "line" ? "Wall" : kind[0].toUpperCase() + kind.slice(1)}
            </SmallButton>
          ))}
        </div>
        {room.obstacles.length === 0 && (
          <p className="text-xs text-[var(--muted)]">None. Add the benches, tables and pillars the drone must keep clear of.</p>
        )}
        <p className="text-xs text-[var(--muted)]">
          An obstacle's height is for the room map. The drone never flies over one: every check treats it as floor to ceiling.
        </p>
        <ul className="grid gap-2">
          {room.obstacles.map((o) => (
            <ObstacleRow key={o.id} obstacle={o} box={box}
                         selected={sameHandle(selected, { kind: "obstacle", id: o.id })}
                         onSelect={() => setSelected({ kind: "obstacle", id: o.id })}
                         onChange={(next) => setObstacle(o.id, next)}
                         onRemove={() => removeObstacle(o.id)} />
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
  const kind = obstacle.kind === "line" ? "wall" : obstacle.kind;
  return (
    <ObjectCard label={`Obstacle ${obstacle.label ?? kind}`} selected={selected} onSelect={onSelect}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <TextField label={kind} value={obstacle.label ?? ""} placeholder="e.g. Bench" readOnly={!selected}
                   onChange={(label) => onChange({ ...obstacle, label: label || null })} width="w-40" />
        <div className="flex items-center gap-2">
          <CardState selected={selected} />
          <SmallButton tone="danger" onClick={onRemove}>Remove</SmallButton>
        </div>
      </div>
      <ObstacleFields obstacle={obstacle} box={box} onChange={onChange} locked={!selected} />
    </ObjectCard>
  );
}

// ── the path ─────────────────────────────────────────────────────────────

function PathForm({ mission, setMission, setPoint, removePoint, box, band, limits, placing, setPlacing, selected, setSelected, problems, drone, setHome }: {
  mission: Mission;
  setMission: (update: (m: Mission) => Mission) => void;
  setPoint: (id: string, change: Partial<InspectionPoint>) => void;
  removePoint: (id: string) => void;
  box: Box;
  band: { lo: number; hi: number };
  limits: PlanLimits;
  placing: Placing;
  setPlacing: (p: Placing) => void;
  selected: Handle | null;
  setSelected: (h: Handle | null) => void;
  problems: Problem[];
  drone: XY | null;
  setHome: (at: XY) => void;
}) {
  const move = (index: number, by: -1 | 1) => setMission((m) => {
    const points = [...m.points];
    const [p] = points.splice(index, 1);
    points.splice(index + by, 0, p);
    return { ...m, points };
  });
  const flagged = new Set(problems.filter((p) => p.severity === "error").map((p) => p.where));
  const unflown = unflownIds(mission);
  const lands = landsAt(mission);
  const flown = flownPoints(mission);
  const [left, front] = placeOf(mission.home, box);
  const off = drone ? distance(drone, mission.home) : null;
  const startSelected = selected?.kind === "home";

  // "Ends at": back at the start, the last point, or any earlier point.
  const endValue = returnsHome(mission) ? "__start" : mission.end_point_id ?? "__last";
  const setEnd = (value: string) => setMission((m) => {
    if (value === "__start") return { ...m, return_to_start: true, end_point_id: null };
    if (value === "__last") return { ...m, return_to_start: false, end_point_id: null };
    return endAt(m, value);
  });

  return (
    <>
      <TextField label="Mission name" value={mission.name} onChange={(name) => setMission((m) => ({ ...m, name }))} />

      <ObjectCard as="section" label="The planned start" selected={startSelected} onSelect={() => setSelected({ kind: "home" })}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="eyebrow">Start</h3>
          <CardState selected={startSelected} />
        </div>
        <p className="text-xs leading-relaxed">
          Every flight starts from <strong>wherever the drone is</strong> (D on the map) when you press Start — ② Check tests the path from there. The planned start (S) is what the plan is drawn and checked from until then.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <NumberField label="From left" value={left} min={0} max={cm(box.xMax - box.xMin)} hint="" readOnly={!startSelected}
                       onCommit={(v) => setHome(fromPlace([v, front], box))} />
          <NumberField label="From front" value={front} min={0} max={cm(box.yMax - box.yMin)} hint="" readOnly={!startSelected}
                       onCommit={(v) => setHome(fromPlace([left, v], box))} />
          <NumberField label="Takeoff height" value={mission.cruise_height_m} min={band.lo} max={band.hi} readOnly={!startSelected}
                       hint="The height it rises to first"
                       onCommit={(v) => setMission((m) => ({ ...m, cruise_height_m: cm(v) }))} />
        </div>
        <p className="text-xs leading-relaxed">
          <strong>Every height here is above the floor where the drone takes off</strong> — it measures the
          floor as it leaves the ground. Take off from the floor: from a 0.9 m bench, every point would fly
          0.9 m higher than planned.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <SmallButton disabled={!drone} onClick={() => drone && setHome(drone)}
                       title={drone ? undefined : "No drone is reporting a position."}>
            Put the start where the drone is
          </SmallButton>
          {off !== null && off > 0.3 && (
            <span className="text-xs">The drone is {formatMetres(off)} from the planned start.</span>
          )}
        </div>
      </ObjectCard>

      <section className="grid gap-2" aria-labelledby="speed-heading">
        <h3 id="speed-heading" className="eyebrow">Speed between points</h3>
        {/* One speed per mission (mission.py SPEED_PRESETS_M_S): every change of
            speed is a lean, and leaning is what makes a hold unsteady. */}
        <div role="group" aria-labelledby="speed-heading" className="flex border border-[var(--border)]">
          {SPEEDS.map(({ m_s, name }) => {
            const on = Math.abs((mission.speed_m_s ?? 0.2) - m_s) < 1e-9;
            return (
              <button key={name} type="button" aria-pressed={on}
                      onClick={() => setMission((m) => ({ ...m, speed_m_s: m_s }))}
                      className={`min-h-8 flex-1 px-2 text-xs font-semibold ${on
                        ? "bg-[var(--primary)] text-[var(--on-primary)]"
                        : "hover:bg-[var(--surface-2)]"}`}>
                {name} · {Math.round(m_s * 100)} cm/s
              </button>
            );
          })}
        </div>
        <p className="text-xs leading-relaxed">Slower is steadier at each point, and the mission takes longer — the battery check counts it.</p>
      </section>

      <section className="grid gap-2" aria-labelledby="finish-heading">
        <h3 id="finish-heading" className="eyebrow">How it ends, and which way round</h3>
        <label className="grid gap-1 text-xs">
          <span className="eyebrow">Ends at</span>
          {/* w-full: a select is as wide as its longest option, and these name
              whole points — it pushed the form past the window's edge. */}
          <select value={endValue} onChange={(e) => setEnd(e.target.value)}
                  className="min-h-9 w-full min-w-0 border border-[var(--border)] bg-[var(--surface-2)] px-2 text-sm">
            <option value="__start">Back at the start — then lands</option>
            <option value="__last">The last point{mission.points.length ? ` (${mission.points[mission.points.length - 1].id})` : ""} — lands there</option>
            {mission.points.slice(0, -1).map((p) => (
              <option key={p.id} value={p.id}>{p.id}{p.label ? ` · ${p.label}` : ""} — lands there; later points are not flown</option>
            ))}
          </select>
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <p className="mono min-w-0 wrap-anywhere text-xs">
            {["S", ...flown.map((p) => p.id), ...(returnsHome(mission) ? ["S"] : [])].join(" → ")}
            {unflown.size > 0 && <span className="text-[var(--muted)]"> · not flown: {[...unflown].join(", ")}</span>}
          </p>
          <SmallButton disabled={mission.points.length < 2} onClick={() => setMission((m) => reversed(m))}
                       title="Fly the points the other way round. The end point stays the end point.">
            ⇄ Reverse direction
          </SmallButton>
        </div>
      </section>

      <section className="grid gap-2" aria-labelledby="points-heading">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id="points-heading" className="eyebrow">Inspection points, in flying order</h3>
          <SmallButton pressed={placing === "point"} onClick={() => setPlacing(placing === "point" ? null : "point")}>
            {placing === "point" ? "Done" : "+ Add on the map"}
          </SmallButton>
        </div>
        {mission.points.length === 0 && (
          <p className="text-xs text-[var(--muted)]">
            None yet. Press “Add on the map”, then click where the drone should hold and record.
          </p>
        )}
        <ol className="grid gap-2">
          {mission.points.map((p, index) => (
            <PointRow key={p.id} point={p} index={index} count={mission.points.length}
                      flagged={flagged.has(p.id)} skipped={unflown.has(p.id)} ends={lands === p.id}
                      explicitEnd={mission.end_point_id === p.id}
                      selected={sameHandle(selected, { kind: "point", id: p.id })}
                      onSelect={() => setSelected({ kind: "point", id: p.id })}
                      onMove={(by) => move(index, by)}
                      onEnd={() => setMission((m) => (m.end_point_id === p.id ? clearEnd(m) : endAt(m, p.id)))}
                      onRemove={() => removePoint(p.id)}
                      fields={<PointFields point={p} box={box} band={band} minHold={limits.min_hold_s}
                                           locked={!sameHandle(selected, { kind: "point", id: p.id })}
                                           setPoint={(c) => setPoint(p.id, c)} />}
                      setLabel={(label) => setPoint(p.id, { label: label || null })} />
          ))}
        </ol>
      </section>
    </>
  );
}

function PointRow({ point: p, index, count, flagged, skipped, ends, explicitEnd, selected, onSelect, onMove, onEnd, onRemove, fields, setLabel }: {
  point: InspectionPoint;
  index: number;
  count: number;
  flagged: boolean;
  skipped: boolean;
  ends: boolean;
  explicitEnd: boolean;
  selected: boolean;
  onSelect: () => void;
  onMove: (by: -1 | 1) => void;
  onEnd: () => void;
  onRemove: () => void;
  fields: React.ReactNode;
  setLabel: (label: string) => void;
}) {
  return (
    <ObjectCard label={`Inspection point ${p.id}`} selected={selected} flagged={flagged} onSelect={onSelect}
                className={skipped ? "opacity-60" : ""}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="flex items-end gap-2">
          <span className="mono pb-2 text-sm font-bold">
            {p.id}{flagged && <span className="sr-only"> — has a problem</span>}
          </span>
          <TextField label="Label" value={p.label ?? ""} placeholder="e.g. Pump 2" width="w-32" onChange={setLabel}
                     readOnly={!selected} />
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <CardState selected={selected} />
          <SmallButton disabled={index === 0} onClick={() => onMove(-1)} title="Fly this one earlier">↑</SmallButton>
          <SmallButton disabled={index === count - 1} onClick={() => onMove(1)} title="Fly this one later">↓</SmallButton>
          <SmallButton pressed={explicitEnd} onClick={onEnd}
                       title={explicitEnd ? "Clear the end point — fly every point" : "End the flight here; later points are not flown"}>
            {explicitEnd ? "End ✓" : "End here"}
          </SmallButton>
          <SmallButton tone="danger" onClick={onRemove}>Remove</SmallButton>
        </div>
      </div>
      {(ends || skipped) && (
        <p className="text-xs">{ends ? "The flight lands here." : "After the end point — not flown."}</p>
      )}
      {fields}
    </ObjectCard>
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
