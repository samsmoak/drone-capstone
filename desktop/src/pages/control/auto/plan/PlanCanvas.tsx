/**
 * The floor plan, drawn to scale: an SVG whose units ARE metres.
 *
 * The viewBox is the room's map (the measured coverage, or the agent's default
 * area) plus a little margin, so one SVG unit is one metre and no pixel
 * conversion exists to get wrong. y is negated on the way in and out — the room
 * frame has y pointing up, SVG has it pointing down — and that is the only
 * transform. The bottom of the plan is the FRONT (geometry.ts, the words).
 *
 *   dashed outline   the room's map: nothing can be drawn outside it
 *   blue outline     the geofence — the room; click its edge to select it
 *   amber shapes     obstacles
 *   dashed line      the path, an arrow on every leg in the flying direction
 *   dots             inspection points, each with its HEIGHT (above the floor
 *                    where the drone takes off); red when the agent reports a
 *                    problem, faded when they come after the end point
 *   ring + END       the end point: the flight lands there
 *   square S         the planned start
 *   green D          the drone, where it is now — the real start of a flight
 *
 * SELECTING ONE THING FADES THE REST, here and in the 3-D view alike: the
 * geofence (the room) or one obstacle, whether it was clicked on the plan or
 * its panel was clicked in the form.
 *
 * EDITING: every shape the operator can move has a handle that is a real
 * control — focusable, named, moved with the arrow keys as well as the mouse.
 * A drag only reports where the pointer is; the editor decides what that means
 * and clamps it to the map (geometry.ts), so the canvas holds no rules. A
 * point's menu (right-click, or the context-menu key / Shift+F10 on a focused
 * point) is the editor's too.
 */

import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import type { Geofence, InspectionPoint, Obstacle, OuterBound, Problem, XY } from "@/lib/agent";
import { NUDGE_M, mapBox } from "./geometry";
import { legsOf, landsAt, unflownIds, type PathSource } from "./path";
import { SPACE_LABEL, insideOutline, type SpaceLayer } from "./space";

export type Handle =
  | { kind: "home" }
  | { kind: "point"; id: string }
  | { kind: "vertex"; index: number }
  | { kind: "obstacle"; id: string }
  | { kind: "fence" };

export function sameHandle(a: Handle | null, b: Handle | null): boolean {
  if (!a || !b || a.kind !== b.kind) return false;
  if (a.kind === "point" && b.kind === "point") return a.id === b.id;
  if (a.kind === "obstacle" && b.kind === "obstacle") return a.id === b.id;
  if (a.kind === "vertex" && b.kind === "vertex") return a.index === b.index;
  return true;
}

/** Whether `h` is one of the room's objects — the things selection fades
 *  everything else for. A path handle (a point, the start) fades nothing. */
export function isRoomObject(h: Handle | null): h is { kind: "fence" } | { kind: "obstacle"; id: string } | { kind: "vertex"; index: number } {
  return h !== null && (h.kind === "fence" || h.kind === "obstacle" || h.kind === "vertex");
}

/** How a point stands while a mission flies (the Fly step). */
export type PointState = "done" | "current" | "pending";

const MARGIN_M = 0.3;
const POINT_R = 0.07;
/** The invisible hit area around a handle — about 24 px at a typical scale. */
const HIT_R = 0.16;
/** How much of its colour a thing that is not selected keeps. */
const FADED = 0.28;

export type Editing = {
  selected: Handle | null;
  onSelect: (handle: Handle | null) => void;
  /** The pointer is at `to` (room metres) while dragging `handle`; `by` is the
   *  movement since the last report. */
  onDrag: (handle: Handle, to: XY, by: XY) => void;
  /** A click on empty floor, in room metres — placing a point or an obstacle. */
  onPlace?: (at: XY) => void;
  placing?: string | null;
  /** A point's menu, asked for at a place on screen. */
  onPointMenu?: (id: string, at: { x: number; y: number }) => void;
};

export function PlanCanvas({
  outer, fence, obstacles, path, takeoffHeight = 0.4, problems = [], drone = null,
  editing, label, progress, selected: shownSelected = null, className, space = null, sliceZ = null,
}: {
  /** The flyable space (space.ts), drawn under the plan; points outside it are ringed red. */
  space?: SpaceLayer | null;
  /** With a prediction: the height whose outline to draw. */
  sliceZ?: number | null;
  outer: OuterBound;
  fence: Geofence | null;
  obstacles: Obstacle[];
  /** The planned start, the points, and how the flight ends. */
  path: PathSource | null;
  takeoffHeight?: number;
  problems?: Problem[];
  drone?: XY | null;
  editing?: Editing;
  /** Names the drawing for a screen reader. */
  label: string;
  /** While a mission flies: each point done, being flown to/held, or ahead. */
  progress?: Record<string, PointState>;
  /** A selection to show when not editing (the 3-D view's twin). */
  selected?: Handle | null;
  className?: string;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [dragging, setDragging] = useState<{ handle: Handle; last: XY } | null>(null);

  const box = mapBox(outer);
  const vx = box.xMin - MARGIN_M;
  const vy = -(box.yMax + MARGIN_M);
  const vw = box.xMax - box.xMin + 2 * MARGIN_M;
  const vh = box.yMax - box.yMin + 2 * MARGIN_M;

  const current = editing?.selected ?? shownSelected;
  const focus = isRoomObject(current) ? current : null;
  const dim = (mine: boolean) => (focus && !mine ? FADED : 1);
  const fenceMine = focus?.kind === "fence" || focus?.kind === "vertex";

  const bad = new Set(problems.filter((p) => p.severity === "error").map((p) => p.where));
  const room = (event: { clientX: number; clientY: number }): XY | null => {
    const el = svg.current;
    const ctm = el?.getScreenCTM();
    if (!el || !ctm) return null;
    const pt = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
    return [pt.x, -pt.y];
  };

  const grab = (handle: Handle) => (event: PointerEvent<SVGElement>) => {
    if (!editing || event.button !== 0) return;
    event.stopPropagation();
    const at = room(event);
    if (!at) return;
    editing.onSelect(handle);
    if (handle.kind === "fence") return;            // selecting the room, not moving it
    setDragging({ handle, last: at });
    svg.current?.setPointerCapture(event.pointerId);
  };

  const move = (event: PointerEvent<SVGSVGElement>) => {
    if (!editing || !dragging) return;
    const at = room(event);
    if (!at) return;
    editing.onDrag(dragging.handle, at, [at[0] - dragging.last[0], at[1] - dragging.last[1]]);
    setDragging({ handle: dragging.handle, last: at });
  };

  const release = (event: PointerEvent<SVGSVGElement>) => {
    if (dragging) svg.current?.releasePointerCapture(event.pointerId);
    setDragging(null);
  };

  const floorClick = (event: PointerEvent<SVGSVGElement>) => {
    if (!editing || dragging || event.button !== 0) return;
    const at = room(event);
    if (!at) return;
    if (editing.placing && editing.onPlace) editing.onPlace(at);
    else editing.onSelect(null);
  };

  const keys = (handle: Handle, at: XY) => (event: KeyboardEvent<SVGElement>) => {
    if (!editing) return;
    const step: Record<string, XY> = {
      ArrowLeft: [-NUDGE_M, 0], ArrowRight: [NUDGE_M, 0],
      ArrowUp: [0, NUDGE_M], ArrowDown: [0, -NUDGE_M],
    };
    const by = step[event.key];
    if (by && handle.kind !== "fence") {
      event.preventDefault();
      editing.onSelect(handle);
      editing.onDrag(handle, [at[0] + by[0], at[1] + by[1]], by);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      editing.onSelect(handle);
    } else if (handle.kind === "point" && editing.onPointMenu
               && (event.key === "ContextMenu" || (event.key === "F10" && event.shiftKey))) {
      event.preventDefault();
      const r = (event.currentTarget as Element).getBoundingClientRect();
      editing.onPointMenu(handle.id, { x: r.right, y: r.bottom });
    }
  };

  // No `style` in here: spread after a shape's own style it would replace the
  // shape's fill and stroke (it did — obstacles drew solid black). The cursor
  // comes from the .plan-handle class instead.
  const handleProps = (handle: Handle, at: XY, name: string) => editing ? {
    role: "button",
    tabIndex: 0,
    "aria-label": handle.kind === "fence"
      ? `${name}. Select it to set its length, width and height.`
      : `${name}, ${(at[0] - box.xMin).toFixed(2)} m from left, ${(at[1] - box.yMin).toFixed(2)} m from front. Arrow keys move it.${handle.kind === "point" ? " Shift+F10 for its menu." : ""}`,
    "aria-pressed": sameHandle(editing.selected, handle),
    onPointerDown: grab(handle),
    onKeyDown: keys(handle, at),
    onContextMenu: handle.kind === "point" && editing.onPointMenu
      ? (event: React.MouseEvent) => {
        event.preventDefault();
        editing.onSelect(handle);
        editing.onPointMenu?.(handle.id, { x: event.clientX, y: event.clientY });
      } : undefined,
    className: dragging ? "plan-handle plan-handle-dragging" : "plan-handle",
  } : {};

  const selected = (handle: Handle) => sameHandle(current, handle);

  const legs = path ? legsOf(path, takeoffHeight) : [];
  const unflown = path ? unflownIds(path) : new Set<string>();
  const lastStop = path ? landsAt(path) : null;
  const points: InspectionPoint[] = path?.points ?? [];
  const home = path?.home ?? null;

  const gridLines: { x1: number; y1: number; x2: number; y2: number; major: boolean }[] = [];
  for (let x = Math.ceil(box.xMin * 2) / 2; x <= box.xMax + 1e-9; x += 0.5) {
    gridLines.push({ x1: x, y1: -box.yMin, x2: x, y2: -box.yMax, major: Math.abs(x % 1) < 1e-9 });
  }
  for (let y = Math.ceil(box.yMin * 2) / 2; y <= box.yMax + 1e-9; y += 0.5) {
    gridLines.push({ x1: box.xMin, y1: -y, x2: box.xMax, y2: -y, major: Math.abs(y % 1) < 1e-9 });
  }

  const polygon = (vertices: XY[]) => vertices.map(([x, y]) => `${x},${-y}`).join(" ");
  const thin = { vectorEffect: "non-scaling-stroke" as const };

  return (
    <svg
      ref={svg}
      viewBox={`${vx} ${vy} ${vw} ${vh}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={label}
      className={className ?? "block h-full max-h-[30rem] min-h-[16rem] w-full touch-none select-none bg-[var(--surface-2)]"}
      onPointerMove={move}
      onPointerUp={release}
      onPointerCancel={release}
      onPointerDown={floorClick}
      onContextMenu={(e) => { if (editing) e.preventDefault(); }}
      style={{ cursor: editing?.placing ? "crosshair" : undefined }}
    >
      {/* the grid: every half metre, every metre a little stronger */}
      {gridLines.map(({ major, ...ends }, i) => (
        <line key={i} {...ends} {...thin} style={{ stroke: "var(--grid)", strokeWidth: major ? 1.2 : 0.6 }} />
      ))}

      {/* the room's map: nothing may be drawn outside it */}
      <polygon points={polygon(outer.vertices)} fill="none" {...thin}
               style={{ stroke: "var(--muted)", strokeWidth: 1.2, strokeDasharray: "5 4" }} />
      <text x={box.xMin + 0.05} y={-box.yMax + 0.16} style={{ fill: "var(--muted)", fontSize: 0.12 }}>
        Room map (the agent&apos;s flying area)
      </text>

      {/* where "from left" and "from front" are measured from, and which way
          length and width run */}
      <g aria-hidden="true">
        <line x1={box.xMin} y1={-box.yMin} x2={box.xMin + 0.35} y2={-box.yMin} {...thin} style={{ stroke: "var(--axis)", strokeWidth: 2 }} />
        <line x1={box.xMin} y1={-box.yMin} x2={box.xMin} y2={-box.yMin - 0.35} {...thin} style={{ stroke: "var(--axis)", strokeWidth: 2 }} />
        <text x={box.xMin + 0.38} y={-box.yMin + 0.04} style={{ fill: "var(--muted)", fontSize: 0.1 }}>length</text>
        <text x={box.xMin + 0.03} y={-box.yMin - 0.38} style={{ fill: "var(--muted)", fontSize: 0.1 }}>width</text>
        <text x={box.xMin + 0.03} y={-box.yMin + 0.16} style={{ fill: "var(--muted)", fontSize: 0.1 }}>front</text>
      </g>

      {space && <SpaceArea space={space} sliceZ={sliceZ} path={path} />}

      {fence && (
        <g opacity={dim(fenceMine)}>
          <polygon points={polygon(fence.vertices)} {...thin}
                   style={{ fill: "var(--primary)", fillOpacity: fenceMine ? 0.12 : 0.06, stroke: "var(--primary)",
                            strokeWidth: fenceMine ? 3.2 : 2, pointerEvents: "none" }} />
          {editing && (
            // The room's own handle: a wide invisible band along its edge, so
            // a click on the floor inside it still places or deselects.
            <polygon points={polygon(fence.vertices)} {...handleProps({ kind: "fence" }, fence.vertices[0], "The room — its geofence")}
                     style={{ fill: "none", stroke: "transparent", strokeWidth: HIT_R * 1.2 }} />
          )}
        </g>
      )}

      {obstacles.map((o) => {
        const mine = selected({ kind: "obstacle", id: o.id });
        const style = {
          fill: "var(--status-warning)", fillOpacity: mine ? 0.34 : 0.18, stroke: "var(--status-warning)",
          strokeWidth: mine ? 3.2 : 1.6,
        };
        const centre: XY = o.kind === "circle" ? o.points[0]
          : [(o.points[0][0] + o.points[1][0]) / 2, (o.points[0][1] + o.points[1][1]) / 2];
        const props = handleProps({ kind: "obstacle", id: o.id }, centre, `Obstacle ${o.label ?? o.kind}`);
        let shape: ReactNode;
        if (o.kind === "circle") {
          shape = <circle cx={o.points[0][0]} cy={-o.points[0][1]} r={o.radius} {...thin} style={style} {...props} />;
        } else if (o.kind === "rectangle") {
          const [[x1, y1], [x2, y2]] = o.points;
          shape = (
            <rect x={Math.min(x1, x2)} y={-Math.max(y1, y2)} width={Math.abs(x2 - x1)}
                  height={Math.abs(y2 - y1)} {...thin} style={style} {...props} />
          );
        } else {
          const [[x1, y1], [x2, y2]] = o.points;
          shape = (
            <g {...props}>
              <line x1={x1} y1={-y1} x2={x2} y2={-y2} {...thin} style={{ ...style, strokeWidth: mine ? 4.5 : 3 }} />
              <line x1={x1} y1={-y1} x2={x2} y2={-y2} style={{ stroke: "transparent", strokeWidth: HIT_R * 1.5 }} />
            </g>
          );
        }
        return <g key={o.id} opacity={dim(mine)}>{shape}</g>;
      })}

      <g opacity={focus ? FADED : 1}>
        {legs.map((leg, i) => {
          const wrong = bad.has(leg.name);
          const colour = wrong ? "var(--status-critical)" : "var(--foreground)";
          return (
            <g key={`${leg.name}-${i}`}>
              <line x1={leg.a[0]} y1={-leg.a[1]} x2={leg.b[0]} y2={-leg.b[1]} {...thin}
                    style={{ stroke: colour, strokeOpacity: wrong ? 1 : 0.55,
                             strokeWidth: wrong ? 2.2 : 1.3, strokeDasharray: "6 4" }} />
              <Arrow a={leg.a} b={leg.b} colour={colour} />
            </g>
          );
        })}
      </g>

      {fence && editing && fence.shape === "polygon" && fence.vertices.map(([x, y], index) => (
        <g key={`v${index}`} opacity={dim(fenceMine)} {...handleProps({ kind: "vertex", index }, [x, y], `Geofence corner ${index + 1}`)}>
          <circle cx={x} cy={-y} r={HIT_R} style={{ fill: "transparent" }} />
          <rect x={x - 0.05} y={-y - 0.05} width={0.1} height={0.1} {...thin}
                style={{ fill: "var(--surface)", stroke: "var(--primary)", strokeWidth: selected({ kind: "vertex", index }) ? 3 : 1.5 }} />
        </g>
      ))}

      <g opacity={focus ? FADED : 1}>
        {home && (
          <g {...handleProps({ kind: "home" }, home, "The planned start")}>
            <circle cx={home[0]} cy={-home[1]} r={HIT_R} style={{ fill: "transparent" }} />
            <rect x={home[0] - 0.07} y={-home[1] - 0.07} width={0.14} height={0.14} {...thin}
                  style={{ fill: "var(--surface)", stroke: bad.has("home") ? "var(--status-critical)" : "var(--foreground)",
                           strokeWidth: selected({ kind: "home" }) ? 3 : 1.6 }} />
            <text x={home[0]} y={-home[1] + 0.045} textAnchor="middle"
                  style={{ fill: "var(--foreground)", fontSize: 0.11, fontWeight: 700 }}>S</text>
          </g>
        )}

        {points.map((p) => {
          const wrong = bad.has(p.id);
          const skipped = unflown.has(p.id);
          const state = progress?.[p.id];
          const isEnd = p.id === lastStop;
          const fill = wrong ? "var(--status-critical)"
            : state === "done" ? "var(--status-good)"
            : state === "current" ? "var(--status-warning)" : "var(--primary)";
          return (
            <g key={p.id} opacity={skipped ? 0.4 : 1}
               {...handleProps({ kind: "point", id: p.id }, [p.x_m, p.y_m], `Inspection point ${p.id}${isEnd ? ", the end point" : ""}${skipped ? ", after the end point — not flown" : ""}`)}>
              <circle cx={p.x_m} cy={-p.y_m} r={HIT_R} style={{ fill: "transparent" }} />
              {isEnd && (
                <circle cx={p.x_m} cy={-p.y_m} r={POINT_R * 1.9} {...thin}
                        style={{ fill: "none", stroke: "var(--foreground)", strokeWidth: 1.6 }} />
              )}
              <circle cx={p.x_m} cy={-p.y_m} r={POINT_R} {...thin}
                      style={{ fill: skipped ? "var(--surface)" : fill, stroke: skipped ? "var(--primary)" : "var(--surface)",
                               strokeWidth: selected({ kind: "point", id: p.id }) ? 3 : 1.2,
                               strokeDasharray: skipped ? "2 2" : undefined }} />
              <text x={p.x_m + 0.1} y={-p.y_m + 0.04}
                    style={{ fill: wrong ? "var(--status-critical)" : "var(--foreground)", fontSize: 0.12, fontWeight: 700 }}>
                {p.id} · {p.z_m.toFixed(2)} m{wrong ? " !" : ""}{isEnd ? " · END" : ""}
              </text>
            </g>
          );
        })}
      </g>

      {drone && (
        <g role="img" aria-label={`The drone, ${(drone[0] - box.xMin).toFixed(2)} m from left and ${(drone[1] - box.yMin).toFixed(2)} m from front`}>
          {/* The ring carries the colour; the letter sits on --surface in
              --foreground, whose contrast holds in both themes. */}
          <circle cx={drone[0]} cy={-drone[1]} r={0.1} {...thin}
                  style={{ fill: "var(--surface)", stroke: "var(--status-good)", strokeWidth: 3 }} />
          <text x={drone[0]} y={-drone[1] + 0.045} textAnchor="middle"
                style={{ fill: "var(--foreground)", fontSize: 0.13, fontWeight: 800 }}>D</text>
        </g>
      )}
    </svg>
  );
}

/** A chevron at the middle of a leg, pointing the way the drone flies it. */
function Arrow({ a, b, colour }: { a: XY; b: XY; colour: string }) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const length = Math.hypot(dx, dy);
  if (length < 0.2) return null;
  const angle = (Math.atan2(-dy, dx) * 180) / Math.PI;      // SVG's y is down
  const mx = (a[0] + b[0]) / 2;
  const my = -(a[1] + b[1]) / 2;
  return (
    <polygon points="0.07,0 -0.05,0.05 -0.05,-0.05" transform={`translate(${mx} ${my}) rotate(${angle})`}
             style={{ fill: colour }} aria-hidden="true" />
  );
}

/** The flyable space from above: shaded where the drone's position can be
 *  trusted, a dashed edge, the predicted outline at the chosen height, and a
 *  red ring round any point of the plan outside it. */
function SpaceArea({ space, sliceZ, path }: { space: SpaceLayer; sliceZ: number | null; path: PathSource | null }) {
  const thin = { vectorEffect: "non-scaling-stroke" as const };
  const polygon = (vertices: XY[]) => vertices.map(([x, y]) => `${x},${-y}`).join(" ");
  const slice = sliceZ === null || !space.slices?.length ? null
    : space.slices.reduce((a, b) => (Math.abs(b.z_m - sliceZ) < Math.abs(a.z_m - sliceZ) ? b : a));
  const outline = slice && slice.outline.length >= 3 ? slice.outline : space.vertices;
  const outside = (path?.points ?? []).filter((p) => outline.length >= 3 && !insideOutline([p.x_m, p.y_m], outline));
  return (
    <g aria-label={SPACE_LABEL[space.kind]}>
      {outline.length >= 3 && (
        <polygon points={polygon(outline)} {...thin}
                 style={{ fill: "var(--status-good)", fillOpacity: 0.14, stroke: "var(--status-good)",
                          strokeWidth: 1.6, strokeDasharray: space.kind === "measured" ? undefined : "4 3",
                          pointerEvents: "none" }} />
      )}
      {outside.map((p) => (
        <circle key={p.id} cx={p.x_m} cy={-p.y_m} r={0.11} {...thin}
                style={{ fill: "none", stroke: "var(--status-critical)", strokeWidth: 2.2, pointerEvents: "none" }}>
          <title>{`${p.id} is outside the flyable space`}</title>
        </circle>
      ))}
    </g>
  );
}

