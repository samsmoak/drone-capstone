/**
 * The flight keys: which physical keys fly which way, and SHIFT TO REVERSE.
 *
 * Shift is a modifier, never a command of its own (the owner, 2026-09-30:
 * "invert control as long as you hold it"). While it is held the arrows fly
 * the opposite way — ↑ is ↓, ← is → — which is what a drone whose nose points
 * back at you needs. Let go and they are as they were. Nothing is sent for
 * Shift itself and nothing is remembered: it only changes what the held
 * arrows mean, the instant it goes down or up, even mid-hold.
 *
 * W / S (height) are never reversed: up is up whichever way the drone faces.
 * A / D (turning) are not either: a turn looks the same to someone watching
 * from anywhere — clockwise from above is clockwise — so reversing them would
 * make A turn the drone the wrong way.
 *
 * (It replaced a Shift + arrow "correction" that turned the arrows for the
 * rest of the flight: nine presses meaning "reverse" turned them 90° and lost
 * the drone — the lab, 2026-09-30, trace_eeb1d2ef.)
 *
 * Pure, so it is tested without a window: scripts/keys.test.mjs.
 */

import type { Intent } from "@/lib/agent";

/** Physical key → intent field. `code`, so the keys stay in the same place on AZERTY. */
export const KEY_MAP: Record<string, keyof Intent> = {
  ArrowUp: "forward",
  ArrowDown: "back",
  ArrowLeft: "left",
  ArrowRight: "right",
  KeyW: "up",
  KeyS: "down",
  KeyA: "yaw_left",
  KeyD: "yaw_right",
};

/** What Shift turns each arrow into. Everything else is left alone. */
export const REVERSED: Partial<Record<keyof Intent, keyof Intent>> = {
  forward: "back",
  back: "forward",
  left: "right",
  right: "left",
};

export const NO_KEYS: Intent = {
  up: false, down: false, forward: false, back: false,
  left: false, right: false, yaw_left: false, yaw_right: false,
};

/** Is this key one of the two Shifts? */
export function isShift(code: string): boolean {
  return code === "ShiftLeft" || code === "ShiftRight";
}

/** What the held keys ask for, with Shift reversing the arrows. */
export function intentFromKeys(held: Iterable<string>, reversed: boolean): Intent {
  const intent: Intent = { ...NO_KEYS };
  for (const code of held) {
    const field = KEY_MAP[code];
    if (!field) continue;
    intent[reversed ? (REVERSED[field] ?? field) : field] = true;
  }
  return intent;
}

export function sameIntent(a: Intent, b: Intent): boolean {
  return (Object.keys(NO_KEYS) as (keyof Intent)[]).every((k) => a[k] === b[k]);
}
