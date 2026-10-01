/**
 * The flyable space, as the room maps draw it (2026-10-01, Samuel: "show what
 * is possible", a see-through blob the plan sits inside).
 *
 * It is where the drone's position can be trusted — Lighthouse coverage
 * (backend mission/plan/coverage.py) — never walls: this drone senses none.
 *   measured   the survey: what a mission flies in
 *   predicted  from the base stations' poses: a guide for the survey
 *   survey     the outline growing while the drone is carried round
 */

import type { XY } from "@/lib/agent";

export type SpaceLayer = {
  kind: "measured" | "predicted" | "survey";
  vertices: XY[];
  z_min: number;
  z_max: number;
  /** A prediction's outline at each height, low to high. */
  slices?: { z_m: number; outline: XY[] }[];
};

export const SPACE_LABEL: Record<SpaceLayer["kind"], string> = {
  measured: "Flyable space (measured)",
  predicted: "Flyable space (predicted — survey to confirm)",
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
