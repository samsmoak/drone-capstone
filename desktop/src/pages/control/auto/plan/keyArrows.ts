/**
 * The arrow keys, drawn round the drone on the room map — Manual's map
 * (2026-10-24, Samuel: "so that as the drone turns in the air, I know where
 * forward is … and where left and right are").
 *
 * THEY SHOW WHERE EACH KEY MOVES IT, NOT WHERE THE NOSE POINTS. The arrows are
 * never along the nose (backend flight/keyframe.py, locked 2026-09-30): ↑ is
 * away from the operator, the room's forward, or the way the nose pointed at
 * takeoff. An F painted on the nose would be wrong the moment A or D turned
 * it, so the nose is drawn apart, as its own small tick.
 *
 * Directions follow keyframe.py: degrees counter-clockwise from the room's +x,
 * and "left" 90° counter-clockwise of forward (keys_to_room).
 */

/** Where ↑ moves the drone now, degrees from +x (lib/keyDirections.ts). */
export type KeyArrows = { forwardDeg: number };

export type KeyDirection = { key: string; letter: string; word: string; offsetDeg: number };

export const KEY_DIRECTIONS: readonly KeyDirection[] = [
  { key: "↑", letter: "F", word: "Forward", offsetDeg: 0 },
  { key: "←", letter: "L", word: "Left", offsetDeg: 90 },
  { key: "↓", letter: "B", word: "Back", offsetDeg: 180 },
  { key: "→", letter: "R", word: "Right", offsetDeg: -90 },
];

/** A direction's unit vector in the room, from its angle in degrees. */
export function unit(deg: number): [number, number] {
  const r = (deg * Math.PI) / 180;
  return [Math.cos(r), Math.sin(r)];
}
