/**
 * The flyable space, as the room maps draw it (2026-10-01, Samuel: "show what
 * is possible", a see-through blob the plan sits inside).
 *
 * It is where the drone's position can be trusted — Lighthouse coverage
 * (backend mission/plan/coverage.py) — never walls: this drone senses none.
 *   predicted  where the measured base station reaches, over the whole map:
 *              what the plan that will fly is fitted into (2026-10-05)
 *   measured   a walked survey saved on the room (older rooms)
 *   survey     the outline growing while the drone is carried round
 */

import type { RoomCoverage, XY } from "@/lib/agent";

export type SpaceLayer = {
  kind: "measured" | "predicted" | "survey";
  vertices: XY[];
  z_min: number;
  z_max: number;
  /** A prediction's outline at each height, low to high. */
  slices?: { z_m: number; outline: XY[] }[];
};

export const SPACE_LABEL: Record<SpaceLayer["kind"], string> = {
  measured: "Flyable space (walked)",
  predicted: "Flyable space — where the base station reaches",
  survey: "Survey so far",
};

/** Ray casting — the same inside test the agent's shapes.point_in_polygon makes. */
export function insideOutline(p: XY, vertices: XY[]): boolean {
  let inside = false;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i++) {
    const [xi, yi] = vertices[i];
    const [xj, yj] = vertices[j];
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** What the maps draw as the flyable space — the same order the agent fits
 *  into (session._flyable): where the measured base station reaches, else a
 *  walked survey saved on the room, else nothing (the default area). */
export function spaceOf(cov: RoomCoverage | null): SpaceLayer | null {
  const ever = cov?.predicted?.everywhere;
  if (ever) return { kind: "predicted", vertices: ever.vertices, z_min: ever.z_min, z_max: ever.z_max, slices: cov?.predicted?.slices };
  if (cov?.measured) return { kind: "measured", vertices: cov.measured.vertices, z_min: cov.measured.z_min, z_max: cov.measured.z_max };
  return null;
}
