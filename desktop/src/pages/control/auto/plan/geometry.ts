/**
 * The editor's geometry: building shapes from their dimensions, reading the
 * dimensions back, and keeping everything inside the room's map.
 *
 * WHAT THIS IS NOT: the safety rules. Whether a point is too near an obstacle,
 * whether a leg leaves the fence, whether a hold is long enough — all of that is
 * the AGENT's (backend/agent/cropwatcher/mission/plan/validate.py), and the
 * editor asks it (api.validateMission) rather than keeping a second copy that
 * could disagree. This file only draws and clamps.
 *
 * THE ROOM'S MAP bounds everything. The drone and its Lighthouse deck do not see
 * walls — this drone has no distance sensor — so the map is where the drone's
 * position can be trusted: the room's measured coverage, or the agent's default
 * area until that is measured (OuterBound). Every dimension typed or dragged is
 * clamped to it, so no shape can be made bigger than the space the drone can fly.
 */

import type { Geofence, InspectionPoint, Obstacle, OuterBound, XY } from "@/lib/agent";

export type Box = { xMin: number; yMin: number; xMax: number; yMax: number };

export const CIRCLE_SIDES = 32;
/** How far one arrow-key press moves the selected shape. */
export const NUDGE_M = 0.05;
/** Nothing is made smaller than this: a 10 cm shape is a typo, not an object. */
export const MIN_SIZE_M = 0.1;

export function boxOf(vertices: XY[]): Box {
  const xs = vertices.map(([x]) => x);
  const ys = vertices.map(([, y]) => y);
  return { xMin: Math.min(...xs), yMin: Math.min(...ys), xMax: Math.max(...xs), yMax: Math.max(...ys) };
}

export function mapBox(outer: OuterBound): Box {
  return boxOf(outer.vertices);
}

export function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}

export function clampXY([x, y]: XY, box: Box): XY {
  return [clamp(x, box.xMin, box.xMax), clamp(y, box.yMin, box.yMax)];
}

/** Round to the centimetre: the estimator cannot tell finer apart. */
export function cm(value: number): number {
  return Math.round(value * 100) / 100;
}

// ── the geofence ─────────────────────────────────────────────────────────

export function rectangleFence(xMin: number, yMin: number, width: number, depth: number,
                               band: Pick<Geofence, "z_min" | "z_max">): Geofence {
  return {
    shape: "rectangle", ...band,
    vertices: [[xMin, yMin], [xMin + width, yMin], [xMin + width, yMin + depth], [xMin, yMin + depth]]
      .map(([x, y]) => [cm(x), cm(y)] as XY),
  };
}

export function circleFence(cx: number, cy: number, radius: number,
                            band: Pick<Geofence, "z_min" | "z_max">): Geofence {
  const step = (2 * Math.PI) / CIRCLE_SIDES;
  return {
    shape: "circle", ...band,
    vertices: Array.from({ length: CIRCLE_SIDES }, (_, i) =>
      [cm(cx + radius * Math.cos(i * step)), cm(cy + radius * Math.sin(i * step))] as XY),
  };
}

/** A rectangle's dimensions, read back from its corners. */
export function rectangleOf(fence: Geofence): { xMin: number; yMin: number; width: number; depth: number } {
  const b = boxOf(fence.vertices);
  return { xMin: b.xMin, yMin: b.yMin, width: cm(b.xMax - b.xMin), depth: cm(b.yMax - b.yMin) };
}

/** A circle's centre and radius, read back from its 32 corners. */
export function circleOf(fence: Geofence): { cx: number; cy: number; radius: number } {
  const b = boxOf(fence.vertices);
  const cx = (b.xMin + b.xMax) / 2;
  const cy = (b.yMin + b.yMax) / 2;
  return { cx: cm(cx), cy: cm(cy), radius: cm((b.xMax - b.xMin) / 2) };
}

/** The largest rectangle a new room starts as: the map, less half a metre. */
export function defaultFence(outer: OuterBound, band: Pick<Geofence, "z_min" | "z_max">): Geofence {
  const m = mapBox(outer);
  const inset = Math.min(0.5, (m.xMax - m.xMin) / 4, (m.yMax - m.yMin) / 4);
  return rectangleFence(m.xMin + inset, m.yMin + inset,
                        m.xMax - m.xMin - 2 * inset, m.yMax - m.yMin - 2 * inset, band);
}

/** Move every vertex of a fence so its box stays inside the map. */
export function fitFence(fence: Geofence, box: Box): Geofence {
  return { ...fence, vertices: fence.vertices.map((v) => clampXY(v, box).map(cm) as XY) };
}

// ── obstacles ────────────────────────────────────────────────────────────

export type ObstacleDimensions =
  | { kind: "line"; x1: number; y1: number; x2: number; y2: number }
  | { kind: "rectangle"; cx: number; cy: number; width: number; depth: number }
  | { kind: "circle"; cx: number; cy: number; radius: number };

export function dimensionsOf(o: Obstacle): ObstacleDimensions {
  if (o.kind === "circle") {
    const [cx, cy] = o.points[0];
    return { kind: "circle", cx, cy, radius: o.radius ?? MIN_SIZE_M };
  }
  const [[x1, y1], [x2, y2]] = o.points;
  if (o.kind === "line") return { kind: "line", x1, y1, x2, y2 };
  return {
    kind: "rectangle", cx: cm((x1 + x2) / 2), cy: cm((y1 + y2) / 2),
    width: cm(Math.abs(x2 - x1)), depth: cm(Math.abs(y2 - y1)),
  };
}

/** Build an obstacle from its dimensions, sized and placed inside the map. */
export function obstacleFrom(o: Obstacle, d: ObstacleDimensions, box: Box): Obstacle {
  const mapW = box.xMax - box.xMin;
  const mapD = box.yMax - box.yMin;
  if (d.kind === "circle") {
    const radius = clamp(d.radius, MIN_SIZE_M / 2, Math.min(mapW, mapD) / 2);
    const cx = clamp(d.cx, box.xMin + radius, box.xMax - radius);
    const cy = clamp(d.cy, box.yMin + radius, box.yMax - radius);
    return { ...o, kind: "circle", points: [[cm(cx), cm(cy)]], radius: cm(radius) };
  }
  if (d.kind === "rectangle") {
    const width = clamp(d.width, MIN_SIZE_M, mapW);
    const depth = clamp(d.depth, MIN_SIZE_M, mapD);
    const cx = clamp(d.cx, box.xMin + width / 2, box.xMax - width / 2);
    const cy = clamp(d.cy, box.yMin + depth / 2, box.yMax - depth / 2);
    return { ...o, kind: "rectangle", radius: undefined, points: [
      [cm(cx - width / 2), cm(cy - depth / 2)], [cm(cx + width / 2), cm(cy + depth / 2)],
    ] };
  }
  const a = clampXY([d.x1, d.y1], box);
  const b = clampXY([d.x2, d.y2], box);
  return { ...o, kind: "line", radius: undefined, points: [a.map(cm) as XY, b.map(cm) as XY] };
}

/** Move a whole obstacle by (dx, dy), stopping at the edge of the map. */
export function moveObstacle(o: Obstacle, dx: number, dy: number, box: Box): Obstacle {
  const d = dimensionsOf(o);
  if (d.kind === "line") {
    return obstacleFrom(o, { ...d, x1: d.x1 + dx, y1: d.y1 + dy, x2: d.x2 + dx, y2: d.y2 + dy }, box);
  }
  return obstacleFrom(o, { ...d, cx: d.cx + dx, cy: d.cy + dy }, box);
}

export function newObstacle(kind: Obstacle["kind"], at: XY, box: Box, id: string): Obstacle {
  const base: Obstacle = { id, kind, label: null, points: [] };
  if (kind === "circle") return obstacleFrom(base, { kind, cx: at[0], cy: at[1], radius: 0.2 }, box);
  if (kind === "rectangle") {
    return obstacleFrom(base, { kind, cx: at[0], cy: at[1], width: 0.6, depth: 0.4 }, box);
  }
  return obstacleFrom(base, { kind, x1: at[0] - 0.4, y1: at[1], x2: at[0] + 0.4, y2: at[1] }, box);
}

// ── inspection points ────────────────────────────────────────────────────

/** P1, P2, … — the next id not already taken. Ids never change once saved:
 *  every reading taken at a point is stamped with it. */
export function nextPointId(points: InspectionPoint[]): string {
  const taken = new Set(points.map((p) => p.id));
  for (let n = points.length + 1; ; n++) {
    if (!taken.has(`P${n}`)) return `P${n}`;
  }
}

export function newId(): string {
  // Letters, digits and dashes only — what the agent accepts for a file name.
  return crypto.randomUUID();
}

export function lengthOf([x1, y1]: XY, [x2, y2]: XY): number {
  return Math.hypot(x2 - x1, y2 - y1);
}
