/**
 * What the arrow keys do, in words — the one place the Control page gets
 * them from (cropwatcher/flight/keyframe.py decides; this only says it).
 *
 * The arrows never follow the drone's nose (the owner, 2026-09-30):
 *   From you   ↑ away from you, ↓ back, ← → round you — right even when the
 *              drone is behind you and you turn to face it.
 *   Room       the room's own directions; ↑ is the forward chosen when the
 *              base stations were set up (`cropwatcher geometry`).
 * and they fall back, said here, when the drone is close to you (room
 * directions), when there is no position (the takeoff direction) or no
 * heading at all (the nose).
 */

import type { Controls, KeyFrameChoice } from "@/lib/agent";

export type ArrowWords = {
  /** After "Position ·" on the keys' caption. */
  short: string;
  /** One sentence under the keys. */
  line: string;
  /** A fallback is in force — say it in the warning tone. */
  warn: boolean;
};

const CHOICE: Record<KeyFrameChoice, string> = { operator: "from you", room: "room" };

export function arrowWords(controls: Controls): ArrowWords {
  const live = controls.live;
  if (!live) {
    if (controls.key_frame === "room") {
      return { short: CHOICE.room, warn: false,
        line: "↑ flies it along the room's forward — the way you faced it when the base stations were set up — whichever way its nose points." };
    }
    return { short: CHOICE.operator, warn: false,
      line: controls.operator
        ? "↑ flies it away from your spot, ↓ back, ← → round you — whichever way its nose points."
        : "↑ flies it away from where it takes off, ↓ back, ← → round it. Press I'm here to measure from where you stand." };
  }
  switch (live.active) {
    case "operator":
      return { short: CHOICE.operator, warn: false,
        line: live.operator_source === "takeoff"
          ? "↑ away from its takeoff spot, ↓ back, ← → round it. I'm here measures from you instead."
          : "↑ away from you, ↓ back, ← → round you. Turn to face it wherever it goes." };
    case "room":
      if (live.reason === "near_operator") {
        // Every flight without a marked spot starts here — it lifts off AT its
        // spot — so that case is said calmly; near YOU is worth the ▲.
        return live.operator_source === "takeoff"
          ? { short: "room", warn: false,
              line: "Near its takeoff spot: the arrows use the room's directions until it is 0.6 m out, then ↑ is away from there." }
          : { short: "near you", warn: true,
              line: "Close to you, “away” has no clear direction: the arrows use the room's until it is 0.6 m out." };
      }
      return { short: CHOICE.room, warn: false,
        line: "↑ is the room's forward, whichever way the nose points." };
    case "takeoff":
      return { short: "takeoff", warn: true,
        line: "No position from the base stations: ↑ keeps the direction it faced at takeoff, however it turns." };
    case "nose":
      return { short: "nose", warn: true,
        line: "No heading reported: the arrows follow the nose, as the drone sees it." };
  }
}
