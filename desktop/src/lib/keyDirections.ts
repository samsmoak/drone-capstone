/**
 * Which way ↑ moves the drone right now, for drawing — Manual's map.
 *
 * A MIRROR, NOT A SECOND DECISION. The agent decides the arrows' frame every
 * tick (backend flight/keyframe.py resolve(), locked 2026-09-30) and tells the
 * app as the session's `controls.live` — but only when the MEANING changes:
 * "away from you" turns continuously as the drone circles and the agent does
 * not send that (manual-control.txt, "THE OPERATOR'S SPOT"). So the direction
 * is worked out here from the same inputs, the same way:
 *
 *   flying (controls.live)   the agent's active frame; "operator" is the
 *                            bearing from the operator's spot to the drone,
 *                            now; "takeoff" the heading it sends; "nose" the
 *                            heading now
 *   on the ground            what resolve() WILL pick: the room, or away from
 *                            a marked spot at least NEAR_OPERATOR_M off (the
 *                            takeoff spot is where the drone sits, so "away"
 *                            from it has no direction yet); with no position,
 *                            the nose — takeoff fixes ↑ to the nose then
 *
 * Read-only: this commands nothing and is not in the lock's file list
 * (lib/arrows.ts and ArrowFrame.tsx are; they are only read).
 */

import type { Controls, XY } from "@/lib/agent";

/** keyframe.py NEAR_OPERATOR_M / FAR_OPERATOR_M — the hysteresis band. */
export const NEAR_OPERATOR_M = 0.5;
export const FAR_OPERATOR_M = 0.6;
/** keyframe.py ROOM_FORWARD_DEG: the room's forward is +x. */
export const ROOM_FORWARD_DEG = 0;

export type KeyFrameNow = "operator" | "room" | "takeoff" | "nose";

export type KeyForward = {
  /** Degrees counter-clockwise from the room's +x; null: nothing to go on. */
  deg: number | null;
  frame: KeyFrameNow | null;
  /** Inside the near-operator circle — fed back in for the hysteresis. */
  near: boolean;
};

const bearing = (from: XY, to: XY) => (Math.atan2(to[1] - from[1], to[0] - from[0]) * 180) / Math.PI;

export function keyForward(controls: Controls | null | undefined, drone: XY | null,
                           yaw: number | null, wasNear = false): KeyForward {
  const live = controls?.live ?? null;
  if (live) {
    switch (live.active) {
      case "operator":
        return live.operator && drone
          ? { deg: bearing(live.operator, drone), frame: "operator", near: false }
          : { deg: live.forward_deg, frame: "operator", near: false };
      case "room":
        return { deg: live.forward_deg ?? ROOM_FORWARD_DEG, frame: "room", near: live.reason === "near_operator" };
      case "takeoff":
        return { deg: live.forward_deg, frame: "takeoff", near: false };
      case "nose":
        return { deg: yaw, frame: "nose", near: false };
    }
  }
  // On the ground: what the agent will resolve at liftoff.
  if (!drone) return { deg: yaw, frame: yaw === null ? null : "takeoff", near: false };
  const spot = controls?.key_frame === "operator" ? controls.operator : null;
  if (!spot) return { deg: ROOM_FORWARD_DEG, frame: "room", near: false };
  const distance = Math.hypot(drone[0] - spot[0], drone[1] - spot[1]);
  const near = distance < (wasNear ? FAR_OPERATOR_M : NEAR_OPERATOR_M);
  return near
    ? { deg: ROOM_FORWARD_DEG, frame: "room", near: true }
    : { deg: bearing(spot, drone), frame: "operator", near: false };
}

/** What ↑ means now, in words, beside the map. */
export const FRAME_WORDS: Record<KeyFrameNow, string> = {
  operator: "↑ is away from you",
  room: "↑ is the room's forward",
  takeoff: "↑ is the way the nose pointed at takeoff",
  nose: "↑ is the way the nose points",
};
