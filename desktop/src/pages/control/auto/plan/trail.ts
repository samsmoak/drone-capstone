/**
 * The path a recorded flight actually flew, for the room map (playback).
 *
 * RUNS, NOT ONE LINE. A run ends wherever the recording has a gap — samples
 * lost on the link — so no line is drawn across time nobody saw; and wherever
 * the position stops (or starts) being measured, so the stretch the drone
 * flew on its own estimate, with no base station, is drawn as such. Each
 * point is [x, y, height above the floor where it took off], in the room's
 * frame — the frame the plan is drawn in.
 */

import type { PlaybackSample } from "@/lib/agent";

export type TrailRun = { points: [number, number, number][]; measured: boolean };
export type Trail = TrailRun[];

/** The samples up to `untilS`, as runs. A sample with no position is skipped.
 *  Each of `gaps` (from the agent: two consecutive samples further apart than
 *  samples lost allows) ends a run at its `from_s` sample and starts the next
 *  at its `to_s` sample. */
export function trailOf(
  samples: PlaybackSample[],
  gaps: { from_s: number; to_s: number }[],
  untilS: number,
): Trail {
  const resumes = new Set(gaps.map((g) => g.to_s));
  const runs: Trail = [];
  let run: TrailRun | null = null;
  for (const s of samples) {
    if (s.t_s > untilS) break;
    if (resumes.has(s.t_s)) run = null;
    if (s.x_m === null || s.y_m === null || s.z_m === null) continue;
    const measured = s.positioned !== false;
    if (!run || run.measured !== measured) {
      const next: TrailRun = { points: [], measured };
      // A change of style joins at the same spot, so the line does not break
      // where only its colour changes.
      if (run && run.points.length) next.points.push(run.points[run.points.length - 1]);
      run = next;
      runs.push(run);
    }
    run.points.push([s.x_m, s.y_m, s.z_m]);
  }
  return runs.filter((r) => r.points.length > 1);
}
