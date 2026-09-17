/**
 * Mission plans built from zones — shared by the planner UI and the server
 * action that queues them. Pure: no I/O, so both sides run the same checks.
 *
 * The plan is the agent's own format, `Mission.to_dict()` in
 * `backend/agent/cropwatcher/flight/missions.py`. The agent re-validates every
 * plan against its geofence and occupancy map before arming; these checks exist
 * so an operator hears "altitude too high" while planning instead of reading
 * "failed" on a mission minutes later. They are never the safety gate.
 *
 * Coordinates: x and y are **absolute Lighthouse metres** — `Flight.goto` sends
 * `go_to(wp.x, wp.y, ground_z + wp.z)`. Only z is relative to the ground
 * captured at takeoff. So a zone's centre, stored in Lighthouse metres, is a
 * waypoint as-is.
 */

import type { ZoneRow } from "@/lib/queries";

/** Mirrors `Geofence` defaults and the agent's `--fence 2.0` default. */
export const FENCE_HALF_EXTENT_M = 2.0;
export const ALTITUDE_MIN_M = 0.1;
export const ALTITUDE_MAX_M = 2.0;
export const HOLD_MAX_S = 30;
export const MAX_WAYPOINTS = 24;
export const NAME_MAX = 80;

/**
 * ASSUMPTION: 0.5 m/s cruise.
 *
 * The agent flies every leg in one `leg_duration_s` and defines no speed limit.
 * Left at its 3 s default, a 4 m leg across the greenhouse is 1.3 m/s indoors.
 * The duration is sized from the longest leg at this speed instead.
 */
const CRUISE_M_S = 0.5;
const LEG_MIN_S = 3;

export type Waypoint = { x: number; y: number; z: number; label: string };

export type MissionPlan = {
  type: "waypoint";
  name: string;
  altitude_m: number;
  hold_s: number;
  leg_duration_s: number;
  return_to_start: boolean;
  metadata: { zone_ids: string[]; source: "planner" };
  waypoints: Waypoint[];
};

export type PlanInput = {
  name: string;
  altitudeM: number;
  holdS: number;
  returnToStart: boolean;
  zoneIds: string[];
};

const round3 = (n: number) => Math.round(n * 1000) / 1000;

export function buildPlan(input: PlanInput, zones: ZoneRow[]): MissionPlan {
  const byId = new Map(zones.map((z) => [z.id, z]));
  const waypoints = input.zoneIds
    .map((id) => byId.get(id))
    .filter((z): z is ZoneRow => Boolean(z))
    .map((z) => ({
      x: round3((z.x_min + z.x_max) / 2),
      y: round3((z.y_min + z.y_max) / 2),
      z: round3(input.altitudeM),
      label: z.label,
    }));

  return {
    type: "waypoint",
    name: input.name.trim(),
    altitude_m: round3(input.altitudeM),
    hold_s: input.holdS,
    leg_duration_s: legDuration(waypoints, input.returnToStart),
    return_to_start: input.returnToStart,
    metadata: { zone_ids: input.zoneIds, source: "planner" },
    waypoints,
  };
}

/** Seconds per leg, from the longest leg — including the one out of the takeoff point. */
function legDuration(waypoints: Waypoint[], returnToStart: boolean): number {
  if (waypoints.length === 0) return LEG_MIN_S;
  // The agent validates legs from (0, 0), so the first leg is measured from there too.
  const points = [{ x: 0, y: 0 }, ...waypoints, ...(returnToStart ? [{ x: 0, y: 0 }] : [])];
  let longest = 0;
  for (let i = 1; i < points.length; i++) {
    longest = Math.max(
      longest,
      Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y),
    );
  }
  return Math.max(LEG_MIN_S, Math.ceil(longest / CRUISE_M_S));
}

/** Takeoff + legs + holds + landing — the same sum as `Mission.estimated_duration_s`. */
export function estimatedDurationS(plan: MissionPlan): number {
  const legs = plan.waypoints.length + (plan.return_to_start ? 1 : 0);
  return 2.0 + legs * plan.leg_duration_s + plan.waypoints.length * plan.hold_s + 2.5;
}

/**
 * Everything wrong with a plan, as sentences an operator can act on.
 *
 * Returns all problems rather than the first, so fixing one does not reveal the
 * next. Names the waypoint and the axis, as the agent's geofence does.
 */
export function validatePlan(plan: MissionPlan): string[] {
  const problems: string[] = [];

  if (!plan.name) problems.push("Give the mission a name.");
  if (plan.name.length > NAME_MAX) problems.push(`Keep the name under ${NAME_MAX} characters.`);

  if (plan.waypoints.length === 0) problems.push("Choose at least one zone to visit.");
  if (plan.waypoints.length > MAX_WAYPOINTS) {
    problems.push(`A mission can visit at most ${MAX_WAYPOINTS} zones.`);
  }

  if (!Number.isFinite(plan.altitude_m) || plan.altitude_m < ALTITUDE_MIN_M || plan.altitude_m > ALTITUDE_MAX_M) {
    problems.push(
      `Altitude must be between ${ALTITUDE_MIN_M.toFixed(2)} and ${ALTITUDE_MAX_M.toFixed(2)} m above the ground.`,
    );
  }
  if (!Number.isFinite(plan.hold_s) || plan.hold_s < 0 || plan.hold_s > HOLD_MAX_S) {
    problems.push(`Hold time must be between 0 and ${HOLD_MAX_S} s.`);
  }

  for (const wp of plan.waypoints) {
    for (const [axis, value] of [["x", wp.x], ["y", wp.y]] as const) {
      if (!Number.isFinite(value) || Math.abs(value) > FENCE_HALF_EXTENT_M) {
        problems.push(
          `Zone ${wp.label}: ${axis}=${value.toFixed(2)} m is outside the permitted ±${FENCE_HALF_EXTENT_M.toFixed(2)} m.`,
        );
      }
    }
  }

  return problems;
}

/**
 * Parse an untrusted plan from a request. The server action receives whatever
 * a client sends, not what the planner UI built — so the plan is rebuilt from
 * zone ids and settings, never accepted as waypoints.
 */
export function parsePlanInput(raw: unknown): PlanInput | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.name !== "string") return null;
  if (typeof r.altitudeM !== "number" || typeof r.holdS !== "number") return null;
  if (typeof r.returnToStart !== "boolean") return null;
  if (!Array.isArray(r.zoneIds) || !r.zoneIds.every((id) => typeof id === "string")) return null;
  return {
    name: r.name,
    altitudeM: r.altitudeM,
    holdS: r.holdS,
    returnToStart: r.returnToStart,
    zoneIds: r.zoneIds as string[],
  };
}
