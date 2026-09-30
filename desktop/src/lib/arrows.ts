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
 * directions), when there is no position (away from you as you stood at
 * takeoff, from where you said its nose pointed) or no heading at all (the
 * nose).
 *
 * WITHOUT A POSITION NOTHING KNOWS WHERE YOU ARE, so it is never implied: the
 * words say it is measured from how you stood at takeoff, and that turning
 * round does not turn the arrows. Only base stations can follow you.
 */

import type { Controls, KeyFrameChoice, NoseFacing } from "@/lib/agent";

export type ArrowWords = {
  /** After "Position ·" on the keys' caption. */
  short: string;
  /** One sentence under the keys. */
  line: string;
  /** A fallback is in force — say it in the warning tone. */
  warn: boolean;
};

const CHOICE: Record<KeyFrameChoice, string> = { operator: "from you", room: "room" };

/** The nose choices, in the order they are offered, with their words. */
export const NOSE_CHOICES: { value: NoseFacing; label: string; where: string }[] = [
  { value: "away", label: "Away", where: "away from you" },
  { value: "left", label: "Left", where: "to your left" },
  { value: "right", label: "Right", where: "to your right" },
  { value: "towards", label: "At me", where: "at you" },
];

const NOSE_WHERE: Record<NoseFacing, string> = Object.fromEntries(
  NOSE_CHOICES.map((c) => [c.value, c.where])) as Record<NoseFacing, string>;

/** `assisted`: the session has a position (base stations). Without one the
 *  frame choice does nothing — the nose choice is what counts. */
export function arrowWords(controls: Controls, assisted: boolean): ArrowWords {
  const live = controls.live;
  if (!live && !assisted) {
    return { short: "from you", warn: true,
      line: "No position from the base stations, so the drone cannot tell where you are. Say where its nose points as you stand, and ↑ flies away from you — kept however it turns." };
  }
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
      return { short: "from you", warn: true,
        // Without a position nothing knows where the operator stands, so "away
        // from you" cannot be measured — it is TOLD (the nose choice) and then
        // kept by the heading. Kept from takeoff, so turning round to follow
        // the drone does not turn the arrows; said, never implied.
        line: `No position: ↑ is away from you as you stood at takeoff (nose ${NOSE_WHERE[controls.nose]}), however it turns. If you turn round, ↑ still goes the way you first faced.` };
    case "nose":
      return { short: "nose", warn: true,
        line: "No heading reported: the arrows follow the nose, as the drone sees it." };
  }
}
