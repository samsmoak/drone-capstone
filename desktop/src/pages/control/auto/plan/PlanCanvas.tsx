/**
 * The floor plan, drawn to scale: an SVG whose units ARE metres.
 *
 * The viewBox is the room's map (the measured coverage, or the agent's default
 * area) plus a little margin, so one SVG unit is one metre and no pixel
 * conversion exists to get wrong. y is negated on the way in and out — the room
 * frame has y pointing up, SVG has it pointing down — and that is the only
 * transform.
 *
 *   dashed outline   the room's map: nothing can be drawn outside it
 *   blue outline     the geofence
 *   amber shapes     obstacles
 *   dashed line      the path: home → points → home
 *   dots             inspection points; red when the agent reports a problem
 *   square           home, where the drone sits before takeoff
 *   green cross      where the drone is now, when a drone is connected
 *
 * EDITING: every shape the operator can move has a handle that is a real
 * control — focusable, named, moved with the arrow keys as well as the mouse.
 * A drag only reports where the pointer is; the editor decides what that means
 * and clamps it to the map (geometry.ts), so the canvas holds no rules.
 */

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { Geofence, InspectionPoint, Obstacle, OuterBound, Problem, XY } from "@/lib/agent";
import { NUDGE_M, mapBox } from "./geometry";

export type Handle =
  | { kind: "home" }
  | { kind: "point"; id: string }
  | { kind: "vertex"; index: number }
  | { kind: "obstacle"; id: string };

export function sameHandle(a: Handle | null, b: Handle | null): boolean {
  if (!a || !b || a.kind !== b.kind) return false;
  if (a.kind === "point" && b.kind === "point") return a.id === b.id;
  if (a.kind === "obstacle" && b.kind === "obstacle") return a.id === b.id;
  if (a.kind === "vertex" && b.kind === "vertex") return a.index === b.index;
  return true;
}

const MARGIN_M = 0.3;
const POINT_R = 0.07;
/** The invisible hit area around a handle — about 24 px at a typical scale. */
const HIT_R = 0.16;

type Editing = {
  selected: Handle | null;
  onSelect: (handle: Handle | null) => void;
  /** The pointer is at `to` (room metres) while dragging `handle`; `by` is the
   *  movement since the last report. */
  onDrag: (handle: Handle, to: XY, by: XY) => void;
  /** A click on empty floor, in room metres — placing a point or an obstacle. */
  onPlace?: (at: XY) => void;
  placing?: string | null;
};

export function PlanCanvas({
  outer, fence, obstacles, home, points, returnToStart, problems = [], drone = null,
  editing, label,
}: {
  outer: OuterBound;
  fence: Geofence | null;
  obstacles: Obstacle[];
  home: XY | null;
  points: InspectionPoint[];
  returnToStart: boolean;
  problems?: Problem[];
  drone?: XY | null;
  editing?: Editing;
  /** Names the drawing for a screen reader. */
  label: string;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [dragging, setDragging] = useState<{ handle: Handle; last: XY } | null>(null);

  const box = mapBox(outer);
  const vx = box.xMin - MARGIN_M;
  const vy = -(box.yMax + MARGIN_M);
  const vw = box.xMax - box.xMin + 2 * MARGIN_M;
  const vh = box.yMax - box.yMin + 2 * MARGIN_M;

  const bad = new Set(problems.filter((p) => p.severity === "error").map((p) => p.where));
  const room = (event: { clientX: number; clientY: number }): XY | null => {
    const el = svg.current;
    const ctm = el?.getScreenCTM();
    if (!el || !ctm) return null;
    const pt = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
    return [pt.x, -pt.y];
  };

  const grab = (handle: Handle) => (event: PointerEvent<SVGElement>) => {
    if (!editing) return;
    event.stopPropagation();
    const at = room(event);
    if (!at) return;
    editing.onSelect(handle);
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
    if (!editing || dragging) return;
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
    if (by) {
      event.preventDefault();
      editing.onSelect(handle);
      editing.onDrag(handle, [at[0] + by[0], at[1] + by[1]], by);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      editing.onSelect(handle);
    }
  };

  // No `style` in here: spread after a shape's own style it would replace the
  // shape's fill and stroke (it did — obstacles drew solid black). The cursor
  // comes from the .plan-handle class instead.
  const handleProps = (handle: Handle, at: XY, name: string) => editing ? {
    role: "button",
    tabIndex: 0,
    "aria-label": `${name} at ${at[0].toFixed(2)}, ${at[1].toFixed(2)} metres. Arrow keys move it.`,
    "aria-pressed": sameHandle(editing.selected, handle),
    onPointerDown: grab(handle),
    onKeyDown: keys(handle, at),
    className: dragging ? "plan-handle plan-handle-dragging" : "plan-handle",
  } : {};

  const selected = (handle: Handle) => editing ? sameHandle(editing.selected, handle) : false;

  // The path, stop by stop, and which legs the agent flagged.
  const stops: { at: XY; name: string }[] = home ? [{ at: home, name: "home" }] : [];
  points.forEach((p) => stops.push({ at: [p.x_m, p.y_m], name: p.id }));
  if (home && returnToStart && points.length) stops.push({ at: home, name: "home" });
  const legs = stops.slice(1).map((b, i) => ({ a: stops[i].at, b: b.at, name: `${stops[i].name} → ${b.name}` }));

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
      className="block h-full max-h-[30rem] min-h-[16rem] w-full touch-none select-none bg-[var(--surface-2)]"
      onPointerMove={move}
      onPointerUp={release}
      onPointerCancel={release}
      onPointerDown={floorClick}
      style={{ cursor: editing?.placing ? "crosshair" : undefined }}
    >
      {/* the grid: every half metre, every metre a little stronger */}
      {gridLines.map((g, i) => (
        <line key={i} {...g} {...thin} style={{ stroke: "var(--grid)", strokeWidth: g.major ? 1.2 : 0.6 }} />
      ))}

      {/* the room's map: nothing may be drawn outside it */}
      <polygon points={polygon(outer.vertices)} fill="none" {...thin}
               style={{ stroke: "var(--muted)", strokeWidth: 1.2, strokeDasharray: "5 4" }} />
      <text x={box.xMin + 0.05} y={-box.yMax + 0.16} style={{ fill: "var(--muted)", fontSize: 0.12 }}>
        {outer.measured ? "Room map (measured coverage)" : "Room map (default area — coverage not measured)"}
      </text>

      {/* the Lighthouse origin */}
      <g aria-hidden="true">
        <line x1={0} y1={0} x2={0.3} y2={0} {...thin} style={{ stroke: "var(--axis)", strokeWidth: 1.5 }} />
        <line x1={0} y1={0} x2={0} y2={-0.3} {...thin} style={{ stroke: "var(--axis)", strokeWidth: 1.5 }} />
        <text x={0.32} y={0.04} style={{ fill: "var(--muted)", fontSize: 0.11 }}>x</text>
        <text x={-0.04} y={-0.33} style={{ fill: "var(--muted)", fontSize: 0.11 }}>y</text>
      </g>

      {fence && (
        <polygon points={polygon(fence.vertices)} {...thin}
                 style={{ fill: "var(--primary)", fillOpacity: 0.06, stroke: "var(--primary)", strokeWidth: 2 }} />
      )}

      {obstacles.map((o) => {
        const style = {
          fill: "var(--status-warning)", fillOpacity: 0.18, stroke: "var(--status-warning)",
          strokeWidth: selected({ kind: "obstacle", id: o.id }) ? 3 : 1.6,
        };
        const centre: XY = o.kind === "circle" ? o.points[0]
          : [(o.points[0][0] + o.points[1][0]) / 2, (o.points[0][1] + o.points[1][1]) / 2];
        const props = handleProps({ kind: "obstacle", id: o.id }, centre, `Obstacle ${o.label ?? o.id}`);
        if (o.kind === "circle") {
          return <circle key={o.id} cx={o.points[0][0]} cy={-o.points[0][1]} r={o.radius} {...thin} style={style} {...props} />;
        }
        if (o.kind === "rectangle") {
          const [[x1, y1], [x2, y2]] = o.points;
          return (
            <rect key={o.id} x={Math.min(x1, x2)} y={-Math.max(y1, y2)} width={Math.abs(x2 - x1)}
                  height={Math.abs(y2 - y1)} {...thin} style={style} {...props} />
          );
        }
        const [[x1, y1], [x2, y2]] = o.points;
        return (
          <g key={o.id} {...props}>
            <line x1={x1} y1={-y1} x2={x2} y2={-y2} {...thin} style={{ ...style, strokeWidth: 3 }} />
            <line x1={x1} y1={-y1} x2={x2} y2={-y2} style={{ stroke: "transparent", strokeWidth: HIT_R * 1.5 }} />
          </g>
        );
      })}

      {legs.map((leg) => (
        <line key={leg.name} x1={leg.a[0]} y1={-leg.a[1]} x2={leg.b[0]} y2={-leg.b[1]} {...thin}
              style={{
                stroke: bad.has(leg.name) ? "var(--status-critical)" : "var(--foreground)",
                strokeOpacity: bad.has(leg.name) ? 1 : 0.55,
                strokeWidth: bad.has(leg.name) ? 2.2 : 1.3, strokeDasharray: "6 4",
              }} />
      ))}

      {fence && editing && fence.shape === "polygon" && fence.vertices.map(([x, y], index) => (
        <g key={`v${index}`} {...handleProps({ kind: "vertex", index }, [x, y], `Geofence corner ${index + 1}`)}>
          <circle cx={x} cy={-y} r={HIT_R} style={{ fill: "transparent" }} />
          <rect x={x - 0.05} y={-y - 0.05} width={0.1} height={0.1} {...thin}
                style={{ fill: "var(--surface)", stroke: "var(--primary)", strokeWidth: selected({ kind: "vertex", index }) ? 3 : 1.5 }} />
        </g>
      ))}

      {home && (
        <g {...handleProps({ kind: "home" }, home, "Home")}>
          <circle cx={home[0]} cy={-home[1]} r={HIT_R} style={{ fill: "transparent" }} />
          <rect x={home[0] - 0.07} y={-home[1] - 0.07} width={0.14} height={0.14} {...thin}
                style={{ fill: "var(--surface)", stroke: bad.has("home") ? "var(--status-critical)" : "var(--foreground)",
                         strokeWidth: selected({ kind: "home" }) ? 3 : 1.6 }} />
          <text x={home[0] + 0.1} y={-home[1] + 0.04} style={{ fill: "var(--foreground)", fontSize: 0.12, fontWeight: 700 }}>H</text>
        </g>
      )}

      {points.map((p) => {
        const wrong = bad.has(p.id);
        return (
          <g key={p.id} {...handleProps({ kind: "point", id: p.id }, [p.x_m, p.y_m], `Inspection point ${p.id}`)}>
            <circle cx={p.x_m} cy={-p.y_m} r={HIT_R} style={{ fill: "transparent" }} />
            <circle cx={p.x_m} cy={-p.y_m} r={POINT_R} {...thin}
                    style={{ fill: wrong ? "var(--status-critical)" : "var(--primary)",
                             stroke: "var(--surface)", strokeWidth: selected({ kind: "point", id: p.id }) ? 3 : 1.2 }} />
            <text x={p.x_m + 0.1} y={-p.y_m + 0.04}
                  style={{ fill: wrong ? "var(--status-critical)" : "var(--foreground)", fontSize: 0.12, fontWeight: 700 }}>
              {p.id}{wrong ? " !" : ""}
            </text>
          </g>
        );
      })}

      {drone && (
        <g aria-label={`The drone, at ${drone[0].toFixed(2)}, ${drone[1].toFixed(2)} metres`} role="img">
          <line x1={drone[0] - 0.08} y1={-drone[1]} x2={drone[0] + 0.08} y2={-drone[1]} {...thin}
                style={{ stroke: "var(--status-good)", strokeWidth: 2.5 }} />
          <line x1={drone[0]} y1={-drone[1] - 0.08} x2={drone[0]} y2={-drone[1] + 0.08} {...thin}
                style={{ stroke: "var(--status-good)", strokeWidth: 2.5 }} />
        </g>
      )}
    </svg>
  );
}
