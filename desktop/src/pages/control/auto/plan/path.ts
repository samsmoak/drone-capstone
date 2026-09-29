/**
 * The path as it will be flown — shared by the 2-D plan, the 3-D room map and
 * the lists beside them, so all three agree on what flies.
 *
 * It mirrors the agent's own Mission.legs() and flown_points
 * (backend/agent/cropwatcher/mission/plan/mission.py), including the leg
 * names ("home → P1"), because the agent's problems name legs that way and a
 * leg the agent flags must be the leg drawn red. This is drawing, not
 * checking: whether a leg is safe is still only ever the agent's answer.
 *
 *   start      the planned start ("home" in the data). The flight itself
 *              starts from wherever the drone is (Mission.from_start) — the
 *              Check step shows that path; the plan is drawn from here.
 *   points     in flying order, up to the END POINT. Points after it stay in
 *              the plan, drawn faded, and are not flown.
 *   return     back over the start — only with no end point.
 */

import type { InspectionPoint, Mission, XY } from "@/lib/agent";

export type PathSource = Pick<Mission, "home" | "points" | "return_to_start" | "end_point_id">;

export type Leg = { a: XY; b: XY; name: string; za: number; zb: number };

/** The points actually flown, in order. */
export function flownPoints(m: PathSource): InspectionPoint[] {
  const end = m.end_point_id ?? null;
  const index = end === null ? -1 : m.points.findIndex((p) => p.id === end);
  return index < 0 ? m.points : m.points.slice(0, index + 1);
}

/** Whether the flight comes back over its start: never with an end point. */
export function returnsHome(m: PathSource): boolean {
  return m.return_to_start && !m.end_point_id;
}

/** The point the flight lands at, or null when it lands back at the start. */
export function landsAt(m: PathSource): string | null {
  if (returnsHome(m)) return null;
  const flown = flownPoints(m);
  return flown.length ? flown[flown.length - 1].id : null;
}

/** Every leg flown, named the agent's way, with the height at each end
 *  (the start is flown at the takeoff height). */
export function legsOf(m: PathSource, takeoffHeight: number): Leg[] {
  const stops: { at: XY; name: string; z: number }[] = [{ at: m.home, name: "home", z: takeoffHeight }];
  for (const p of flownPoints(m)) stops.push({ at: [p.x_m, p.y_m], name: p.id, z: p.z_m });
  if (returnsHome(m) && stops.length > 1) stops.push({ at: m.home, name: "home", z: takeoffHeight });
  return stops.slice(1).map((b, i) => ({
    a: stops[i].at, b: b.at, name: `${stops[i].name} → ${b.name}`, za: stops[i].z, zb: b.z,
  }));
}

/** Ids of points in the plan that are not flown (after the end point). */
export function unflownIds(m: PathSource): Set<string> {
  const flown = new Set(flownPoints(m).map((p) => p.id));
  return new Set(m.points.filter((p) => !flown.has(p.id)).map((p) => p.id));
}

/** Make `id` where the flight ends. The last point needs no end point — "land
 *  at the last point" is simply not returning, so points added later are still
 *  flown. */
export function endAt<T extends PathSource>(m: T, id: string): T {
  const last = m.points[m.points.length - 1]?.id;
  return { ...m, end_point_id: id === last ? null : id, return_to_start: false };
}

/** Clear the end point: every point flies, and the flight lands at the last. */
export function clearEnd<T extends PathSource>(m: T): T {
  return { ...m, end_point_id: null };
}

/** Fly the points the other way round. The end point stays the end point, so
 *  the drone approaches it from the other side. */
export function reversed<T extends PathSource>(m: T): T {
  return { ...m, points: [...m.points].reverse() };
}

/** How far apart two positions are, in metres. */
export function distance([x1, y1]: XY, [x2, y2]: XY): number {
  return Math.hypot(x2 - x1, y2 - y1);
}
